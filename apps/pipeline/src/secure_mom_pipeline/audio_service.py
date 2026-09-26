"""Replaceable mock boundary for the audio-processing ML service."""

from __future__ import annotations

import logging
import os
from threading import Lock, Timer
from pathlib import Path
from typing import Final
from uuid import uuid4

import httpx

from .models import AudioSubmission


logger = logging.getLogger("secure_mom_pipeline")
MOCK_TRANSCRIPTION_MEDIA_TYPE: Final = "text/plain; charset=utf-8"


class AudioSubmissionError(RuntimeError):
    """Raised when the mock service cannot pick up its local audio input."""


class MockAudioService:
    """Acknowledge audio, then push a deterministic mock transcription."""

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

    def submit(self, pipeline_job_id: str, audio_path: Path) -> AudioSubmission:
        if not audio_path.is_absolute():
            raise AudioSubmissionError("The audio input path must be absolute")
        if not audio_path.is_file() or not os.access(audio_path, os.R_OK):
            raise AudioSubmissionError("The audio input is not readable")
        submission = AudioSubmission(
            model_job_id=f"mock-audio-{uuid4()}",
            status="accepted",
        )
        self.ensure_callback(pipeline_job_id, submission.model_job_id)
        return submission

    def ensure_callback(self, pipeline_job_id: str, model_job_id: str) -> None:
        """Schedule one callback, including after recovery from a worker restart."""
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
            "event=mock_audio_callback_scheduled job_id=%s model_job_id=%s delay_seconds=%s",
            pipeline_job_id,
            model_job_id,
            self.callback_delay_seconds,
        )

    def _send_callback(self, pipeline_job_id: str, model_job_id: str) -> None:
        callback_succeeded = False
        try:
            callback_url = self.callback_url_template.format(job_id=pipeline_job_id)
            transcription = (
                f"Mock transcription for pipeline job {pipeline_job_id}."
            ).encode("utf-8")
            with httpx.Client(timeout=5.0, transport=self.transport) as client:
                response = client.post(
                    callback_url,
                    content=transcription,
                    headers={
                        "Content-Type": MOCK_TRANSCRIPTION_MEDIA_TYPE,
                        "X-Audio-Model-Job-Id": model_job_id,
                    },
                )
            callback_succeeded = 200 <= response.status_code < 300
            if callback_succeeded:
                logger.info(
                    "event=mock_audio_callback_accepted job_id=%s model_job_id=%s status_code=%d",
                    pipeline_job_id,
                    model_job_id,
                    response.status_code,
                )
            else:
                logger.error(
                    "event=mock_audio_callback_rejected job_id=%s model_job_id=%s status_code=%d",
                    pipeline_job_id,
                    model_job_id,
                    response.status_code,
                )
        except (httpx.TransportError, ValueError):
            logger.error(
                "event=mock_audio_callback_failed job_id=%s model_job_id=%s",
                pipeline_job_id,
                model_job_id,
            )
        finally:
            if not callback_succeeded:
                with self._schedule_lock:
                    self._scheduled.discard((pipeline_job_id, model_job_id))
