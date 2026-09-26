"""FastAPI control surface for persisted local pipeline jobs."""

from __future__ import annotations

import json
import os
from pathlib import Path
from time import monotonic
from typing import Annotated

import uvicorn
from fastapi import FastAPI, File, Header, Request, UploadFile, status
from fastapi.responses import JSONResponse, PlainTextResponse

from .config import get_settings
from .job_store import InvalidJobStateError, JobNotFoundError, JobStore
from .logging_config import configure_logging
from .models import (
    CreateJobResponse,
    ErrorDetail,
    ErrorEnvelope,
    JobArtifacts,
    JobState,
    JobStatus,
    JobStatusResponse,
    MomReceipt,
    TranscriptionReceipt,
    utc_now,
)


settings = get_settings()
logger = configure_logging(settings.log_file)
job_store = JobStore(settings.storage_root)

MAX_UPLOAD_BYTES = 300 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024
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
    version="0.4.0-provisional",
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
        state_model = JobState(
            job_id=job_id,
            status=JobStatus.QUEUED,
            stage="queued",
            created_at=created_at,
            updated_at=created_at,
            artifacts=JobArtifacts(audio=relative_audio_path.as_posix()),
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
        500: {"model": ErrorEnvelope},
    },
    summary="Persist a completed transcription from the audio-to-text service",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {
                    "schema": {"type": "string", "format": "binary"}
                },
                "text/plain": {"schema": {"type": "string", "format": "binary"}},
                "application/json": {
                    "schema": {"type": "string", "format": "binary"}
                },
                "text/csv": {"schema": {"type": "string", "format": "binary"}},
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
    media_type = request.headers.get("content-type", "application/octet-stream")
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
                if existing_data == data and existing.media_type == media_type:
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
                relative_path="transcript/source.bin",
                data=data,
                media_type=media_type,
            )
            artifacts = state_model.artifacts.model_copy(
                update={"transcription_source": descriptor}
            )
            received_state = state_model.model_copy(
                update={
                    "status": JobStatus.TRANSCRIBING,
                    "stage": "transcription_received",
                    "updated_at": utc_now(),
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
                    "schema": {"type": "object", "additionalProperties": True}
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
        document = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error(
            status.HTTP_400_BAD_REQUEST,
            "INVALID_MOM_JSON",
            "The draft MoM must be a valid UTF-8 JSON object.",
            False,
        )
    if not isinstance(document, dict):
        return _error(
            status.HTTP_400_BAD_REQUEST,
            "INVALID_MOM_JSON",
            "The draft MoM must be a JSON object.",
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

            descriptor = job_store.write_artifact_at(
                directory,
                relative_path="mom/draft.json",
                data=data,
                media_type="application/json",
            )
            artifacts = state_model.artifacts.model_copy(
                update={"mom": descriptor.path, "mom_output": descriptor}
            )
            review_state = state_model.model_copy(
                update={
                    "status": JobStatus.AWAITING_REVIEW,
                    "stage": "review_ready",
                    "updated_at": utc_now(),
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


@app.get(
    f"{settings.api_prefix}{settings.routes.transcript}",
    response_class=PlainTextResponse,
    openapi_extra=MOCK_OPENAPI,
    summary="Trigger mock transcript read",
)
def get_transcript(job_id: str) -> PlainTextResponse:
    del job_id
    _log_trigger("get_transcript")
    return PlainTextResponse("TODO(discovery): dummy transcript response")


@app.get(
    f"{settings.api_prefix}{settings.routes.mom}",
    response_model=None,
    responses={
        404: {"model": ErrorEnvelope},
        409: {"model": ErrorEnvelope},
        500: {"model": ErrorEnvelope},
    },
    summary="Read the persisted draft MoM JSON",
)
def get_mom(job_id: str) -> JSONResponse:
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
        document = json.loads(data.decode("utf-8"))
    except JobNotFoundError:
        return _error(
            status.HTTP_404_NOT_FOUND,
            "JOB_NOT_FOUND",
            "The requested job does not exist.",
            False,
        )
    except (InvalidJobStateError, UnicodeDecodeError, json.JSONDecodeError, OSError):
        logger.error("event=mom_artifact_invalid job_id=%s", job_id)
        return _error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "MOM_ARTIFACT_INVALID",
            "The persisted draft MoM is invalid.",
            False,
        )
    logger.info("event=mom_read job_id=%s", job_id)
    return JSONResponse(content=document)


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
