"""HTTP boundary for the local speech-to-text ML service."""

from __future__ import annotations

import os
from pathlib import Path

import httpx
from pydantic import ValidationError

from .models import AudioJobRequest, AudioSubmission


class AudioSubmissionError(RuntimeError):
    """Base class for safe audio-service submission failures."""

    retryable = False


class AudioConnectionError(AudioSubmissionError):
    retryable = True


class AudioProtocolError(AudioSubmissionError):
    retryable = False


class HttpAudioService:
    """Submit one recording by local path and return the service's acknowledgement.

    The service reads the recording in place and later pushes the
    schema-version-1 transcription to `callback_url`, or a safe failure to
    `failure_url`; both are URL templates with `{job_id}`.
    """

    def __init__(
        self,
        base_url: str,
        jobs_route: str,
        timeout_seconds: float,
        *,
        callback_url: str,
        failure_url: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.url = f"{base_url.rstrip('/')}/{jobs_route.lstrip('/')}"
        self.timeout_seconds = timeout_seconds
        self.callback_url = callback_url
        self.failure_url = failure_url
        self.transport = transport

    def submit(
        self, pipeline_job_id: str, audio_path: Path, idempotency_key: str
    ) -> AudioSubmission:
        if not audio_path.is_absolute():
            raise AudioProtocolError("The audio input path must be absolute")
        if not audio_path.is_file() or not os.access(audio_path, os.R_OK):
            raise AudioProtocolError("The audio input is not readable")
        request = AudioJobRequest(
            pipeline_job_id=pipeline_job_id,
            audio_path=str(audio_path),
            callback_url=self.callback_url.format(job_id=pipeline_job_id),
            failure_url=self.failure_url.format(job_id=pipeline_job_id),
        )
        try:
            with httpx.Client(timeout=self.timeout_seconds, transport=self.transport) as client:
                response = client.post(
                    self.url,
                    headers={"Idempotency-Key": idempotency_key},
                    json=request.model_dump(mode="json", by_alias=True),
                )
        except httpx.TransportError as exc:
            raise AudioConnectionError("The audio service could not be reached") from exc

        if response.status_code != 202:
            raise AudioProtocolError("The audio service rejected the recording")
        try:
            return AudioSubmission.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise AudioProtocolError(
                "The audio service returned an invalid acknowledgement"
            ) from exc
