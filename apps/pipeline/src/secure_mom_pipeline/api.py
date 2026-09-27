"""FastAPI control surface for persisted local pipeline jobs."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Annotated

import uvicorn
from fastapi import FastAPI, File, Header, Query, Request, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .config import get_settings
from .directory import search_people
from .job_store import InvalidJobStateError, JobNotFoundError, JobStore
from .logging_config import configure_logging
from .mail_adapter import LocalMailAdapter, MailAdapterError, make_local_mail_adapter
from .mom_email import compose_approved_mom_email
from .models import (
    ApprovalRequest,
    ApprovedMom,
    ArtifactLink,
    CreateJobResponse,
    DeliveryResult,
    DirectoryPerson,
    ErrorDetail,
    ErrorEnvelope,
    JobArtifacts,
    JobError,
    JobState,
    JobStatus,
    JobStatusResponse,
    MeetingMetadata,
    MomDocument,
    MomResult,
    MomReceipt,
    ParticipantAssignment,
    ParticipantAssignments,
    ParticipantAssignmentsRequest,
    ProcessingSummary,
    ReviewArtifactLinks,
    ReviewContext,
    ReviewContextResponse,
    ReviewQuality,
    ReviewSourceRecording,
    SourceRecording,
    SubmittedBy,
    TranscriptionSpeaker,
    TranscriptionResult,
    TranscriptionReceipt,
    utc_now,
)


settings = get_settings()
logger = configure_logging(settings.log_file)
job_store = JobStore(settings.storage_root)
mail_adapter: LocalMailAdapter = make_local_mail_adapter(settings)

MAX_UPLOAD_BYTES = 300 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024
LOCAL_EMAIL_PATTERN = re.compile(
    r"[a-z0-9][a-z0-9._%+\-]*@[a-z0-9][a-z0-9.\-]*",
    re.ASCII,
)
MAX_TRANSCRIPTION_BYTES = settings.transcription_max_bytes
MAX_MOM_BYTES = settings.mom_max_bytes
ALLOWED_AUDIO_EXTENSIONS = frozenset(
    {".aac", ".flac", ".m4a", ".mp3", ".mp4", ".ogg", ".opus", ".wav", ".webm"}
)

MOCK_OPENAPI = {
    "x-contract-status": "TODO(discovery): provisional mock response",
}

app = FastAPI(
    title="Secure MOM Pipeline API",
    version="0.5.0-provisional",
    description=(
        "Filesystem-backed upload, transcription receipt, transformation, and "
        "text-service dispatch and persisted draft MoM callback pipeline."
    ),
)


def _error(status_code: int, code: str, message: str, retryable: bool) -> JSONResponse:
    envelope = ErrorEnvelope(
        error=ErrorDetail(code=code, message=message, retryable=retryable)
    )
    return JSONResponse(
        status_code=status_code,
        content=envelope.model_dump(mode="json", by_alias=True),
    )


def _partition_recipients(recipients: list[str]) -> tuple[list[str], list[str]]:
    """Keep permitted local addresses and softly skip everything else."""

    accepted: list[str] = []
    skipped: list[str] = []
    seen: set[str] = set()
    allowed = set(settings.mail_allowed_recipient_domains)
    for original in recipients:
        candidate = original.strip().lower()
        local, separator, domain = candidate.rpartition("@")
        if (
            not separator
            or not local
            or not domain
            or LOCAL_EMAIL_PATTERN.fullmatch(candidate) is None
            or domain not in allowed
        ):
            skipped.append(original)
            continue
        if candidate not in seen:
            accepted.append(candidate)
            seen.add(candidate)
    return accepted, skipped


def _read_participant_assignments(
    directory: Path,
    state_model: JobState,
) -> ParticipantAssignments | None:
    descriptor = state_model.artifacts.participant_assignments
    if descriptor is None:
        return None
    return ParticipantAssignments.model_validate_json(
        job_store.read_artifact_at(directory, descriptor)
    )


def _apply_participant_assignments(
    speakers: list[TranscriptionSpeaker],
    assignments: ParticipantAssignments | None,
) -> list[TranscriptionSpeaker]:
    if assignments is None:
        return speakers
    names = {
        assignment.speaker_id: assignment.display_name
        for assignment in assignments.assignments
    }
    return [
        speaker.model_copy(
            update={"display_name": names.get(speaker.id, speaker.display_name)}
        )
        for speaker in speakers
    ]


def _json_bytes(model: ApprovedMom | DeliveryResult) -> bytes:
    return (
        json.dumps(
            model.model_dump(mode="json", by_alias=True),
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")


@app.get(
    f"{settings.api_prefix}{settings.routes.directory}",
    response_model=list[DirectoryPerson],
    summary="Search the local demo staff directory",
)
def get_directory(
    q: Annotated[str, Query(max_length=160)] = "",
) -> list[DirectoryPerson]:
    return search_people(q)


def _safe_extension(filename: str | None) -> str | None:
    if not filename:
        return None
    extension = Path(filename).suffix.lower()
    return extension if extension in ALLOWED_AUDIO_EXTENSIONS else None


def _log_trigger(operation: str) -> None:
    logger.info("event=endpoint_triggered operation=%s", operation)


def _dummy(operation: str) -> JSONResponse:
    return JSONResponse(
        status_code=200,
        content={
            "mock": True,
            "operation": operation,
            "detail": "TODO(discovery): replace this dummy response",
        },
    )


@app.post(
    f"{settings.api_prefix}{settings.routes.jobs}",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=CreateJobResponse,
    responses={
        400: {"model": ErrorEnvelope},
        413: {"model": ErrorEnvelope},
        415: {"model": ErrorEnvelope},
        500: {"model": ErrorEnvelope},
    },
    summary="Persist an audio upload and queue a pipeline job",
)
async def create_job(
    audio: Annotated[
        UploadFile,
        File(description="Audio recording, up to 300 MiB"),
    ],
) -> CreateJobResponse | JSONResponse:
    extension = _safe_extension(audio.filename)
    if extension is None:
        await audio.close()
        return _error(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "UNSUPPORTED_AUDIO_FORMAT",
            "Use a supported audio file extension.",
            False,
        )

    job_id = job_store.new_job_id()
    started = monotonic()
    staging_directory: Path | None = None
    byte_count = 0
    try:
        staging_directory = job_store.prepare_staging(job_id)
        job_store.append_event_at(
            staging_directory,
            job_id=job_id,
            event_type="upload.started",
            producer="pipeline-api",
            value={"extension": extension},
        )
        logger.info("event=upload_started job_id=%s", job_id)

        relative_audio_path = Path("input") / f"meeting{extension}"
        audio_path = staging_directory / relative_audio_path
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        with audio_path.open("xb") as stream:
            while chunk := await audio.read(UPLOAD_CHUNK_BYTES):
                byte_count += len(chunk)
                if byte_count > MAX_UPLOAD_BYTES:
                    logger.info(
                        "event=upload_rejected job_id=%s reason=size_limit bytes=%d",
                        job_id,
                        byte_count,
                    )
                    return _error(
                        status.HTTP_413_CONTENT_TOO_LARGE,
                        "UPLOAD_TOO_LARGE",
                        "The audio file exceeds the 300 MiB limit.",
                        False,
                    )
                stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())

        if byte_count == 0:
            logger.info("event=upload_rejected job_id=%s reason=empty", job_id)
            return _error(
                status.HTTP_400_BAD_REQUEST,
                "EMPTY_AUDIO_FILE",
                "The audio file is empty.",
                False,
            )

        created_at = utc_now()
        original_file_name = (audio.filename or f"meeting{extension}").replace(
            "\\", "/"
        ).rsplit("/", 1)[-1]
        state_model = JobState(
            job_id=job_id,
            status=JobStatus.QUEUED,
            stage="queued",
            created_at=created_at,
            updated_at=created_at,
            artifacts=JobArtifacts(audio=relative_audio_path.as_posix()),
            submitted_by=SubmittedBy(
                user_id=settings.demo_submitter_user_id,
                display_name=settings.demo_submitter_display_name,
                email=settings.demo_submitter_email,
            ),
            source_recording=SourceRecording(
                original_file_name=original_file_name,
                media_type=audio.content_type or "application/octet-stream",
                size_bytes=byte_count,
            ),
        )
        job_store.append_event_at(
            staging_directory,
            job_id=job_id,
            event_type="upload.persisted",
            producer="pipeline-api",
            value={
                "artifact": relative_audio_path.as_posix(),
                "bytes": byte_count,
                "elapsedMs": round((monotonic() - started) * 1000),
            },
        )
        job_store.write_state_at(staging_directory, state_model)
        job_store.append_event_at(
            staging_directory,
            job_id=job_id,
            event_type="job.queued",
            producer="pipeline-api",
            value={"status": state_model.status, "stage": state_model.stage},
        )
        job_store.publish(staging_directory, job_id)
        staging_directory = None
        logger.info(
            "event=job_queued job_id=%s bytes=%d elapsed_ms=%d",
            job_id,
            byte_count,
            round((monotonic() - started) * 1000),
        )
        return CreateJobResponse(
            job_id=job_id,
            status=state_model.status,
            stage=state_model.stage,
            created_at=state_model.created_at,
        )
    except (OSError, ValueError):
        logger.error("event=job_create_failed job_id=%s", job_id)
        return _error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "JOB_PERSISTENCE_FAILED",
            "The job could not be persisted.",
            True,
        )
    finally:
        await audio.close()
        if staging_directory is not None:
            try:
                job_store.discard_staging(staging_directory)
            except (OSError, ValueError):
                logger.error("event=staging_cleanup_failed job_id=%s", job_id)


@app.get(
    f"{settings.api_prefix}{settings.routes.job}",
    response_model=JobStatusResponse,
    responses={404: {"model": ErrorEnvelope}, 500: {"model": ErrorEnvelope}},
    summary="Read persisted pipeline job status",
)
def get_job(job_id: str) -> JobStatusResponse | JSONResponse:
    try:
        state_model = job_store.read_state(job_id)
    except JobNotFoundError:
        return _error(
            status.HTTP_404_NOT_FOUND,
            "JOB_NOT_FOUND",
            "The requested job does not exist.",
            False,
        )
    except InvalidJobStateError:
        logger.error("event=job_state_invalid job_id=%s", job_id)
        return _error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "JOB_STATE_INVALID",
            "The persisted job state is invalid.",
            False,
        )
    logger.info("event=job_status_read job_id=%s status=%s", job_id, state_model.status)
    return JobStatusResponse.from_state(state_model)


@app.post(
    f"{settings.api_prefix}{settings.routes.transcription_result}",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TranscriptionReceipt,
    responses={
        200: {"model": TranscriptionReceipt},
        400: {"model": ErrorEnvelope},
        404: {"model": ErrorEnvelope},
        409: {"model": ErrorEnvelope},
        413: {"model": ErrorEnvelope},
        415: {"model": ErrorEnvelope},
        500: {"model": ErrorEnvelope},
    },
    summary="Persist a completed transcription from the audio-to-text service",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/TranscriptionResult"}
                }
            },
        }
    },
)
async def receive_transcription(
    job_id: str,
    request: Request,
    audio_model_job_id: Annotated[
        str,
        Header(alias="X-Audio-Model-Job-Id", min_length=1),
    ],
) -> TranscriptionReceipt | JSONResponse:
    media_type = request.headers.get("content-type", "")
    if media_type.split(";", 1)[0].strip().lower() != "application/json":
        return _error(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "UNSUPPORTED_TRANSCRIPTION_MEDIA_TYPE",
            "The transcription result must use application/json.",
            False,
        )

    payload = bytearray()
    async for chunk in request.stream():
        payload.extend(chunk)
        if len(payload) > MAX_TRANSCRIPTION_BYTES:
            return _error(
                status.HTTP_413_CONTENT_TOO_LARGE,
                "TRANSCRIPTION_TOO_LARGE",
                "The transcription exceeds the configured size limit.",
                False,
            )
    if not payload:
        return _error(
            status.HTTP_400_BAD_REQUEST,
            "EMPTY_TRANSCRIPTION",
            "The transcription is empty.",
            False,
        )

    data = bytes(payload)
    try:
        transcription = TranscriptionResult.model_validate_json(data)
    except (ValidationError, ValueError):
        return _error(
            status.HTTP_400_BAD_REQUEST,
            "INVALID_TRANSCRIPTION_JSON",
            "The transcription result does not match schema version 1.",
            False,
        )
    if transcription.job_id != job_id:
        return _error(
            status.HTTP_409_CONFLICT,
            "TRANSCRIPTION_JOB_MISMATCH",
            "The transcription body does not match the requested pipeline job.",
            False,
        )
    try:
        with job_store.locked_job(job_id) as directory:
            state_model = job_store.read_state(job_id)
            if state_model.model_jobs.audio != audio_model_job_id:
                return _error(
                    status.HTTP_409_CONFLICT,
                    "TRANSCRIPTION_CORRELATION_MISMATCH",
                    "The transcription does not match the active audio model job.",
                    True,
                )

            existing = state_model.artifacts.transcription_source
            if existing is not None:
                existing_data = job_store.read_artifact_at(directory, existing)
                if existing_data == data and existing.media_type == "application/json":
                    job_store.append_event_at(
                        directory,
                        job_id=job_id,
                        event_type="transcription.received.replayed",
                        producer="pipeline-api",
                        value={
                            "bytes": existing.byte_count,
                            "sha256": existing.sha256,
                            "mediaType": existing.media_type,
                        },
                    )
                    receipt = TranscriptionReceipt(
                        job_id=job_id,
                        status=state_model.status,
                        stage=state_model.stage,
                        replayed=True,
                    )
                    return JSONResponse(
                        status_code=status.HTTP_200_OK,
                        content=receipt.model_dump(mode="json", by_alias=True),
                    )
                return _error(
                    status.HTTP_409_CONFLICT,
                    "TRANSCRIPTION_CONFLICT",
                    "A different transcription is already persisted for this job.",
                    False,
                )

            if not (
                state_model.status == JobStatus.TRANSCRIBING
                and state_model.stage == "audio_processing"
            ):
                return _error(
                    status.HTTP_409_CONFLICT,
                    "TRANSCRIPTION_NOT_EXPECTED",
                    "The job is not waiting for a transcription.",
                    True,
                )

            descriptor = job_store.write_artifact_at(
                directory,
                relative_path="transcript/source.json",
                data=data,
                media_type="application/json",
            )
            artifacts = state_model.artifacts.model_copy(
                update={
                    "transcript": descriptor.path,
                    "transcription_source": descriptor,
                }
            )
            received_at = utc_now()
            received_state = state_model.model_copy(
                update={
                    "status": JobStatus.TRANSCRIBING,
                    "stage": "transcription_received",
                    "updated_at": received_at,
                    "audio_stage_ms": max(0, round((received_at - state_model.updated_at).total_seconds() * 1000)),
                    "artifacts": artifacts,
                    "error": None,
                }
            )
            job_store.write_state_at(directory, received_state)
            job_store.append_event_at(
                directory,
                job_id=job_id,
                event_type="job.state.changed",
                producer="pipeline-api",
                value={
                    "status": received_state.status,
                    "stage": received_state.stage,
                },
            )
            job_store.append_event_at(
                directory,
                job_id=job_id,
                event_type="transcription.received",
                producer="pipeline-api",
                value={
                    "bytes": descriptor.byte_count,
                    "sha256": descriptor.sha256,
                    "mediaType": descriptor.media_type,
                },
            )
    except JobNotFoundError:
        return _error(
            status.HTTP_404_NOT_FOUND,
            "JOB_NOT_FOUND",
            "The requested job does not exist.",
            False,
        )
    except InvalidJobStateError:
        logger.error("event=transcription_state_invalid job_id=%s", job_id)
        return _error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "JOB_STATE_INVALID",
            "The persisted job state or artifact is invalid.",
            False,
        )
    except (OSError, ValueError):
        logger.error("event=transcription_persistence_failed job_id=%s", job_id)
        return _error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "TRANSCRIPTION_PERSISTENCE_FAILED",
            "The transcription could not be persisted.",
            True,
        )

    logger.info(
        "event=transcription_received job_id=%s bytes=%d",
        job_id,
        len(data),
    )
    return TranscriptionReceipt(
        job_id=job_id,
        status=received_state.status,
        stage=received_state.stage,
        replayed=False,
    )


def _build_review_context(
    *,
    state_model: JobState,
    transcription: TranscriptionResult,
    mom: MomResult,
    completed_at: datetime,
) -> ReviewContext:
    if state_model.submitted_by is None or state_model.source_recording is None:
        raise InvalidJobStateError("The job is missing submission metadata")
    elapsed_ms = max(
        0,
        round((completed_at - state_model.created_at).total_seconds() * 1000),
    )
    return ReviewContext(
        schema_version=1,
        job_id=state_model.job_id,
        status=JobStatus.AWAITING_REVIEW,
        stage="review_ready",
        created_at=state_model.created_at,
        updated_at=completed_at,
        submitted_by=state_model.submitted_by,
        source_recording=ReviewSourceRecording(
            original_file_name=state_model.source_recording.original_file_name,
            media_type=state_model.source_recording.media_type,
            size_bytes=state_model.source_recording.size_bytes,
            duration_ms=transcription.audio_metadata.duration_ms,
            recorded_at=transcription.audio_metadata.recorded_at,
        ),
        processing=ProcessingSummary(
            started_at=state_model.created_at,
            completed_at=completed_at,
            elapsed_ms=elapsed_ms,
            audio_stage_ms=state_model.audio_stage_ms,
            mom_stage_ms=max(0, round((completed_at - state_model.updated_at).total_seconds() * 1000)),
        ),
        meeting_metadata=MeetingMetadata(
            duration_ms=transcription.audio_metadata.duration_ms,
            speaker_count=len(transcription.speakers),
            named_speaker_count=sum(
                speaker.display_name is not None for speaker in transcription.speakers
            ),
            languages=transcription.language_detection.languages,
        ),
        speakers=transcription.speakers,
        quality=ReviewQuality(
            transcript_confidence=(
                transcription.quality.transcript_confidence
            ),
            mom_confidence=mom.quality.mom_confidence,
            overall_confidence=None,
            confidence_scale="ZERO_TO_ONE",
        ),
        artifacts=ReviewArtifactLinks(
            mom=ArtifactLink(
                available=True,
                href=(
                    f"{settings.api_prefix}{settings.routes.mom}"
                ).format(job_id=state_model.job_id),
            ),
            transcript=ArtifactLink(
                available=True,
                href=(
                    f"{settings.api_prefix}{settings.routes.transcript}"
                ).format(job_id=state_model.job_id),
            ),
        ),
    )


def _validate_mom_evidence(
    document: MomDocument,
    transcription: TranscriptionResult,
) -> None:
    """Reject a draft whose supporting statements point outside this transcript.

    A segment ID, unlike a rendered timestamp or list offset, remains stable
    when the portal changes sorting, filtering, or presentation.
    """
    segment_ids = {segment.id for segment in transcription.transcript.segments}
    evidence = [
        *(item.evidence for item in document.decisions),
        *(item.evidence for item in document.actions),
        *(item.evidence for item in document.findings),
        *(item.evidence for item in document.risks if item.evidence is not None),
        *(
            item.evidence
            for item in document.open_questions
            if item.evidence is not None
        ),
    ]
    unknown = sorted({item.segment_id for item in evidence if item.segment_id not in segment_ids})
    if unknown:
        raise ValueError("The draft MoM references an unknown transcript segment")


@app.post(
    f"{settings.api_prefix}{settings.routes.mom_result}",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=MomReceipt,
    responses={
        200: {"model": MomReceipt},
        400: {"model": ErrorEnvelope},
        404: {"model": ErrorEnvelope},
        409: {"model": ErrorEnvelope},
        413: {"model": ErrorEnvelope},
        415: {"model": ErrorEnvelope},
        500: {"model": ErrorEnvelope},
    },
    summary="Persist a completed draft MoM from the text service",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/MomResult"}
                }
            },
        }
    },
)
async def receive_mom(
    job_id: str,
    request: Request,
    text_model_job_id: Annotated[
        str,
        Header(alias="X-Text-Model-Job-Id", min_length=1),
    ],
) -> MomReceipt | JSONResponse:
    media_type = request.headers.get("content-type", "")
    if media_type.split(";", 1)[0].strip().lower() != "application/json":
        return _error(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "UNSUPPORTED_MOM_MEDIA_TYPE",
            "The draft MoM must use application/json.",
            False,
        )

    payload = bytearray()
    async for chunk in request.stream():
        payload.extend(chunk)
        if len(payload) > MAX_MOM_BYTES:
            return _error(
                status.HTTP_413_CONTENT_TOO_LARGE,
                "MOM_TOO_LARGE",
                "The draft MoM exceeds the configured size limit.",
                False,
            )
    if not payload:
        return _error(
            status.HTTP_400_BAD_REQUEST,
            "EMPTY_MOM",
            "The draft MoM is empty.",
            False,
        )

    data = bytes(payload)
    try:
        mom = MomResult.model_validate_json(data)
    except (ValidationError, ValueError):
        return _error(
            status.HTTP_400_BAD_REQUEST,
            "INVALID_MOM_JSON",
            "The draft MoM does not match schema version 1.",
            False,
        )

    try:
        with job_store.locked_job(job_id) as directory:
            state_model = job_store.read_state(job_id)
            if state_model.model_jobs.text != text_model_job_id:
                return _error(
                    status.HTTP_409_CONFLICT,
                    "MOM_CORRELATION_MISMATCH",
                    "The draft MoM does not match the active text model job.",
                    True,
                )

            existing = state_model.artifacts.mom_output
            if existing is not None:
                existing_data = job_store.read_artifact_at(directory, existing)
                if existing_data == data:
                    job_store.append_event_at(
                        directory,
                        job_id=job_id,
                        event_type="mom.received.replayed",
                        producer="pipeline-api",
                        value={
                            "bytes": existing.byte_count,
                            "sha256": existing.sha256,
                            "mediaType": existing.media_type,
                        },
                    )
                    receipt = MomReceipt(
                        job_id=job_id,
                        status=state_model.status,
                        stage=state_model.stage,
                        replayed=True,
                    )
                    return JSONResponse(
                        status_code=status.HTTP_200_OK,
                        content=receipt.model_dump(mode="json", by_alias=True),
                    )
                return _error(
                    status.HTTP_409_CONFLICT,
                    "MOM_CONFLICT",
                    "A different draft MoM is already persisted for this job.",
                    False,
                )

            if not (
                state_model.status == JobStatus.GENERATING_MOM
                and state_model.stage == "text_processing"
            ):
                return _error(
                    status.HTTP_409_CONFLICT,
                    "MOM_NOT_EXPECTED",
                    "The job is not waiting for a draft MoM.",
                    True,
                )

            transcription_descriptor = state_model.artifacts.transcription_source
            if transcription_descriptor is None:
                raise InvalidJobStateError("The transcription artifact is missing")
            transcription = TranscriptionResult.model_validate_json(
                job_store.read_artifact_at(directory, transcription_descriptor)
            )
            try:
                _validate_mom_evidence(mom.document, transcription)
            except ValueError:
                return _error(
                    status.HTTP_400_BAD_REQUEST,
                    "INVALID_MOM_EVIDENCE",
                    "The draft MoM references a transcript segment that is not available.",
                    False,
                )
            completed_at = utc_now()
            review_context = _build_review_context(
                state_model=state_model,
                transcription=transcription,
                mom=mom,
                completed_at=completed_at,
            )
            review_context_data = (
                json.dumps(
                    review_context.model_dump(mode="json", by_alias=True),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8")

            descriptor = job_store.write_artifact_at(
                directory,
                relative_path="mom/draft.json",
                data=data,
                media_type="application/json",
            )
            review_descriptor = job_store.write_artifact_at(
                directory,
                relative_path="review/context.json",
                data=review_context_data,
                media_type="application/json",
            )
            artifacts = state_model.artifacts.model_copy(
                update={
                    "mom": descriptor.path,
                    "mom_output": descriptor,
                    "review_context": review_descriptor,
                }
            )
            review_state = state_model.model_copy(
                update={
                    "status": JobStatus.AWAITING_REVIEW,
                    "stage": "review_ready",
                    "updated_at": completed_at,
                    "mom_stage_ms": review_context.processing.mom_stage_ms,
                    "artifacts": artifacts,
                    "error": None,
                }
            )
            job_store.write_state_at(directory, review_state)
            job_store.append_event_at(
                directory,
                job_id=job_id,
                event_type="job.state.changed",
                producer="pipeline-api",
                value={"status": review_state.status, "stage": review_state.stage},
            )
            job_store.append_event_at(
                directory,
                job_id=job_id,
                event_type="mom.received",
                producer="pipeline-api",
                value={
                    "bytes": descriptor.byte_count,
                    "sha256": descriptor.sha256,
                    "mediaType": descriptor.media_type,
                },
            )
    except JobNotFoundError:
        return _error(
            status.HTTP_404_NOT_FOUND,
            "JOB_NOT_FOUND",
            "The requested job does not exist.",
            False,
        )
    except InvalidJobStateError:
        logger.error("event=mom_state_invalid job_id=%s", job_id)
        return _error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "JOB_STATE_INVALID",
            "The persisted job state or artifact is invalid.",
            False,
        )
    except (OSError, ValueError):
        logger.error("event=mom_persistence_failed job_id=%s", job_id)
        return _error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "MOM_PERSISTENCE_FAILED",
            "The draft MoM could not be persisted.",
            True,
        )

    logger.info("event=mom_received job_id=%s bytes=%d", job_id, len(data))
    return MomReceipt(
        job_id=job_id,
        status=review_state.status,
        stage=review_state.stage,
        replayed=False,
    )


@app.put(
    f"{settings.api_prefix}{settings.routes.participants}",
    response_model=ParticipantAssignments,
    responses={
        400: {"model": ErrorEnvelope},
        404: {"model": ErrorEnvelope},
        409: {"model": ErrorEnvelope},
        500: {"model": ErrorEnvelope},
    },
    summary="Persist reviewer-confirmed names for diarized speakers",
)
def save_participant_assignments(
    job_id: str,
    request: ParticipantAssignmentsRequest,
) -> ParticipantAssignments | JSONResponse:
    try:
        with job_store.locked_job(job_id) as directory:
            state_model = job_store.read_state(job_id)
            if state_model.status != JobStatus.AWAITING_REVIEW:
                return _error(
                    status.HTTP_409_CONFLICT,
                    "NOT_AWAITING_REVIEW",
                    "Participant names can only be edited while the job awaits review.",
                    False,
                )
            transcription_descriptor = state_model.artifacts.transcription_source
            if transcription_descriptor is None:
                return _error(
                    status.HTTP_409_CONFLICT,
                    "ARTIFACT_NOT_READY",
                    "The transcription is not available yet.",
                    True,
                )
            transcription = TranscriptionResult.model_validate_json(
                job_store.read_artifact_at(directory, transcription_descriptor)
            )
            valid_speaker_ids = {speaker.id for speaker in transcription.speakers}
            unknown = [
                assignment.speaker_id
                for assignment in request.assignments
                if assignment.speaker_id not in valid_speaker_ids
            ]
            if unknown:
                return _error(
                    status.HTTP_400_BAD_REQUEST,
                    "UNKNOWN_SPEAKER",
                    "One or more speaker IDs are not present in this transcription.",
                    False,
                )
            saved = ParticipantAssignments(
                schema_version=1,
                job_id=job_id,
                updated_at=utc_now(),
                assignments=[
                    ParticipantAssignment(
                        speaker_id=assignment.speaker_id,
                        display_name=assignment.display_name.strip(),
                    )
                    for assignment in request.assignments
                ],
            )
            data = (
                json.dumps(
                    saved.model_dump(mode="json", by_alias=True),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8")
            descriptor = job_store.write_artifact_at(
                directory,
                relative_path="review/participant-assignments.json",
                data=data,
                media_type="application/json",
            )
            updated_state = state_model.model_copy(
                update={
                    "updated_at": saved.updated_at,
                    "artifacts": state_model.artifacts.model_copy(
                        update={"participant_assignments": descriptor}
                    ),
                }
            )
            job_store.write_state_at(directory, updated_state)
            job_store.append_event_at(
                directory,
                job_id=job_id,
                event_type="participants.updated",
                producer="pipeline-api",
                value={"speakerCount": len(saved.assignments)},
            )
            return saved
    except JobNotFoundError:
        return _error(
            status.HTTP_404_NOT_FOUND,
            "JOB_NOT_FOUND",
            "The requested job does not exist.",
            False,
        )
    except (InvalidJobStateError, ValidationError, ValueError, OSError):
        logger.error("event=participant_assignments_save_failed job_id=%s", job_id)
        return _error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "PARTICIPANT_ASSIGNMENTS_SAVE_FAILED",
            "The participant names could not be saved.",
            True,
        )


@app.get(
    f"{settings.api_prefix}{settings.routes.transcript}",
    response_model=TranscriptionResult,
    responses={
        404: {"model": ErrorEnvelope},
        409: {"model": ErrorEnvelope},
        500: {"model": ErrorEnvelope},
    },
    summary="Read the persisted structured transcription result",
)
def get_transcript(job_id: str) -> TranscriptionResult | JSONResponse:
    try:
        state_model = job_store.read_state(job_id)
        descriptor = state_model.artifacts.transcription_source
        if descriptor is None:
            return _error(
                status.HTTP_409_CONFLICT,
                "ARTIFACT_NOT_READY",
                "The transcription is not available yet.",
                True,
            )
        data = job_store.read_artifact_at(job_store.job_directory(job_id), descriptor)
        transcription = TranscriptionResult.model_validate_json(data)
        assignments = _read_participant_assignments(
            job_store.job_directory(job_id), state_model
        )
    except JobNotFoundError:
        return _error(
            status.HTTP_404_NOT_FOUND,
            "JOB_NOT_FOUND",
            "The requested job does not exist.",
            False,
        )
    except (InvalidJobStateError, ValidationError, ValueError, OSError):
        logger.error("event=transcript_artifact_invalid job_id=%s", job_id)
        return _error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "TRANSCRIPT_ARTIFACT_INVALID",
            "The persisted transcription is invalid.",
            False,
        )
    logger.info("event=transcript_read job_id=%s", job_id)
    if assignments is None:
        # Preserve exact artifact replay until the reviewer adds speaker names.
        return JSONResponse(content=json.loads(data))
    return transcription.model_copy(
        update={
            "speakers": _apply_participant_assignments(
                transcription.speakers, assignments
            )
        }
    )


@app.get(
    f"{settings.api_prefix}{settings.routes.mom}",
    response_model=MomResult,
    responses={
        404: {"model": ErrorEnvelope},
        409: {"model": ErrorEnvelope},
        500: {"model": ErrorEnvelope},
    },
    summary="Read the persisted draft MoM JSON",
)
def get_mom(job_id: str) -> MomResult | JSONResponse:
    try:
        state_model = job_store.read_state(job_id)
        descriptor = state_model.artifacts.mom_output
        if descriptor is None:
            return _error(
                status.HTTP_409_CONFLICT,
                "ARTIFACT_NOT_READY",
                "The draft MoM is not available yet.",
                True,
            )
        directory = job_store.job_directory(job_id)
        data = job_store.read_artifact_at(directory, descriptor)
        document = MomResult.model_validate_json(data)
    except JobNotFoundError:
        return _error(
            status.HTTP_404_NOT_FOUND,
            "JOB_NOT_FOUND",
            "The requested job does not exist.",
            False,
        )
    except (InvalidJobStateError, ValidationError, ValueError, OSError):
        logger.error("event=mom_artifact_invalid job_id=%s", job_id)
        return _error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "MOM_ARTIFACT_INVALID",
            "The persisted draft MoM is invalid.",
            False,
        )
    logger.info("event=mom_read job_id=%s", job_id)
    return JSONResponse(content=json.loads(data))


@app.get(
    f"{settings.api_prefix}{settings.routes.review_context}",
    response_model=ReviewContextResponse,
    responses={
        404: {"model": ErrorEnvelope},
        409: {"model": ErrorEnvelope},
        500: {"model": ErrorEnvelope},
    },
    summary="Read compact metadata for the review-ready portal view",
)
def get_review_context(job_id: str) -> ReviewContextResponse | JSONResponse:
    try:
        state_model = job_store.read_state(job_id)
        descriptor = state_model.artifacts.review_context
        if descriptor is None:
            return _error(
                status.HTTP_409_CONFLICT,
                "ARTIFACT_NOT_READY",
                "The review context is not available yet.",
                True,
            )
        data = job_store.read_artifact_at(job_store.job_directory(job_id), descriptor)
        context = ReviewContext.model_validate_json(data)
        assignments = _read_participant_assignments(
            job_store.job_directory(job_id), state_model
        )
    except JobNotFoundError:
        return _error(
            status.HTTP_404_NOT_FOUND,
            "JOB_NOT_FOUND",
            "The requested job does not exist.",
            False,
        )
    except (InvalidJobStateError, ValidationError, ValueError, OSError):
        logger.error("event=review_context_artifact_invalid job_id=%s", job_id)
        return _error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "REVIEW_CONTEXT_ARTIFACT_INVALID",
            "The persisted review context is invalid.",
            False,
        )
    logger.info("event=review_context_read job_id=%s", job_id)
    if assignments is not None:
        speakers = _apply_participant_assignments(context.speakers, assignments)
        context = context.model_copy(
            update={
                "updated_at": assignments.updated_at,
                "speakers": speakers,
                "meeting_metadata": context.meeting_metadata.model_copy(
                    update={
                        "named_speaker_count": sum(
                            speaker.display_name is not None for speaker in speakers
                        )
                    }
                ),
            }
        )
    return ReviewContextResponse.from_context(context)


@app.post(
    f"{settings.api_prefix}{settings.routes.approve}",
    response_model=ApprovedMom,
    responses={
        404: {"model": ErrorEnvelope},
        409: {"model": ErrorEnvelope},
        502: {"model": ErrorEnvelope},
        500: {"model": ErrorEnvelope},
    },
    summary="Approve a MoM and optionally deliver it through local SMTP",
)
def approve_mom(job_id: str, request: ApprovalRequest) -> ApprovedMom | JSONResponse:
    try:
        with job_store.locked_job(job_id) as directory:
            state_model = job_store.read_state(job_id)
            recipients, skipped_recipients = _partition_recipients(request.recipients)
            submitter = state_model.submitted_by
            if recipients and not (
                submitter
                and submitter.user_id == settings.demo_submitter_user_id
                and submitter.email.lower() == settings.demo_submitter_email.lower()
            ):
                return _error(
                    409,
                    "SENDER_NOT_AUTHORIZED",
                    "The stored submitting-author identity is not authorized for local delivery.",
                    False,
                )
            existing = state_model.artifacts.approved_mom
            if existing is not None:
                approved = ApprovedMom.model_validate_json(
                    job_store.read_artifact_at(directory, existing)
                )
                if (
                    approved.document != request.document
                    or approved.recipients != recipients
                    or approved.skipped_recipients != skipped_recipients
                ):
                    return _error(
                        409,
                        "APPROVAL_CONFLICT",
                        "A different MoM or recipient list is already approved.",
                        False,
                    )
                if state_model.status == JobStatus.COMPLETED:
                    return approved
                if not (
                    state_model.status == JobStatus.FAILED
                    and state_model.stage == "delivery_failed"
                ):
                    return _error(
                        409,
                        "APPROVAL_NOT_RETRYABLE",
                        "The existing approval cannot be retried in its current state.",
                        False,
                    )
            elif state_model.status != JobStatus.AWAITING_REVIEW:
                return _error(
                    409, "NOT_AWAITING_REVIEW", "The job is not ready for approval.", True
                )

            if existing is None:
                transcription_descriptor = state_model.artifacts.transcription_source
                if transcription_descriptor is None:
                    raise InvalidJobStateError("The transcription artifact is missing")
                transcription = TranscriptionResult.model_validate_json(
                    job_store.read_artifact_at(directory, transcription_descriptor)
                )
                _validate_mom_evidence(request.document, transcription)
                approved = ApprovedMom(
                    schema_version=1,
                    job_id=job_id,
                    approved_at=utc_now(),
                    document=request.document,
                    recipients=recipients,
                    skipped_recipients=skipped_recipients,
                )
                descriptor = job_store.write_artifact_at(
                    directory,
                    relative_path="mom/approved.json",
                    data=_json_bytes(approved),
                    media_type="application/json",
                )
                state_model = state_model.model_copy(
                    update={
                        "updated_at": approved.approved_at,
                        "artifacts": state_model.artifacts.model_copy(
                            update={"approved_mom": descriptor}
                        ),
                    }
                )
                job_store.append_event_at(
                    directory,
                    job_id=job_id,
                    event_type="mom.approved",
                    producer="pipeline-api",
                    value={
                        "sha256": descriptor.sha256,
                        "recipientCount": len(recipients),
                        "skippedRecipientCount": len(skipped_recipients),
                    },
                )

            if not approved.recipients:
                completed = state_model.model_copy(
                    update={
                        "status": JobStatus.COMPLETED,
                        "stage": "approved",
                        "updated_at": utc_now(),
                        "error": None,
                    }
                )
                job_store.write_state_at(directory, completed)
                return approved

            sending = state_model.model_copy(
                update={
                    "status": JobStatus.AWAITING_REVIEW,
                    "stage": "delivery_sending",
                    "updated_at": utc_now(),
                    "error": None,
                }
            )
            job_store.write_state_at(directory, sending)
            message_id = f"<secure-mom-{job_id}@medpark.test>"
            attempted_at = utc_now()
            message = compose_approved_mom_email(
                approved,
                sender=submitter.email,
                message_id=message_id,
            )
            try:
                mail_adapter.send(message)
            except MailAdapterError as exc:
                result = DeliveryResult(
                    schema_version=1,
                    job_id=job_id,
                    status="failed",
                    message_id=message_id,
                    attempted_at=attempted_at,
                    recipient_count=len(approved.recipients),
                    error_code="LOCAL_SMTP_FAILED",
                )
                result_descriptor = job_store.write_artifact_at(
                    directory,
                    relative_path="delivery/result.json",
                    data=_json_bytes(result),
                    media_type="application/json",
                )
                failed = sending.model_copy(
                    update={
                        "status": JobStatus.FAILED,
                        "stage": "delivery_failed",
                        "updated_at": utc_now(),
                        "artifacts": sending.artifacts.model_copy(
                            update={"delivery_result": result_descriptor}
                        ),
                        "error": JobError(
                            code="LOCAL_SMTP_FAILED",
                            message="The approved MoM was saved, but local email delivery failed.",
                            retryable=exc.retryable,
                        ),
                    }
                )
                job_store.write_state_at(directory, failed)
                job_store.append_event_at(
                    directory,
                    job_id=job_id,
                    event_type="delivery.failed",
                    producer="pipeline-api",
                    value={
                        "messageId": message_id,
                        "recipientCount": len(approved.recipients),
                        "retryable": exc.retryable,
                    },
                )
                return _error(
                    502,
                    "LOCAL_SMTP_FAILED",
                    "The approved MoM was saved, but local email delivery failed.",
                    exc.retryable,
                )

            result = DeliveryResult(
                schema_version=1,
                job_id=job_id,
                status="accepted",
                message_id=message_id,
                attempted_at=attempted_at,
                recipient_count=len(approved.recipients),
            )
            result_descriptor = job_store.write_artifact_at(
                directory,
                relative_path="delivery/result.json",
                data=_json_bytes(result),
                media_type="application/json",
            )
            completed = sending.model_copy(
                update={
                    "status": JobStatus.COMPLETED,
                    "stage": "delivered",
                    "updated_at": utc_now(),
                    "artifacts": sending.artifacts.model_copy(
                        update={"delivery_result": result_descriptor}
                    ),
                    "error": None,
                }
            )
            job_store.write_state_at(directory, completed)
            job_store.append_event_at(
                directory,
                job_id=job_id,
                event_type="delivery.accepted",
                producer="pipeline-api",
                value={
                    "messageId": message_id,
                    "recipientCount": len(approved.recipients),
                },
            )
            return approved
    except JobNotFoundError:
        return _error(404, "JOB_NOT_FOUND", "The requested job does not exist.", False)
    except (InvalidJobStateError, ValidationError, OSError):
        logger.error("event=mom_approval_failed job_id=%s", job_id)
        return _error(500, "APPROVAL_FAILED", "The approved MoM could not be saved.", True)
    except ValueError:
        return _error(
            409,
            "INVALID_APPROVAL_EVIDENCE",
            "The approved MoM references missing evidence.",
            False,
        )


@app.get(
    f"{settings.api_prefix}{settings.routes.approved_mom}",
    response_model=ApprovedMom,
    responses={
        404: {"model": ErrorEnvelope},
        409: {"model": ErrorEnvelope},
        500: {"model": ErrorEnvelope},
    },
    summary="Read the persisted approved MoM",
)
def get_approved_mom(job_id: str) -> ApprovedMom | JSONResponse:
    try:
        state_model = job_store.read_state(job_id)
        descriptor = state_model.artifacts.approved_mom
        if descriptor is None:
            return _error(
                409, "APPROVAL_NOT_READY", "The MoM has not been approved.", True
            )
        return ApprovedMom.model_validate_json(
            job_store.read_artifact_at(job_store.job_directory(job_id), descriptor)
        )
    except JobNotFoundError:
        return _error(404, "JOB_NOT_FOUND", "The requested job does not exist.", False)
    except (InvalidJobStateError, ValidationError, ValueError, OSError):
        logger.error("event=approved_mom_read_failed job_id=%s", job_id)
        return _error(500, "APPROVED_MOM_INVALID", "The approved MoM could not be read.", False)


@app.post(
    f"{settings.api_prefix}{settings.routes.retry}",
    response_model=None,
    openapi_extra=MOCK_OPENAPI,
    summary="Trigger mock retry",
)
def retry_job(job_id: str) -> JSONResponse:
    del job_id
    _log_trigger("retry_job")
    return _dummy("retry_job")


@app.get(
    settings.routes.health,
    response_model=None,
    openapi_extra=MOCK_OPENAPI,
    summary="Trigger mock liveness read",
)
def health() -> JSONResponse:
    _log_trigger("health")
    return _dummy("health")


@app.get(
    settings.routes.ready,
    response_model=None,
    openapi_extra=MOCK_OPENAPI,
    summary="Trigger mock readiness read",
)
def ready() -> JSONResponse:
    _log_trigger("ready")
    return _dummy("ready")


def run() -> None:
    uvicorn.run(
        "secure_mom_pipeline.api:app",
        host=settings.api_host,
        port=settings.api_port,
    )
