"""FastAPI control surface for persisted local pipeline jobs."""

from __future__ import annotations

import os
from pathlib import Path
from time import monotonic
from typing import Annotated

import uvicorn
from fastapi import FastAPI, File, UploadFile, status
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
    utc_now,
)


settings = get_settings()
logger = configure_logging(settings.log_file)
job_store = JobStore(settings.storage_root)

MAX_UPLOAD_BYTES = 300 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024
ALLOWED_AUDIO_EXTENSIONS = frozenset(
    {".aac", ".flac", ".m4a", ".mp3", ".mp4", ".ogg", ".opus", ".wav", ".webm"}
)

MOCK_OPENAPI = {
    "x-contract-status": "TODO(discovery): provisional mock response",
}

app = FastAPI(
    title="Secure MOM Pipeline API",
    version="0.2.0-provisional",
    description=(
        "Filesystem-backed upload and mock audio-dispatch slice. Endpoints not "
        "covered by this slice remain explicit mocks."
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
    openapi_extra=MOCK_OPENAPI,
    summary="Trigger mock draft MoM read",
)
def get_mom(job_id: str) -> JSONResponse:
    del job_id
    _log_trigger("get_mom")
    return _dummy("get_mom")


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
