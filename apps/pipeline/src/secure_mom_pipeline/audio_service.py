"""Replaceable mock boundary for the audio-processing ML service."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from threading import Lock, Timer
from pathlib import Path
from typing import Final
from uuid import uuid4

import httpx

from .callback_transport import CallbackSender
from .models import AudioSubmission


logger = logging.getLogger("secure_mom_pipeline")
MOCK_TRANSCRIPTION_MEDIA_TYPE: Final = "application/json"


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
        callback_sender: CallbackSender | None = None,
    ) -> None:
        self.callback_url_template = callback_url_template
        self.callback_delay_seconds = callback_delay_seconds
        self.transport = transport
        self.callback_sender = callback_sender
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
            text = f"Mock transcription for pipeline job {pipeline_job_id}."
            transcription = json.dumps(
                {
                    "schemaVersion": "transcription.v1alpha1",
                    "jobId": pipeline_job_id,
                    "transcript": {
                        "text": text,
                        "segments": [
                            {
                                "id": "segment-1",
                                "startMs": 0,
                                "endMs": 3000,
                                "speakerId": "speaker-1",
                                "languages": ["en"],
                                "text": text,
                                "confidence": 0.94,
                            }
                        ],
                    },
                    "audioMetadata": {"durationMs": 3000},
                    "languageDetection": {
                        "languages": [{"code": "en", "proportion": 1.0}]
                    },
                    "speakers": [
                        {
                            "id": "speaker-1",
                            "displayName": None,
                            "languages": ["en"],
                            "speakingTimeProportion": 1.0,
                        }
                    ],
                    "quality": {
                        "transcriptConfidence": 0.91,
                        "confidenceScale": "ZERO_TO_ONE",
                    },
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            headers: Mapping[str, str] = {
                "Content-Type": MOCK_TRANSCRIPTION_MEDIA_TYPE,
                "X-Audio-Model-Job-Id": model_job_id,
            }
            if self.callback_sender is not None:
                status_code = self.callback_sender(
                    callback_url,
                    transcription,
                    headers,
                )
            else:
                with httpx.Client(timeout=5.0, transport=self.transport) as client:
                    response = client.post(
                        callback_url,
                        content=transcription,
                        headers=headers,
                    )
                status_code = response.status_code
            callback_succeeded = 200 <= status_code < 300
            if callback_succeeded:
                logger.info(
                    "event=mock_audio_callback_accepted job_id=%s model_job_id=%s status_code=%d",
                    pipeline_job_id,
                    model_job_id,
                    status_code,
                )
            else:
                logger.error(
                    "event=mock_audio_callback_rejected job_id=%s model_job_id=%s status_code=%d",
                    pipeline_job_id,
                    model_job_id,
                    status_code,
                )
        except (httpx.TransportError, RuntimeError, ValueError) as exc:
            logger.error(
                "event=mock_audio_callback_failed job_id=%s model_job_id=%s "
                "error_type=%s",
                pipeline_job_id,
                model_job_id,
                type(exc).__name__,
            )
        finally:
            if not callback_succeeded:
                with self._schedule_lock:
                    self._scheduled.discard((pipeline_job_id, model_job_id))
