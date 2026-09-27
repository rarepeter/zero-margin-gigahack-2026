"""Test doubles shared by the pipeline test modules."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from secure_mom_pipeline.models import AudioSubmission


class AcceptingAudioService:
    """Acknowledges every recording, as the speech-to-text service does."""

    def __init__(self) -> None:
        self.submissions: list[tuple[str, Path, str]] = []

    def submit(
        self, pipeline_job_id: str, audio_path: Path, idempotency_key: str
    ) -> AudioSubmission:
        self.submissions.append((pipeline_job_id, audio_path, idempotency_key))
        return AudioSubmission(model_job_id=f"audio-{uuid4()}", status="accepted")
