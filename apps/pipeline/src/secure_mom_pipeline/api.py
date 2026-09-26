"""FastAPI surface for the explicitly non-functional pipeline baseline."""

from __future__ import annotations

from typing import Annotated

import uvicorn
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse

from .config import get_settings
from .logging_config import configure_logging


settings = get_settings()
logger = configure_logging(settings.log_file)

MOCK_OPENAPI = {
    "x-contract-status": "TODO(discovery): provisional mock response",
}

app = FastAPI(
    title="Secure MOM Pipeline API",
    version="0.1.0-mock",
    description=(
        "Non-functional baseline. Every operation only records a safe endpoint "
        "event and returns dummy data. TODO(discovery, TD-025): finalize the API."
    ),
)


def _log_trigger(operation: str) -> None:
    # Deliberately exclude request bodies, identifiers, paths, and filenames.
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
    status_code=200,
    response_model=None,
    openapi_extra=MOCK_OPENAPI,
    summary="Trigger mock job creation",
)
async def create_job(
    audio: Annotated[UploadFile, File(description="TODO(discovery, TD-031)")],
) -> JSONResponse:
    _log_trigger("create_job")
    await audio.close()
    return _dummy("create_job")


@app.get(
    f"{settings.api_prefix}{settings.routes.job}",
    response_model=None,
    openapi_extra=MOCK_OPENAPI,
    summary="Trigger mock job status read",
)
def get_job(job_id: str) -> JSONResponse:
    del job_id
    _log_trigger("get_job")
    return _dummy("get_job")


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
    # TODO(discovery): confirm the configured bind values and server policy.
    uvicorn.run(
        "secure_mom_pipeline.api:app",
        host=settings.api_host,
        port=settings.api_port,
    )
