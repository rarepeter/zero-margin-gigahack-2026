"""Stable, content-free portal links for locally reviewable jobs."""

from __future__ import annotations

from ipaddress import ip_address
from urllib.parse import urlencode, urlsplit, urlunsplit


def normalize_portal_base_url(value: str) -> str:
    """Validate and normalize the loopback-only portal URL used by the demo."""

    candidate = value.strip()
    if not candidate:
        raise ValueError("PIPELINE_PORTAL_BASE_URL must not be empty")

    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("PIPELINE_PORTAL_BASE_URL must use http or https")
    if not parsed.hostname:
        raise ValueError("PIPELINE_PORTAL_BASE_URL must include a host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("PIPELINE_PORTAL_BASE_URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("PIPELINE_PORTAL_BASE_URL must not contain a query or fragment")

    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("PIPELINE_PORTAL_BASE_URL contains an invalid port") from exc

    hostname = parsed.hostname.casefold()
    try:
        loopback = ip_address(hostname).is_loopback
    except ValueError:
        loopback = hostname == "localhost"
    if not loopback:
        raise ValueError("PIPELINE_PORTAL_BASE_URL must use a loopback host for the demo")

    path = f"{parsed.path.rstrip('/')}/"
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, path, "", ""))


def build_review_url(portal_base_url: str, job_id: str) -> str:
    """Build a stable review URL containing only an encoded job identifier."""

    normalized_job_id = job_id.strip()
    if not normalized_job_id:
        raise ValueError("job_id must not be empty")
    base = urlsplit(normalize_portal_base_url(portal_base_url))
    return urlunsplit(
        (
            base.scheme,
            base.netloc,
            base.path,
            urlencode({"review": normalized_job_id}),
            "",
        )
    )
