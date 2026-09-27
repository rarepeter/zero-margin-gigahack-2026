"""HTTP boundary for the local text/MoM ML service."""

from __future__ import annotations

import os
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path

import httpx
from pydantic import ValidationError

from .models import TextSubmission


class TextSubmissionError(RuntimeError):
    """Base class for safe text-service submission failures."""

    retryable = False


class TextConnectionError(TextSubmissionError):
    retryable = True


class TextProtocolError(TextSubmissionError):
    retryable = False


class HttpTextService:
    """Submit one MoM generation job and return the service's acknowledgement.

    The multipart body carries the derived `transcript.txt`, the persisted
    schema-version-1 transcription (whose segment IDs the MoM evidence must
    cite), and the upload time used as the meeting date when the recording
    has none. Generation finishes later through the MoM callback.
    """

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
        *,
        transcription_path: Path,
        uploaded_at: datetime,
    ) -> TextSubmission:
        for path in (text_path, transcription_path):
            if not path.is_absolute():
                raise TextProtocolError("The text input path must be absolute")
            if not path.is_file() or not os.access(path, os.R_OK):
                raise TextProtocolError("The text input is not readable")

        try:
            with ExitStack() as streams:
                transcript = streams.enter_context(text_path.open("rb"))
                transcription = streams.enter_context(transcription_path.open("rb"))
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
                        data={"uploadedAt": uploaded_at.isoformat()},
                        files={
                            "transcript": (
                                "transcript.txt",
                                transcript,
                                "text/plain; charset=utf-8",
                            ),
                            "transcription": (
                                "transcription.json",
                                transcription,
                                "application/json",
                            ),
                        },
                    )
        except OSError as exc:
            raise TextProtocolError("The text input could not be read") from exc
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
