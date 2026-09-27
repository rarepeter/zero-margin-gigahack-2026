"""Centralized configuration for the local pipeline processes."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .review_url import normalize_portal_base_url


def _path_from_env(name: str, fallback: str) -> Path:
    return Path(os.getenv(name, fallback)).expanduser()


def _bounded_positive_float_from_env(name: str, fallback: str, maximum: float) -> float:
    value = float(os.getenv(name, fallback))
    if not 0 < value <= maximum:
        raise ValueError(f"{name} must be greater than zero and no greater than {maximum}")
    return value


def _bounded_positive_int_from_env(name: str, fallback: str, maximum: int) -> int:
    value = int(os.getenv(name, fallback))
    if not 0 < value <= maximum:
        raise ValueError(f"{name} must be greater than zero and no greater than {maximum}")
    return value


def _boolean_from_env(name: str, fallback: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return fallback
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value")


def _domains_from_env(name: str, fallback: str) -> tuple[str, ...]:
    domains = tuple(
        part.strip().lower().removeprefix("@")
        for part in os.getenv(name, fallback).split(",")
        if part.strip()
    )
    if not domains:
        raise ValueError(f"{name} must contain at least one domain")
    return domains


def _email_from_env(name: str, fallback: str) -> str:
    value = os.getenv(name, fallback).strip()
    local, separator, domain = value.rpartition("@")
    if (
        not separator
        or not local
        or not domain
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{name} must contain one valid local email address")
    return value


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
    directory: str = os.getenv("PIPELINE_DIRECTORY_ROUTE", "/directory")
    participants: str = os.getenv(
        "PIPELINE_PARTICIPANTS_ROUTE", "/jobs/{job_id}/participants"
    )
    approve: str = os.getenv("PIPELINE_APPROVE_ROUTE", "/jobs/{job_id}/approve")
    approved_mom: str = os.getenv(
        "PIPELINE_APPROVED_MOM_ROUTE", "/jobs/{job_id}/approved-mom"
    )
    deliveries: str = os.getenv(
        "PIPELINE_DELIVERIES_ROUTE", "/jobs/{job_id}/deliveries"
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
    mom_failure: str = os.getenv(
        "PIPELINE_MOM_FAILURE_ROUTE",
        "/integrations/text/jobs/{job_id}/failure",
    )
    transcription_failure: str = os.getenv(
        "PIPELINE_TRANSCRIPTION_FAILURE_ROUTE",
        "/integrations/audio/jobs/{job_id}/failure",
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
    portal_base_url: str = normalize_portal_base_url(
        os.getenv("PIPELINE_PORTAL_BASE_URL", "http://127.0.0.1:3100")
    )

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

    # The demo mail transport is deliberately local and uses Mailpit's SMTP
    # listener. The adapter has no Mailpit HTTP dependency, relay, or cloud
    # API. A bounded socket timeout covers connection and SMTP commands.
    mail_host: str = os.getenv("PIPELINE_MAIL_HOST", "127.0.0.1")
    mail_port: int = int(os.getenv("PIPELINE_MAIL_PORT", "1025"))
    mail_timeout_seconds: float = _bounded_positive_float_from_env(
        "PIPELINE_MAIL_TIMEOUT_SECONDS", "5.0", 60.0
    )
    mail_use_starttls: bool = _boolean_from_env(
        "PIPELINE_MAIL_USE_STARTTLS", False
    )
    mail_allowed_recipient_domains: tuple[str, ...] = _domains_from_env(
        "PIPELINE_MAIL_ALLOWED_RECIPIENT_DOMAINS", "medpark.test"
    )
    notification_sender: str = _email_from_env(
        "PIPELINE_NOTIFICATION_SENDER", "secure-mom@medpark.test"
    )
    notification_max_attempts: int = _bounded_positive_int_from_env(
        "PIPELINE_NOTIFICATION_MAX_ATTEMPTS", "2", 10
    )
    # Unicode TrueType fonts for the emailed MoM PDF. They must cover Romanian
    # diacritics and Cyrillic; the defaults ship with macOS.
    pdf_font_path: Path = _path_from_env(
        "PIPELINE_PDF_FONT_PATH", "/System/Library/Fonts/Supplemental/Arial.ttf"
    )
    pdf_bold_font_path: Path = _path_from_env(
        "PIPELINE_PDF_BOLD_FONT_PATH",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    )

    # Both URLs point at local services in this package: speech-to-text
    # (`uv run asr-service`) and MoM (`uv run mom-llm-service`). Each
    # acknowledges within its timeout and works asynchronously.
    audio_service_url: str = os.getenv(
        "PIPELINE_AUDIO_SERVICE_URL", "http://127.0.0.1:8101"
    )
    audio_service_jobs_route: str = os.getenv(
        "PIPELINE_AUDIO_SERVICE_JOBS_ROUTE", "/jobs"
    )
    audio_service_timeout_seconds: float = float(
        os.getenv("PIPELINE_AUDIO_SERVICE_TIMEOUT_SECONDS", "10.0")
    )
    # Base URL of this API as the speech-to-text service reaches it.
    audio_callback_base_url: str = os.getenv(
        "PIPELINE_AUDIO_CALLBACK_BASE_URL",
        f"http://127.0.0.1:{os.getenv('PIPELINE_API_PORT', '8000')}",
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

    # TODO(discovery, TD-032): tune after observing actual local services.
    worker_interval_seconds: float = float(
        os.getenv("PIPELINE_WORKER_INTERVAL_SECONDS", "1.0")
    )


def get_settings() -> Settings:
    return Settings()
