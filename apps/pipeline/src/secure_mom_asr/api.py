"""HTTP surface of the local speech-to-text service, started with `uv run asr-service`.

The pipeline posts a job and gets an immediate 202; transcription runs in the
background and the outcome is pushed to the URLs named in the request.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import FastAPI, Header, status
from fastapi.responses import JSONResponse

from secure_mom_pipeline.models import (
    AudioJobRequest,
    AudioSubmission,
    ErrorDetail,
    ErrorEnvelope,
)

from .config import AsrSettings, get_asr_settings
from .diarize import Diarizer
from .jobs import AsrJobs, IdempotencyConflictError
from .lexicon import Lexicon
from .whisper import WhisperServer


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    envelope = ErrorEnvelope(error=ErrorDetail(code=code, message=message, retryable=False))
    return JSONResponse(
        status_code=status_code, content=envelope.model_dump(mode="json", by_alias=True)
    )


def create_app(jobs: AsrJobs) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        jobs.start()
        yield
        jobs.stop()

    app = FastAPI(
        title="Secure MOM local speech-to-text service",
        description="Transcribes a meeting recording on this machine with FraPiz and Whisper.",
        lifespan=lifespan,
    )

    @app.get("/health")
    def health() -> dict[str, object]:
        return {"status": "ok", "models": jobs.models(), "queuedJobs": jobs.pending()}

    @app.post(
        "/jobs",
        status_code=status.HTTP_202_ACCEPTED,
        response_model=AudioSubmission,
        responses={400: {"model": ErrorEnvelope}, 409: {"model": ErrorEnvelope}},
    )
    def create_job(
        request: AudioJobRequest,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    ) -> AudioSubmission | JSONResponse:
        audio_path = Path(request.audio_path)
        if not audio_path.is_absolute():
            return _error(400, "INVALID_AUDIO_PATH", "audioPath must be absolute.")
        if not audio_path.is_file() or not os.access(audio_path, os.R_OK):
            return _error(400, "AUDIO_NOT_READABLE", "audioPath is not a readable file.")
        try:
            record = jobs.accept(
                request.pipeline_job_id,
                idempotency_key,
                audio_path,
                request.callback_url,
                request.failure_url,
            )
        except IdempotencyConflictError:
            return _error(
                409, "IDEMPOTENCY_CONFLICT", "Idempotency-Key was used for another pipeline job."
            )
        return AudioSubmission(model_job_id=record.model_job_id, status="accepted")

    return app


def _configure_logging(settings: AsrSettings) -> None:
    """Log operational events only: counts and timings, never meeting content."""
    logger = logging.getLogger("secure_mom_asr")
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
    settings = get_asr_settings()
    _configure_logging(settings)
    log_dir = settings.log_file.parent
    jobs = AsrJobs(
        settings,
        WhisperServer("frapiz", settings.whisper_server_bin, settings.frapiz_model_path,
                      settings.threads, log_dir),
        WhisperServer("large-v3", settings.whisper_server_bin, settings.fallback_model_path,
                      settings.threads, log_dir),
        lexicon=Lexicon.load(settings.lexicon_path) if settings.lexicon_path else None,
        diarizer=(
            Diarizer(settings.diarization_model_path, settings.diarization_device)
            if settings.diarization_model_path else None
        ),
    )
    uvicorn.run(create_app(jobs), host=settings.host, port=settings.port)
