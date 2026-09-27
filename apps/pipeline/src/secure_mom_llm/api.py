"""HTTP surface of the local MoM service, started with `uv run mom-llm-service`.

The pipeline posts a job and gets an immediate 202; generation runs in the
background and the outcome is pushed to the pipeline's callback routes.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated

import uvicorn
from fastapi import FastAPI, Form, Header, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from secure_mom_pipeline.models import (
    ErrorDetail,
    ErrorEnvelope,
    TextSubmission,
    TranscriptionResult,
)

from .config import LlmSettings, get_llm_settings
from .jobs import IdempotencyConflictError, MomJobs
from .llama import LlamaServer


MAX_INPUT_BYTES = 10 * 1024 * 1024


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    envelope = ErrorEnvelope(
        error=ErrorDetail(code=code, message=message, retryable=False)
    )
    return JSONResponse(
        status_code=status_code,
        content=envelope.model_dump(mode="json", by_alias=True),
    )


def _media_type(upload: UploadFile) -> str:
    return (upload.content_type or "").split(";", 1)[0].strip().lower()


def create_app(jobs: MomJobs) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        jobs.start()
        yield
        jobs.stop()

    app = FastAPI(
        title="Secure MOM local MoM service",
        description="Turns a structured transcription into a draft MoM on this machine.",
        lifespan=lifespan,
    )

    @app.get("/health")
    def health() -> dict[str, object]:
        return {"status": "ok", "model": jobs.model.state, "queuedJobs": jobs.pending()}

    @app.post(
        "/jobs",
        status_code=status.HTTP_202_ACCEPTED,
        response_model=TextSubmission,
        responses={400: {"model": ErrorEnvelope}, 409: {"model": ErrorEnvelope}},
    )
    async def create_job(
        transcript: UploadFile,
        transcription: UploadFile,
        uploaded_at: Annotated[datetime, Form(alias="uploadedAt")],
        pipeline_job_id: Annotated[str, Header(alias="X-Pipeline-Job-Id", min_length=1)],
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    ) -> TextSubmission | JSONResponse:
        # transcript.txt is the pipeline's plain-text rendering; generation reads
        # the structured transcription, whose segment IDs evidence must cite.
        text = await transcript.read(MAX_INPUT_BYTES + 1)
        source = await transcription.read(MAX_INPUT_BYTES + 1)
        if len(text) > MAX_INPUT_BYTES or len(source) > MAX_INPUT_BYTES:
            return _error(400, "INPUT_TOO_LARGE", "The transcript exceeds 10 MiB.")
        if transcript.filename != "transcript.txt" or _media_type(transcript) != "text/plain":
            return _error(400, "INVALID_TRANSCRIPT", "transcript must be transcript.txt as text/plain.")
        try:
            text.decode("utf-8")
        except UnicodeDecodeError:
            return _error(400, "INVALID_TRANSCRIPT", "transcript must be UTF-8.")
        if _media_type(transcription) != "application/json":
            return _error(400, "INVALID_TRANSCRIPTION", "transcription must be application/json.")
        try:
            parsed = TranscriptionResult.model_validate_json(source)
        except ValidationError:
            return _error(
                400, "INVALID_TRANSCRIPTION", "transcription does not match schema version 1."
            )
        if parsed.job_id != pipeline_job_id:
            return _error(
                409, "TRANSCRIPTION_JOB_MISMATCH", "transcription belongs to another pipeline job."
            )

        if uploaded_at.tzinfo is None:
            uploaded_at = uploaded_at.replace(tzinfo=UTC)
        try:
            record = jobs.accept(pipeline_job_id, idempotency_key, uploaded_at, source)
        except IdempotencyConflictError:
            return _error(
                409, "IDEMPOTENCY_CONFLICT", "Idempotency-Key was used for another pipeline job."
            )
        return TextSubmission(model_job_id=record.model_job_id, status="accepted")

    return app


def _configure_logging(settings: LlmSettings) -> None:
    """Log operational events only: counts and timings, never meeting content."""
    logger = logging.getLogger("secure_mom_llm")
    if logger.handlers:
        return
    settings.log_file.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    for handler in (
        logging.FileHandler(settings.log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stderr),
    ):
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def run() -> None:
    settings = get_llm_settings()
    _configure_logging(settings)
    app = create_app(MomJobs(settings, LlamaServer(settings)))
    uvicorn.run(app, host=settings.host, port=settings.port)
