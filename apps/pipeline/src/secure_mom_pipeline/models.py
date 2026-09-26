"""Versioned models persisted and exposed by the first real pipeline slice."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class PipelineModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    TRANSCRIBING = "TRANSCRIBING"
    FAILED = "FAILED"


class JobAttempts(PipelineModel):
    transcription: int = 0
    mom_generation: int = Field(default=0, alias="momGeneration")


class ModelJobs(PipelineModel):
    audio: str | None = None
    text: str | None = None


class JobArtifacts(PipelineModel):
    audio: str
    transcript: str | None = None
    mom: str | None = None


class JobError(PipelineModel):
    code: str
    message: str
    retryable: bool


class JobState(PipelineModel):
    schema_version: int = Field(default=1, alias="schemaVersion")
    job_id: str = Field(alias="jobId")
    status: JobStatus
    stage: str
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    attempts: JobAttempts = Field(default_factory=JobAttempts)
    model_jobs: ModelJobs = Field(default_factory=ModelJobs, alias="modelJobs")
    artifacts: JobArtifacts
    error: JobError | None = None


class CreateJobResponse(PipelineModel):
    job_id: str = Field(alias="jobId")
    status: JobStatus
    stage: str
    created_at: datetime = Field(alias="createdAt")


class ArtifactAvailability(PipelineModel):
    transcript_available: bool = Field(alias="transcriptAvailable")
    mom_available: bool = Field(alias="momAvailable")


class JobStatusResponse(PipelineModel):
    job_id: str = Field(alias="jobId")
    status: JobStatus
    stage: str
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    artifacts: ArtifactAvailability
    error: JobError | None

    @classmethod
    def from_state(cls, state: JobState) -> JobStatusResponse:
        return cls(
            job_id=state.job_id,
            status=state.status,
            stage=state.stage,
            created_at=state.created_at,
            updated_at=state.updated_at,
            artifacts=ArtifactAvailability(
                transcript_available=state.artifacts.transcript is not None,
                mom_available=state.artifacts.mom is not None,
            ),
            error=state.error,
        )


class ErrorDetail(PipelineModel):
    code: str
    message: str
    retryable: bool


class ErrorEnvelope(PipelineModel):
    error: ErrorDetail


class EventRecord(PipelineModel):
    schema_version: int = Field(default=1, alias="schemaVersion")
    offset: int
    timestamp: datetime
    topic: str = "pipeline.job-events"
    key: str
    event_type: str = Field(alias="eventType")
    producer: str
    value: dict[str, Any]


class AudioSubmission(PipelineModel):
    model_job_id: str = Field(alias="modelJobId", min_length=1)
    status: Literal["accepted"]
