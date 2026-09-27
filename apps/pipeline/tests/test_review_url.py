from __future__ import annotations

import pytest

from secure_mom_pipeline.review_url import build_review_url, normalize_portal_base_url


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("http://127.0.0.1:3100", "http://127.0.0.1:3100/"),
        ("http://localhost:3100/", "http://localhost:3100/"),
        ("https://[::1]:3100/portal", "https://[::1]:3100/portal/"),
    ],
)
def test_normalize_portal_base_url_accepts_demo_loopback_urls(
    source: str, expected: str
) -> None:
    assert normalize_portal_base_url(source) == expected


@pytest.mark.parametrize(
    "source",
    [
        "",
        "ftp://127.0.0.1:3100",
        "http://portal.medpark.test",
        "http://user:secret@127.0.0.1:3100",
        "http://127.0.0.1:3100/?existing=value",
        "http://127.0.0.1:3100/#fragment",
        "http://127.0.0.1:invalid",
    ],
)
def test_normalize_portal_base_url_rejects_unsafe_demo_urls(source: str) -> None:
    with pytest.raises(ValueError):
        normalize_portal_base_url(source)


def test_build_review_url_preserves_base_path_and_encodes_only_job_id() -> None:
    assert build_review_url(
        "http://127.0.0.1:3100/secure-mom", " job /?& "
    ) == "http://127.0.0.1:3100/secure-mom/?review=job+%2F%3F%26"


def test_build_review_url_rejects_empty_job_id() -> None:
    with pytest.raises(ValueError):
        build_review_url("http://127.0.0.1:3100", "   ")
