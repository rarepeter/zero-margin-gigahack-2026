"""Replaceable mock boundary for the audio-processing ML service."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from .models import AudioSubmission


class AudioSubmissionError(RuntimeError):
    """Raised when the mock service cannot pick up its local audio input."""


class MockAudioService:
    """Acknowledge an accessible file without reading or processing its content."""

    def submit(self, pipeline_job_id: str, audio_path: Path) -> AudioSubmission:
        del pipeline_job_id
        if not audio_path.is_absolute():
            raise AudioSubmissionError("The audio input path must be absolute")
        if not audio_path.is_file() or not os.access(audio_path, os.R_OK):
            raise AudioSubmissionError("The audio input is not readable")
        return AudioSubmission(
            model_job_id=f"mock-audio-{uuid4()}",
            status="accepted",
        )
