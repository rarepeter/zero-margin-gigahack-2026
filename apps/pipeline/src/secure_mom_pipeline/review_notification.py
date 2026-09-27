"""Safe, deterministic draft-ready notification construction."""

from __future__ import annotations

from datetime import datetime

from .mail_adapter import LocalMailMessage
from .models import NotificationIntent
from .review_url import build_review_url


NOTIFICATION_SUBJECT = "Your Secure MOM draft is ready for review"


def build_notification_intent(
    *,
    job_id: str,
    recipient: str,
    portal_base_url: str,
    created_at: datetime,
) -> NotificationIntent:
    return NotificationIntent(
        schema_version=1,
        job_id=job_id,
        recipient=recipient,
        subject=NOTIFICATION_SUBJECT,
        review_url=build_review_url(portal_base_url, job_id),
        message_id=f"<secure-mom-review-{job_id}@medpark.test>",
        created_at=created_at,
    )


def compose_review_notification(
    intent: NotificationIntent,
    *,
    sender: str,
) -> LocalMailMessage:
    return LocalMailMessage(
        sender=sender,
        recipients=(intent.recipient,),
        subject=intent.subject,
        text_body=(
            "Your Secure MOM draft is ready for review.\n\n"
            f"Job ID: {intent.job_id}\n"
            f"Review locally: {intent.review_url}\n"
        ),
        message_id=intent.message_id,
    )
