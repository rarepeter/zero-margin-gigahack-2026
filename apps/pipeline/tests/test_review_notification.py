from __future__ import annotations

from datetime import UTC, datetime

from secure_mom_pipeline.review_notification import (
    NOTIFICATION_SUBJECT,
    build_notification_intent,
    compose_review_notification,
)


def test_review_notification_is_stable_and_contains_only_safe_context() -> None:
    created_at = datetime(2026, 9, 27, 8, 30, tzinfo=UTC)
    intent = build_notification_intent(
        job_id="01234567-89ab-cdef-8123-456789abcdef",
        recipient="author@medpark.test",
        portal_base_url="http://127.0.0.1:3100",
        created_at=created_at,
    )
    repeated = build_notification_intent(
        job_id=intent.job_id,
        recipient=intent.recipient,
        portal_base_url="http://127.0.0.1:3100/",
        created_at=created_at,
    )
    message = compose_review_notification(
        intent,
        sender="secure-mom@medpark.test",
    )

    assert intent == repeated
    assert intent.subject == NOTIFICATION_SUBJECT
    assert intent.review_url == (
        "http://127.0.0.1:3100/?review=01234567-89ab-cdef-8123-456789abcdef"
    )
    assert intent.message_id == (
        "<secure-mom-review-01234567-89ab-cdef-8123-456789abcdef@medpark.test>"
    )
    assert message.sender == "secure-mom@medpark.test"
    assert message.recipients == ("author@medpark.test",)
    assert message.subject == NOTIFICATION_SUBJECT
    assert intent.job_id in message.text_body
    assert intent.review_url in message.text_body
    assert "transcript" not in message.text_body.lower()
    assert "minutes" not in message.text_body.lower()
