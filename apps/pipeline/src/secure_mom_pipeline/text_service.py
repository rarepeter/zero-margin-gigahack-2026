"""Replaceable HTTP boundary for the text/MoM ML service."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from pathlib import Path
from threading import Lock, Timer
from typing import Final
from uuid import uuid4

import httpx
from pydantic import ValidationError

from .callback_transport import CallbackSender
from .models import TextSubmission


logger = logging.getLogger("secure_mom_pipeline")
MOCK_MOM_DOCUMENT: Final = {
    "schemaVersion": "mom.v1alpha1",
    "quality": {
        "momConfidence": 0.86,
        "confidenceScale": "ZERO_TO_ONE",
    },
    "document": {
        "header": {
            "subject": "Local pipeline demo validation",
            "meeting_type": "other",
            "meeting_type_confidence": "high",
            "date": "2026-09-27",
            "date_source": "recording",
            "languages": {"en": 1.0},
            "participants_mentioned": [
                {
                    "name": "integration team",
                    "role": None,
                    "role_stated": False,
                }
            ],
        },
        "summary": (
            "Participants agreed to validate the local pipeline demo, and the "
            "integration team will verify the review screen by 27 September "
            "2026. 1 decision, 1 action."
        ),
        "decisions": [
            {
                "id": "D1",
                "text": "Validate the local pipeline demo.",
                "status": "decided",
                "evidence": {
                    "quote": (
                        "Participants agreed to validate the local pipeline demo."
                    ),
                    "lang": "en",
                    "segment": 0,
                    "t": "00:00:00",
                    "speaker": "speaker-1",
                },
                "flags": [],
            }
        ],
        "actions": [
            {
                "id": "A1",
                "text": "Verify the review screen",
                "decision_ids": ["D1"],
                "owner": "integration team",
                "deadline": {
                    "spoken": "by 27 September 2026",
                    "resolved": "2026-09-27",
                },
                "evidence": {
                    "quote": (
                        "The integration team will verify the review screen by "
                        "27 September 2026."
                    ),
                    "lang": "en",
                    "segment": 0,
                    "t": "00:00:00",
                    "speaker": "speaker-1",
                },
                "flags": [],
            }
        ],
        "findings": [],
        "topics": [],
        "risks": [],
        "open_questions": [],
    },
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
        callback_sender: CallbackSender | None = None,
    ) -> None:
        self.callback_url_template = callback_url_template
        self.callback_delay_seconds = callback_delay_seconds
        self.transport = transport
        self.callback_sender = callback_sender
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
            headers: Mapping[str, str] = {
                "Content-Type": "application/json",
                "X-Text-Model-Job-Id": model_job_id,
            }
            if self.callback_sender is not None:
                status_code = self.callback_sender(callback_url, payload, headers)
            else:
                with httpx.Client(timeout=5.0, transport=self.transport) as client:
                    response = client.post(
                        callback_url,
                        content=payload,
                        headers=headers,
                    )
                status_code = response.status_code
            callback_succeeded = 200 <= status_code < 300
            if callback_succeeded:
                logger.info(
                    "event=mock_text_callback_accepted job_id=%s model_job_id=%s status_code=%d",
                    pipeline_job_id,
                    model_job_id,
                    status_code,
                )
            else:
                logger.error(
                    "event=mock_text_callback_rejected job_id=%s model_job_id=%s status_code=%d",
                    pipeline_job_id,
                    model_job_id,
                    status_code,
                )
        except (httpx.TransportError, RuntimeError, ValueError) as exc:
            logger.error(
                "event=mock_text_callback_failed job_id=%s model_job_id=%s "
                "error_type=%s",
                pipeline_job_id,
                model_job_id,
                type(exc).__name__,
            )
        finally:
            if not callback_succeeded:
                with self._schedule_lock:
                    self._scheduled.discard((pipeline_job_id, model_job_id))
