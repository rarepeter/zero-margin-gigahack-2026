"""Versioned models persisted and exposed by the first real pipeline slice."""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class PipelineModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class ContractModel(PipelineModel):
    """Strict model used at ML and portal-facing data boundaries."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    TRANSCRIBING = "TRANSCRIBING"
    GENERATING_MOM = "GENERATING_MOM"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    FAILED = "FAILED"


class JobAttempts(PipelineModel):
    transcription: int = 0
    mom_generation: int = Field(default=0, alias="momGeneration")


class ModelJobs(PipelineModel):
    audio: str | None = None
    text: str | None = None


class ArtifactDescriptor(PipelineModel):
    path: str = Field(min_length=1)
    media_type: str = Field(alias="mediaType", min_length=1)
    byte_count: int = Field(alias="byteCount", ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SubmittedBy(PipelineModel):
    user_id: str = Field(alias="userId", min_length=1)
    display_name: str | None = Field(default=None, alias="displayName")
    email: str = Field(min_length=3, pattern=r"^[^@\s]+@[^@\s]+$")


class PublicSubmittedBy(PipelineModel):
    user_id: str = Field(alias="userId", min_length=1)
    display_name: str | None = Field(default=None, alias="displayName")


class SourceRecording(PipelineModel):
    original_file_name: str = Field(alias="originalFileName", min_length=1)
    media_type: str = Field(alias="mediaType", min_length=1)
    size_bytes: int = Field(alias="sizeBytes", ge=1)


class JobArtifacts(PipelineModel):
    audio: str
    transcript: str | None = None
    mom: str | None = None
    transcription_source: ArtifactDescriptor | None = Field(
        default=None,
        alias="transcriptionSource",
    )
    text_input: ArtifactDescriptor | None = Field(default=None, alias="textInput")
    mom_output: ArtifactDescriptor | None = Field(default=None, alias="momOutput")
    review_context: ArtifactDescriptor | None = Field(
        default=None,
        alias="reviewContext",
    )


class JobError(PipelineModel):
    code: str
    message: str
    retryable: bool


class JobState(PipelineModel):
    schema_version: int = Field(default=3, alias="schemaVersion")
    job_id: str = Field(alias="jobId")
    status: JobStatus
    stage: str
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    attempts: JobAttempts = Field(default_factory=JobAttempts)
    model_jobs: ModelJobs = Field(default_factory=ModelJobs, alias="modelJobs")
    artifacts: JobArtifacts
    submitted_by: SubmittedBy | None = Field(default=None, alias="submittedBy")
    source_recording: SourceRecording | None = Field(
        default=None,
        alias="sourceRecording",
    )
    error: JobError | None = None


class CreateJobResponse(PipelineModel):
    job_id: str = Field(alias="jobId")
    status: JobStatus
    stage: str
    created_at: datetime = Field(alias="createdAt")


class ArtifactAvailability(PipelineModel):
    transcript_available: bool = Field(alias="transcriptAvailable")
    mom_available: bool = Field(alias="momAvailable")
    review_context_available: bool = Field(alias="reviewContextAvailable")


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
                review_context_available=state.artifacts.review_context is not None,
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


class TranscriptionSource(PipelineModel):
    data: bytes
    media_type: str = Field(alias="mediaType", min_length=1)


class TextDocument(PipelineModel):
    text: str


class TranscriptSegment(ContractModel):
    id: str = Field(min_length=1)
    start_ms: int = Field(alias="startMs", ge=0)
    end_ms: int | None = Field(alias="endMs", ge=0)
    speaker_id: str | None = Field(alias="speakerId", min_length=1)
    languages: list[str]
    text: str = Field(min_length=1)
    confidence: float | None = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_time_range(self) -> TranscriptSegment:
        if self.end_ms is not None and self.end_ms < self.start_ms:
            raise ValueError("endMs must be greater than or equal to startMs")
        return self


class TranscriptContent(ContractModel):
    text: str = Field(min_length=1)
    segments: list[TranscriptSegment]


class AudioMetadata(ContractModel):
    duration_ms: int = Field(alias="durationMs", gt=0)
    # The audio service may extract a container/recording timestamp.  The
    # pipeline never substitutes the filesystem creation time: that time can
    # change when a recording is copied to the demo machine.
    recorded_at: datetime | None = Field(default=None, alias="recordedAt")


class DetectedLanguage(ContractModel):
    code: str = Field(min_length=2, max_length=16)
    proportion: float = Field(ge=0, le=1)


class LanguageDetection(ContractModel):
    languages: list[DetectedLanguage]


class TranscriptionSpeaker(ContractModel):
    id: str = Field(min_length=1)
    display_name: str | None = Field(alias="displayName")
    languages: list[str]
    speaking_time_proportion: float | None = Field(
        alias="speakingTimeProportion",
        ge=0,
        le=1,
    )


class TranscriptionQuality(ContractModel):
    transcript_confidence: float | None = Field(
        default=None,
        alias="transcriptConfidence",
        ge=0,
        le=1,
    )
    confidence_scale: Literal["ZERO_TO_ONE"] = Field(
        alias="confidenceScale",
    )


class TranscriptionResult(ContractModel):
    schema_version: Literal[1] = Field(alias="schemaVersion")
    job_id: str = Field(alias="jobId", min_length=1)
    transcript: TranscriptContent
    audio_metadata: AudioMetadata = Field(alias="audioMetadata")
    language_detection: LanguageDetection = Field(alias="languageDetection")
    speakers: list[TranscriptionSpeaker]
    quality: TranscriptionQuality


class MomQuality(ContractModel):
    mom_confidence: float | None = Field(
        default=None,
        alias="momConfidence",
        ge=0,
        le=1,
    )
    confidence_scale: Literal["ZERO_TO_ONE"] = Field(
        alias="confidenceScale",
    )


MomLanguage = Literal["ro", "ru", "en", "mixed"]
MeetingType = Literal[
    "medical",
    "patient_case",
    "financial",
    "administrative",
    "executive",
    "operational",
    "crisis",
    "other",
]
FlagType = Literal["number", "decision_status", "owner", "deadline", "term"]


class MomEvidence(ContractModel):
    """Trace an MoM statement to an immutable transcription segment ID."""

    quote: str = Field(min_length=1)
    lang: MomLanguage
    segment_id: str = Field(min_length=1)
    # Kept only as a migration aid for the current portal fixture. New model
    # output and all new consumers must use segment_id.
    segment: int | None = Field(default=None, ge=0)
    t: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}:\d{2}$")
    speaker: str | None = None


class MomFlag(ContractModel):
    type: FlagType
    reason: str = Field(min_length=1)
    blocking: bool
    candidates: list[str] | None = None


class MomParticipant(ContractModel):
    name: str = Field(min_length=1)
    role: str | None = None
    role_stated: bool | None = None


class MomHeader(ContractModel):
    subject: str = Field(min_length=1, max_length=120)
    meeting_type: MeetingType
    meeting_type_confidence: Literal["high", "medium", "low"]
    date: date
    date_source: Literal["recording", "upload"]
    duration_min: int | None = Field(default=None, ge=0)
    languages: dict[Literal["ro", "ru", "en"], float] | None = None
    participants_mentioned: list[MomParticipant] | None = None
    also_discussed: list[MeetingType] | None = None


class MomDecision(ContractModel):
    id: str = Field(pattern=r"^D\d+$")
    text: str = Field(min_length=1)
    status: Literal["decided", "proposed", "revoked"]
    revised_in_meeting: bool | None = None
    evidence: MomEvidence
    flags: list[MomFlag]


class MomDeadline(ContractModel):
    spoken: str | None = None
    resolved: date | None = None


class MomAction(ContractModel):
    id: str = Field(pattern=r"^A\d+$")
    text: str = Field(min_length=1)
    decision_ids: list[str] | None = None
    owner: str | None = None
    deadline: MomDeadline
    evidence: MomEvidence
    flags: list[MomFlag]


class MomFinding(ContractModel):
    text: str = Field(min_length=1)
    source_stated: str | None = None
    evidence: MomEvidence
    flags: list[MomFlag]


class MomTopic(ContractModel):
    title: str = Field(min_length=1)
    text: str = Field(min_length=1)


class MomRisk(ContractModel):
    text: str = Field(min_length=1)
    category: Literal[
        "clinical", "safety", "technical", "regulatory", "data_quality", "operational"
    ] | None = None
    raised_by: str | None = None
    evidence: MomEvidence | None = None


class MomOpenQuestion(ContractModel):
    text: str = Field(min_length=1)
    raised_by: str | None = None
    evidence: MomEvidence | None = None


class MomPatient(ContractModel):
    reference: str = Field(min_length=1)
    findings: list[str] | None = None
    decision_ids: list[str]
    plan: str | None = None


class MomDocument(ContractModel):
    """The validated schema-version-1 review document consumed by the portal."""

    header: MomHeader
    summary: str = Field(min_length=1)
    decisions: list[MomDecision]
    actions: list[MomAction]
    findings: list[MomFinding]
    topics: list[MomTopic]
    risks: list[MomRisk]
    open_questions: list[MomOpenQuestion]
    patients: list[MomPatient] | None = None


class MomResult(ContractModel):
    schema_version: Literal[1] = Field(alias="schemaVersion")
    quality: MomQuality
    document: MomDocument


class ProcessingSummary(PipelineModel):
    started_at: datetime = Field(alias="startedAt")
    completed_at: datetime = Field(alias="completedAt")
    elapsed_ms: int = Field(alias="elapsedMs", ge=0)


class ReviewSourceRecording(SourceRecording):
    duration_ms: int = Field(alias="durationMs", gt=0)
    recorded_at: datetime | None = Field(default=None, alias="recordedAt")


class MeetingMetadata(PipelineModel):
    duration_ms: int = Field(alias="durationMs", gt=0)
    speaker_count: int = Field(alias="speakerCount", ge=0)
    named_speaker_count: int = Field(alias="namedSpeakerCount", ge=0)
    languages: list[DetectedLanguage]


class ReviewQuality(PipelineModel):
    transcript_confidence: float | None = Field(
        default=None,
        alias="transcriptConfidence",
        ge=0,
        le=1,
    )
    mom_confidence: float | None = Field(
        default=None,
        alias="momConfidence",
        ge=0,
        le=1,
    )
    overall_confidence: float | None = Field(
        alias="overallConfidence",
        ge=0,
        le=1,
    )
    confidence_scale: Literal["ZERO_TO_ONE"] = Field(
        alias="confidenceScale",
    )


class ArtifactLink(PipelineModel):
    available: bool
    href: str


class ReviewArtifactLinks(PipelineModel):
    mom: ArtifactLink
    transcript: ArtifactLink


class ReviewContext(ContractModel):
    """Persisted server-side context, including the notification recipient."""

    schema_version: Literal[1] = Field(alias="schemaVersion")
    job_id: str = Field(alias="jobId", min_length=1)
    status: JobStatus
    stage: str
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    submitted_by: SubmittedBy = Field(alias="submittedBy")
    source_recording: ReviewSourceRecording = Field(alias="sourceRecording")
    processing: ProcessingSummary
    meeting_metadata: MeetingMetadata = Field(alias="meetingMetadata")
    speakers: list[TranscriptionSpeaker]
    quality: ReviewQuality
    artifacts: ReviewArtifactLinks


class ReviewContextResponse(ContractModel):
    """Browser-facing context with the submitter email intentionally omitted."""

    schema_version: Literal[1] = Field(alias="schemaVersion")
    job_id: str = Field(alias="jobId", min_length=1)
    status: JobStatus
    stage: str
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    submitted_by: PublicSubmittedBy = Field(alias="submittedBy")
    source_recording: ReviewSourceRecording = Field(alias="sourceRecording")
    processing: ProcessingSummary
    meeting_metadata: MeetingMetadata = Field(alias="meetingMetadata")
    speakers: list[TranscriptionSpeaker]
    quality: ReviewQuality
    artifacts: ReviewArtifactLinks

    @classmethod
    def from_context(cls, context: ReviewContext) -> ReviewContextResponse:
        return cls(
            schema_version=context.schema_version,
            job_id=context.job_id,
            status=context.status,
            stage=context.stage,
            created_at=context.created_at,
            updated_at=context.updated_at,
            submitted_by=PublicSubmittedBy(
                user_id=context.submitted_by.user_id,
                display_name=context.submitted_by.display_name,
            ),
            source_recording=context.source_recording,
            processing=context.processing,
            meeting_metadata=context.meeting_metadata,
            speakers=context.speakers,
            quality=context.quality,
            artifacts=context.artifacts,
        )


class TextSubmission(PipelineModel):
    model_job_id: str = Field(alias="modelJobId", min_length=1)
    status: Literal["accepted"]


class TranscriptionReceipt(PipelineModel):
    job_id: str = Field(alias="jobId")
    status: JobStatus
    stage: str
    replayed: bool


class MomReceipt(PipelineModel):
    job_id: str = Field(alias="jobId")
    status: JobStatus
    stage: str
    replayed: bool
