"""Replaceable HTTP boundary for the text/MoM ML service."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from threading import Lock, Timer
from typing import Final
from uuid import uuid4

import httpx
from pydantic import ValidationError

from .models import TextSubmission


logger = logging.getLogger("secure_mom_pipeline")
MOCK_MOM_DOCUMENT: Final = {
    "schemaVersion": "mock-v1",
    "document": {"content": "Mock Minutes of Meeting"},
}


class TextSubmissionError(RuntimeError):
    """Base class for safe text-service submission failures."""

    retryable = False


class TextConnectionError(TextSubmissionError):
    retryable = True


class TextProtocolError(TextSubmissionError):
    retryable = False


class HttpTextService:
    def __init__(
        self,
        base_url: str,
        jobs_route: str,
        timeout_seconds: float,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.url = f"{base_url.rstrip('/')}/{jobs_route.lstrip('/')}"
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def submit(
        self,
        pipeline_job_id: str,
        text_path: Path,
        idempotency_key: str,
    ) -> TextSubmission:
        if not text_path.is_absolute():
            raise TextProtocolError("The text input path must be absolute")
        if not text_path.is_file() or not os.access(text_path, os.R_OK):
            raise TextProtocolError("The text input is not readable")

        try:
            stream = text_path.open("rb")
        except OSError as exc:
            raise TextProtocolError("The text input could not be read") from exc

        try:
            with stream:
                with httpx.Client(
                    timeout=self.timeout_seconds,
                    transport=self.transport,
                ) as client:
                    response = client.post(
                        self.url,
                        headers={
                            "X-Pipeline-Job-Id": pipeline_job_id,
                            "Idempotency-Key": idempotency_key,
                        },
                        files={
                            "transcript": (
                                "transcript.txt",
                                stream,
                                "text/plain; charset=utf-8",
                            )
                        },
                    )
        except httpx.TransportError as exc:
            raise TextConnectionError("The text service could not be reached") from exc

        if response.status_code != 202:
            raise TextProtocolError("The text service rejected the transcription")
        try:
            return TextSubmission.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise TextProtocolError(
                "The text service returned an invalid acknowledgement"
            ) from exc


class MockTextService:
    """Acknowledge UTF-8 text, then push a deterministic mock MoM document."""

    def __init__(
        self,
        callback_url_template: str | None = None,
        callback_delay_seconds: float = 5.0,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.callback_url_template = callback_url_template
        self.callback_delay_seconds = callback_delay_seconds
        self.transport = transport
        self._scheduled: set[tuple[str, str]] = set()
        self._schedule_lock = Lock()

    def submit(
        self,
        pipeline_job_id: str,
        text_path: Path,
        idempotency_key: str,
    ) -> TextSubmission:
        del idempotency_key
        if not text_path.is_absolute() or not text_path.is_file():
            raise TextProtocolError("The text input is not readable")
        try:
            text_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise TextProtocolError("The text input is not valid UTF-8") from exc
        submission = TextSubmission(
            model_job_id=f"mock-text-{uuid4()}",
            status="accepted",
        )
        self.ensure_callback(pipeline_job_id, submission.model_job_id)
        return submission

    def ensure_callback(self, pipeline_job_id: str, model_job_id: str) -> None:
        if self.callback_url_template is None:
            return
        key = (pipeline_job_id, model_job_id)
        with self._schedule_lock:
            if key in self._scheduled:
                return
            self._scheduled.add(key)

        timer = Timer(
            self.callback_delay_seconds,
            self._send_callback,
            args=(pipeline_job_id, model_job_id),
        )
        timer.daemon = True
        timer.start()
        logger.info(
            "event=mock_text_callback_scheduled job_id=%s model_job_id=%s delay_seconds=%s",
            pipeline_job_id,
            model_job_id,
            self.callback_delay_seconds,
        )

    def _send_callback(self, pipeline_job_id: str, model_job_id: str) -> None:
        callback_succeeded = False
        try:
            callback_url = self.callback_url_template.format(job_id=pipeline_job_id)
            payload = json.dumps(
                MOCK_MOM_DOCUMENT,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            with httpx.Client(timeout=5.0, transport=self.transport) as client:
                response = client.post(
                    callback_url,
                    content=payload,
                    headers={
                        "Content-Type": "application/json",
                        "X-Text-Model-Job-Id": model_job_id,
                    },
                )
            callback_succeeded = 200 <= response.status_code < 300
            if callback_succeeded:
                logger.info(
                    "event=mock_text_callback_accepted job_id=%s model_job_id=%s status_code=%d",
                    pipeline_job_id,
                    model_job_id,
                    response.status_code,
                )
            else:
                logger.error(
                    "event=mock_text_callback_rejected job_id=%s model_job_id=%s status_code=%d",
                    pipeline_job_id,
                    model_job_id,
                    response.status_code,
                )
        except (httpx.TransportError, ValueError):
            logger.error(
                "event=mock_text_callback_failed job_id=%s model_job_id=%s",
                pipeline_job_id,
                model_job_id,
            )
        finally:
            if not callback_succeeded:
                with self._schedule_lock:
                    self._scheduled.discard((pipeline_job_id, model_job_id))
