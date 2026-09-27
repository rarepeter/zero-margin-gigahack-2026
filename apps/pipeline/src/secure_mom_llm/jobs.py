"""Persistent MoM jobs: accept, generate one at a time, and push the outcome.

Each job has a directory under `<storage root>/jobs/<model job id>/`:

    job.json            correlation with the pipeline job, written once
    transcription.json  the pipeline's structured transcription
    result.json         the exact MoM callback body, resent byte for byte
    failure.json        the failure callback body, when generation failed
    delivered           marker written once the pipeline has the outcome

On startup, undelivered jobs resume: a stored outcome is resent, and a job
interrupted mid-generation is generated again.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from queue import Queue
from threading import Event, Lock, Thread
from typing import Any, Literal, Protocol
from uuid import uuid4

import httpx
from pydantic import BaseModel, ValidationError

from secure_mom_pipeline.models import MomFailure, TranscriptionResult

from .assemble import assemble, meeting_date, serialize
from .config import LlmSettings
from .draft import Draft, draft_json_schema
from .llama import (
    Generation,
    GenerationError,
    ModelState,
    ModelUnavailableError,
    TranscriptTooLongError,
)
from .prompt import system_prompt, user_message


logger = logging.getLogger("secure_mom_llm")

# Waits between delivery attempts while the pipeline API is unreachable. After
# the last one the job stays undelivered until the service restarts.
DELIVERY_BACKOFF_SECONDS = (1, 2, 5, 10, 30, 60, 60, 60, 60, 60)

FAILURES: dict[str, tuple[str, bool]] = {
    "MODEL_UNAVAILABLE": ("The local language model could not be started.", True),
    "TRANSCRIPT_TOO_LONG": (
        "The transcript is too long for the configured model context.",
        False,
    ),
    "NO_TRANSCRIPT_SEGMENTS": ("The transcript has no segments to cite.", False),
    "GENERATION_FAILED": (
        "The local language model stopped before finishing the minutes.",
        True,
    ),
    "INVALID_MODEL_OUTPUT": (
        "The local language model returned minutes in an invalid structure.",
        True,
    ),
    "MOM_REJECTED": ("The pipeline rejected the generated minutes.", True),
}


class Model(Protocol):
    state: ModelState

    def ensure_ready(self) -> None: ...

    def stop(self) -> None: ...

    def generate(self, system: str, user: str, schema: dict[str, Any]) -> Generation: ...


class JobRecord(BaseModel):
    model_job_id: str
    pipeline_job_id: str
    idempotency_key: str
    uploaded_at: datetime
    created_at: datetime


class IdempotencyConflictError(ValueError):
    """An idempotency key was reused for a different pipeline job."""


def _write_atomic(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _failure_body(code: str) -> bytes:
    message, retryable = FAILURES[code]
    failure = MomFailure(code=code, message=message, retryable=retryable)
    return failure.model_dump_json().encode("utf-8")


class MomJobs:
    def __init__(
        self,
        settings: LlmSettings,
        model: Model,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.model = model
        self.root = settings.storage_root / "jobs"
        self.transport = transport
        self.stopping = Event()
        self._queue: Queue[str | None] = Queue()
        self._by_key: dict[str, JobRecord] = {}
        self._lock = Lock()
        self._thread = Thread(target=self._run, name="mom-llm-jobs", daemon=True)

    def start(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        records = []
        for directory in self.root.iterdir():
            if not directory.is_dir():
                continue
            if directory.name.startswith("."):
                shutil.rmtree(directory)  # an acceptance interrupted mid-write
                continue
            record = JobRecord.model_validate_json((directory / "job.json").read_bytes())
            self._by_key[record.idempotency_key] = record
            if not (directory / "delivered").exists():
                records.append(record)
        for record in sorted(records, key=lambda r: r.created_at):
            self._queue.put(record.model_job_id)
        if records:
            logger.info("event=jobs_resumed count=%d", len(records))
        self._thread.start()

    def stop(self) -> None:
        self.stopping.set()
        self._queue.put(None)
        # Stopping the model ends any running generation; the interrupted job
        # stays undelivered and resumes on the next start.
        self.model.stop()
        self._thread.join(timeout=30)

    def pending(self) -> int:
        return self._queue.qsize()

    def accept(
        self,
        pipeline_job_id: str,
        idempotency_key: str,
        uploaded_at: datetime,
        transcription: bytes,
    ) -> JobRecord:
        """Persist a job and queue it; a repeated key returns the first job."""
        with self._lock:
            existing = self._by_key.get(idempotency_key)
            if existing is not None:
                if existing.pipeline_job_id != pipeline_job_id:
                    raise IdempotencyConflictError(idempotency_key)
                return existing
            record = JobRecord(
                model_job_id=f"mom-llm-{uuid4()}",
                pipeline_job_id=pipeline_job_id,
                idempotency_key=idempotency_key,
                uploaded_at=uploaded_at,
                created_at=datetime.now().astimezone(),
            )
            staging = self.root / f".{record.model_job_id}"
            staging.mkdir(parents=True)
            _write_atomic(staging / "transcription.json", transcription)
            _write_atomic(staging / "job.json", record.model_dump_json().encode("utf-8"))
            os.replace(staging, self.root / record.model_job_id)
            self._by_key[idempotency_key] = record
        self._queue.put(record.model_job_id)
        logger.info(
            "event=job_accepted job_id=%s model_job_id=%s",
            pipeline_job_id,
            record.model_job_id,
        )
        return record

    def _run(self) -> None:
        # Load the model right away so the first job does not wait for it.
        try:
            self.model.ensure_ready()
        except ModelUnavailableError as exc:
            logger.error("event=llama_unavailable reason=%s", exc)
        while (model_job_id := self._queue.get()) is not None:
            if self.stopping.is_set():
                return
            try:
                self._process(self.root / model_job_id)
            except Exception:  # keep serving later jobs
                logger.exception("event=job_crashed model_job_id=%s", model_job_id)

    def _process(self, directory: Path) -> None:
        record = JobRecord.model_validate_json((directory / "job.json").read_bytes())
        result, failure = directory / "result.json", directory / "failure.json"
        delivered = "retry"
        if not result.exists() and not failure.exists():
            outcome, body = self._generate(record, directory)
            if self.stopping.is_set():
                return
            _write_atomic(directory / f"{outcome}.json", body)
        if result.exists() and not failure.exists():
            delivered = self._deliver(record, "result", result.read_bytes())
            if delivered == "rejected":
                _write_atomic(failure, _failure_body("MOM_REJECTED"))
        if failure.exists():
            delivered = self._deliver(record, "failure", failure.read_bytes())
        if delivered != "retry":
            (directory / "delivered").touch()

    def _generate(
        self, record: JobRecord, directory: Path
    ) -> tuple[Literal["result", "failure"], bytes]:
        transcription = TranscriptionResult.model_validate_json(
            (directory / "transcription.json").read_bytes()
        )
        segments = transcription.transcript.segments
        if not segments:
            return "failure", _failure_body("NO_TRANSCRIPT_SEGMENTS")
        language = self.settings.output_language
        held_on, date_source = meeting_date(transcription, record.uploaded_at)
        started = time.monotonic()
        logger.info(
            "event=generation_started model_job_id=%s segments=%d",
            record.model_job_id,
            len(segments),
        )
        try:
            self.model.ensure_ready()
            generation = self.model.generate(
                system_prompt(language),
                user_message(transcription, held_on, date_source, language),
                draft_json_schema(len(segments)),
            )
        except ModelUnavailableError as exc:
            logger.error("event=llama_unavailable reason=%s", exc)
            return "failure", _failure_body("MODEL_UNAVAILABLE")
        except TranscriptTooLongError as exc:
            logger.error("event=transcript_too_long reason=%s", exc)
            return "failure", _failure_body("TRANSCRIPT_TOO_LONG")
        except GenerationError as exc:
            if not self.stopping.is_set():
                logger.error("event=generation_failed reason=%s", exc)
            return "failure", _failure_body("GENERATION_FAILED")

        try:
            draft = Draft.model_validate_json(generation.text)
            mom, replaced_quotes = assemble(
                draft, transcription, record.uploaded_at, language
            )
        except (ValidationError, ValueError) as exc:
            logger.error(
                "event=invalid_model_output model_job_id=%s error_type=%s",
                record.model_job_id,
                type(exc).__name__,
            )
            return "failure", _failure_body("INVALID_MODEL_OUTPUT")

        document = mom.document
        logger.info(
            "event=generation_completed model_job_id=%s elapsed_s=%.0f "
            "prompt_tokens=%d reasoning_tokens=%d answer_tokens=%d decisions=%d "
            "actions=%d findings=%d replaced_quotes=%d",
            record.model_job_id,
            time.monotonic() - started,
            generation.prompt_tokens,
            generation.reasoning_tokens,
            generation.answer_tokens,
            len(document.decisions),
            len(document.actions),
            len(document.findings),
            replaced_quotes,
        )
        return "result", serialize(mom)

    def _deliver(
        self, record: JobRecord, kind: Literal["result", "failure"], body: bytes
    ) -> Literal["accepted", "rejected", "abandoned", "retry"]:
        route = self.settings.result_route if kind == "result" else self.settings.failure_route
        url = self.settings.callback_base_url.rstrip("/") + route.format(
            job_id=record.pipeline_job_id
        )
        headers = {
            "Content-Type": "application/json",
            "X-Text-Model-Job-Id": record.model_job_id,
        }
        for delay in (0, *DELIVERY_BACKOFF_SECONDS):
            if self.stopping.wait(delay):
                return "retry"
            try:
                with httpx.Client(timeout=30.0, transport=self.transport) as client:
                    status = client.post(url, content=body, headers=headers).status_code
            except httpx.TransportError:
                continue
            logger.info(
                "event=callback_answered kind=%s job_id=%s model_job_id=%s status_code=%d",
                kind,
                record.pipeline_job_id,
                record.model_job_id,
                status,
            )
            if 200 <= status < 300:
                return "accepted"
            if status in (404, 409):
                # Unknown job, superseded attempt, or the job moved on.
                return "abandoned"
            if status < 500:
                return "rejected" if kind == "result" else "abandoned"
        logger.error(
            "event=callback_undelivered kind=%s model_job_id=%s",
            kind,
            record.model_job_id,
        )
        return "retry"
