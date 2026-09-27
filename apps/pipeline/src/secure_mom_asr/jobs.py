"""Persistent transcription jobs: accept, transcribe one at a time, push the outcome.

Each job has a directory under `<storage root>/jobs/<model job id>/`:

    job.json         correlation with the pipeline job and callback URLs
    normalized.wav   16 kHz mono PCM16 copy of the recording
    segments.json    every recogniser attempt per segment, raw text included,
                     with language class, lexicon matches and speaker overlaps
    result.json      the exact transcription callback body, resent byte for byte
    failure.json     the failure callback body, when transcription failed
    delivered        marker written once the pipeline has the outcome

On startup, undelivered jobs resume: a stored outcome is resent, and a job
interrupted mid-transcription is transcribed again.
"""

from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from queue import Queue
from threading import Event, Lock, Thread
from typing import Literal
from uuid import uuid4

import httpx
from pydantic import BaseModel

from secure_mom_pipeline.models import MomFailure

from .audio import AudioPreparationError
from .config import AsrSettings
from .diarize import DiarizationError, Diarizer
from .lexicon import Lexicon
from .transcribe import NoSpeechError, Recognizer, transcribe_recording
from .whisper import ModelUnavailableError, RecognitionError, WhisperServer


logger = logging.getLogger("secure_mom_asr")

# Waits between delivery attempts while the pipeline API is unreachable. After
# the last one the job stays undelivered until the service restarts.
DELIVERY_BACKOFF_SECONDS = (1, 2, 5, 10, 30, 60, 60, 60, 60, 60)

FAILURES: dict[str, tuple[str, bool]] = {
    "MODEL_UNAVAILABLE": ("The local speech recognition model could not be started.", True),
    "AUDIO_UNREADABLE": ("The recording could not be decoded as audio.", False),
    "NO_SPEECH": ("No speech was recognised in the recording.", False),
    "RECOGNITION_FAILED": ("The local speech recognition model stopped unexpectedly.", True),
    "TRANSCRIPTION_REJECTED": ("The pipeline rejected the transcription.", True),
}


class JobRecord(BaseModel):
    model_job_id: str
    pipeline_job_id: str
    idempotency_key: str
    audio_path: Path
    callback_url: str
    failure_url: str
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
    return MomFailure(code=code, message=message, retryable=retryable).model_dump_json().encode()


class AsrJobs:
    def __init__(
        self,
        settings: AsrSettings,
        frapiz: Recognizer,
        fallback: Recognizer,
        *,
        lexicon: Lexicon | None = None,
        diarizer: Diarizer | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.frapiz = frapiz
        self.fallback = fallback
        self.lexicon = lexicon
        self.diarizer = diarizer
        self.root = settings.storage_root / "jobs"
        self.transport = transport
        self.stopping = Event()
        self._queue: Queue[str | None] = Queue()
        self._by_key: dict[str, JobRecord] = {}
        self._lock = Lock()
        self._thread = Thread(target=self._run, name="asr-jobs", daemon=True)

    def models(self) -> dict[str, str]:
        return {
            **{
                name: getattr(model, "state", "ready")
                for name, model in (("frapiz", self.frapiz), ("fallback", self.fallback))
            },
            "diarization": "enabled" if self.diarizer else "disabled",
            "lexicon": self.settings.lexicon_mode if self.lexicon else "disabled",
        }

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
        # Stopping the models ends a running transcription; the interrupted
        # job stays undelivered and resumes on the next start.
        for model in (self.frapiz, self.fallback):
            if isinstance(model, WhisperServer):
                model.stop()
        self._thread.join(timeout=30)

    def pending(self) -> int:
        return self._queue.qsize()

    def accept(
        self,
        pipeline_job_id: str,
        idempotency_key: str,
        audio_path: Path,
        callback_url: str,
        failure_url: str,
    ) -> JobRecord:
        """Persist a job and queue it; a repeated key returns the first job."""
        with self._lock:
            existing = self._by_key.get(idempotency_key)
            if existing is not None:
                if existing.pipeline_job_id != pipeline_job_id:
                    raise IdempotencyConflictError(idempotency_key)
                return existing
            record = JobRecord(
                model_job_id=f"asr-{uuid4()}",
                pipeline_job_id=pipeline_job_id,
                idempotency_key=idempotency_key,
                audio_path=audio_path,
                callback_url=callback_url,
                failure_url=failure_url,
                created_at=datetime.now().astimezone(),
            )
            staging = self.root / f".{record.model_job_id}"
            staging.mkdir(parents=True)
            _write_atomic(staging / "job.json", record.model_dump_json().encode("utf-8"))
            os.replace(staging, self.root / record.model_job_id)
            self._by_key[idempotency_key] = record
        self._queue.put(record.model_job_id)
        logger.info(
            "event=job_accepted job_id=%s model_job_id=%s", pipeline_job_id, record.model_job_id
        )
        return record

    def _run(self) -> None:
        # Load both models right away so the first job does not wait for them.
        for model in (self.frapiz, self.fallback):
            if isinstance(model, WhisperServer):
                try:
                    model.ensure_ready()
                except ModelUnavailableError as exc:
                    logger.error("event=whisper_unavailable reason=%s", exc)
        if self.diarizer is not None:
            try:
                self.diarizer.ensure_ready()
            except DiarizationError as exc:
                # Transcription still runs; segments go out without speakers.
                logger.error("event=diarization_unavailable reason=%s", exc)
                self.diarizer = None
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
            outcome, body = self._transcribe(record, directory)
            if self.stopping.is_set():
                return
            _write_atomic(directory / f"{outcome}.json", body)
        if result.exists() and not failure.exists():
            delivered = self._deliver(record, "result", result.read_bytes())
            if delivered == "rejected":
                _write_atomic(failure, _failure_body("TRANSCRIPTION_REJECTED"))
        if failure.exists():
            delivered = self._deliver(record, "failure", failure.read_bytes())
        if delivered != "retry":
            (directory / "delivered").touch()

    def _transcribe(
        self, record: JobRecord, directory: Path
    ) -> tuple[Literal["result", "failure"], bytes]:
        logger.info("event=transcription_started model_job_id=%s", record.model_job_id)
        try:
            body = transcribe_recording(
                self.settings,
                self.frapiz,
                self.fallback,
                source=record.audio_path,
                workdir=directory,
                pipeline_job_id=record.pipeline_job_id,
                lexicon=self.lexicon,
                diarizer=self.diarizer,
            )
        except ModelUnavailableError as exc:
            logger.error("event=whisper_unavailable reason=%s", exc)
            return "failure", _failure_body("MODEL_UNAVAILABLE")
        except AudioPreparationError as exc:
            logger.error("event=audio_unreadable reason=%s", exc)
            return "failure", _failure_body("AUDIO_UNREADABLE")
        except NoSpeechError:
            logger.error("event=no_speech model_job_id=%s", record.model_job_id)
            return "failure", _failure_body("NO_SPEECH")
        except RecognitionError as exc:
            if not self.stopping.is_set():
                logger.error("event=recognition_failed reason=%s", exc)
            return "failure", _failure_body("RECOGNITION_FAILED")
        return "result", body

    def _deliver(
        self, record: JobRecord, kind: Literal["result", "failure"], body: bytes
    ) -> Literal["accepted", "rejected", "abandoned", "retry"]:
        url = record.callback_url if kind == "result" else record.failure_url
        headers = {"Content-Type": "application/json", "X-Audio-Model-Job-Id": record.model_job_id}
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
        logger.error("event=callback_undelivered kind=%s model_job_id=%s", kind, record.model_job_id)
        return "retry"
