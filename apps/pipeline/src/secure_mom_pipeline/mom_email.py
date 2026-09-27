"""Deterministic email rendering from an already approved MoM."""

from __future__ import annotations

from .mail_adapter import LocalMailMessage
from .models import ApprovedMom


def _section(title: str, values: list[str]) -> list[str]:
    if not values:
        return []
    return [title, *[f"- {value}" for value in values], ""]


def compose_approved_mom_email(
    approved: ApprovedMom,
    *,
    sender: str,
    message_id: str,
) -> LocalMailMessage:
    """Render only facts already present in the approved document."""

    document = approved.document
    header = document.header
    subject = " ".join(header.subject.splitlines()).strip()
    lines = [
        "Approved Minutes of Meeting",
        "",
        f"Subject: {header.subject}",
        f"Date: {header.date.isoformat()}",
        "",
        "Summary",
        document.summary,
        "",
    ]

    participants = [
        f"{participant.name} — {participant.role}"
        if participant.role
        else participant.name
        for participant in (header.participants_mentioned or [])
    ]
    lines.extend(_section("Participants mentioned", participants))
    lines.extend(
        _section(
            "Key topics discussed",
            [f"{topic.title}: {topic.text}" for topic in document.topics],
        )
    )
    lines.extend(
        _section("Evidence and findings reviewed", [item.text for item in document.findings])
    )
    lines.extend(
        _section("Decisions and conclusions", [item.text for item in document.decisions])
    )

    actions: list[str] = []
    for action in document.actions:
        details = [action.text]
        if action.owner:
            details.append(f"owner: {action.owner}")
        deadline = action.deadline.resolved or action.deadline.spoken
        if deadline:
            details.append(f"deadline: {deadline}")
        actions.append("; ".join(str(value) for value in details))
    lines.extend(_section("Actions and follow-ups", actions))
    lines.extend(_section("Risks and concerns", [item.text for item in document.risks]))
    lines.extend(
        _section("Open questions", [item.text for item in document.open_questions])
    )

    return LocalMailMessage(
        sender=sender,
        recipients=tuple(approved.recipients),
        subject=f"Secure MOM — {subject}",
        text_body="\n".join(lines).rstrip() + "\n",
        message_id=message_id,
    )
