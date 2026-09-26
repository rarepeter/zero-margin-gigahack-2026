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
    review_context: str = os.getenv(
        "PIPELINE_REVIEW_CONTEXT_ROUTE", "/jobs/{job_id}/review-context"
    )
    approve: str = os.getenv("PIPELINE_APPROVE_ROUTE", "/jobs/{job_id}/approve")
    approved_mom: str = os.getenv(
        "PIPELINE_APPROVED_MOM_ROUTE", "/jobs/{job_id}/approved-mom"
    )
    retry: str = os.getenv("PIPELINE_RETRY_ROUTE", "/jobs/{job_id}/retry")
    transcription_result: str = os.getenv(
        "PIPELINE_TRANSCRIPTION_RESULT_ROUTE",
        "/integrations/audio/jobs/{job_id}/transcription",
    )
    mom_result: str = os.getenv(
        "PIPELINE_MOM_RESULT_ROUTE",
        "/integrations/text/jobs/{job_id}/mom",
    )
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

    # Authentication is outside the MVP. This fixed local identity represents
    # the already-authenticated submitter during the offline demonstration.
    demo_submitter_user_id: str = os.getenv(
        "PIPELINE_DEMO_SUBMITTER_USER_ID", "demo-user"
    )
    demo_submitter_email: str = os.getenv(
        "PIPELINE_DEMO_SUBMITTER_EMAIL", "demo@medpark.test"
    )
    demo_submitter_display_name: str | None = os.getenv(
        "PIPELINE_DEMO_SUBMITTER_DISPLAY_NAME", "Demo User"
    )

    # TODO(discovery, TD-026): replace these placeholders with ML-owner URLs.
    audio_service_url: str = os.getenv(
        "PIPELINE_AUDIO_SERVICE_URL", "http://127.0.0.1:8101"
    )
    text_service_url: str = os.getenv(
        "PIPELINE_TEXT_SERVICE_URL", "http://127.0.0.1:8102"
    )
    text_service_jobs_route: str = os.getenv(
        "PIPELINE_TEXT_SERVICE_JOBS_ROUTE", "/jobs"
    )
    text_service_timeout_seconds: float = float(
        os.getenv("PIPELINE_TEXT_SERVICE_TIMEOUT_SECONDS", "10.0")
    )
    transcription_max_bytes: int = int(
        os.getenv("PIPELINE_TRANSCRIPTION_MAX_BYTES", str(10 * 1024 * 1024))
    )
    mom_max_bytes: int = int(
        os.getenv("PIPELINE_MOM_MAX_BYTES", str(10 * 1024 * 1024))
    )

    # Development mocks route through the real callback handlers in-process by
    # default. Use "http" to exercise actual loopback networking.
    mock_callback_transport: str = os.getenv(
        "PIPELINE_MOCK_CALLBACK_TRANSPORT", "in_process"
    )
    mock_audio_callback_base_url: str = os.getenv(
        "PIPELINE_MOCK_AUDIO_CALLBACK_BASE_URL",
        f"http://127.0.0.1:{os.getenv('PIPELINE_API_PORT', '8000')}",
    )
    mock_audio_callback_delay_seconds: float = float(
        os.getenv("PIPELINE_MOCK_AUDIO_CALLBACK_DELAY_SECONDS", "5.0")
    )
    mock_text_callback_base_url: str = os.getenv(
        "PIPELINE_MOCK_TEXT_CALLBACK_BASE_URL",
        f"http://127.0.0.1:{os.getenv('PIPELINE_API_PORT', '8000')}",
    )
    mock_text_callback_delay_seconds: float = float(
        os.getenv("PIPELINE_MOCK_TEXT_CALLBACK_DELAY_SECONDS", "5.0")
    )

    # TODO(discovery, TD-032): tune after observing actual local services.
    mock_worker_interval_seconds: float = float(
        os.getenv("PIPELINE_MOCK_WORKER_INTERVAL_SECONDS", "1.0")
    )


def get_settings() -> Settings:
    return Settings()
