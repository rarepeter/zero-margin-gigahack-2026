"""Centralized configuration for the local pipeline processes."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _path_from_env(name: str, fallback: str) -> Path:
    return Path(os.getenv(name, fallback)).expanduser()


@dataclass(frozen=True, slots=True)
class ApiRoutes:
    """TODO(discovery, TD-025): replace all provisional public routes."""

    jobs: str = os.getenv("PIPELINE_JOBS_ROUTE", "/jobs")
    job: str = os.getenv("PIPELINE_JOB_ROUTE", "/jobs/{job_id}")
    transcript: str = os.getenv(
        "PIPELINE_TRANSCRIPT_ROUTE", "/jobs/{job_id}/transcript"
    )
    mom: str = os.getenv("PIPELINE_MOM_ROUTE", "/jobs/{job_id}/mom")
    retry: str = os.getenv("PIPELINE_RETRY_ROUTE", "/jobs/{job_id}/retry")
    health: str = os.getenv("PIPELINE_HEALTH_ROUTE", "/health")
    ready: str = os.getenv("PIPELINE_READY_ROUTE", "/ready")


@dataclass(frozen=True, slots=True)
class Settings:
    # TODO(discovery, TD-025): confirm public binding and routing.
    api_host: str = os.getenv("PIPELINE_API_HOST", "127.0.0.1")
    api_port: int = int(os.getenv("PIPELINE_API_PORT", "8000"))
    api_prefix: str = os.getenv("PIPELINE_API_PREFIX", "/api/v1")
    routes: ApiRoutes = field(default_factory=ApiRoutes)

    # TODO(discovery): choose machine-specific locations before the demo.
    storage_root: Path = _path_from_env("PIPELINE_STORAGE_ROOT", "runtime/data")
    log_file: Path = _path_from_env(
        "PIPELINE_LOG_FILE", "runtime/logs/pipeline.log"
    )

    # TODO(discovery, TD-026): replace these placeholders with ML-owner URLs.
    audio_service_url: str = os.getenv(
        "PIPELINE_AUDIO_SERVICE_URL", "http://127.0.0.1:8101"
    )
    text_service_url: str = os.getenv(
        "PIPELINE_TEXT_SERVICE_URL", "http://127.0.0.1:8102"
    )

    # TODO(discovery, TD-032): tune after observing actual local services.
    mock_worker_interval_seconds: float = float(
        os.getenv("PIPELINE_MOCK_WORKER_INTERVAL_SECONDS", "1.0")
    )


def get_settings() -> Settings:
    return Settings()
