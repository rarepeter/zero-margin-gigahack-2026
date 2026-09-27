"""Turn the model's draft into the pipeline's schema-version-1 MoM result.

Everything that can be derived from the transcription is derived here rather
than generated: segment IDs, timestamps, speakers, the meeting date, duration,
and language shares. Quotes are checked against the transcript; a quote the
transcript does not support is replaced by the cited segment's own text, so
the reviewer never sees invented evidence.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from datetime import date, datetime
from typing import Literal

from secure_mom_pipeline.models import (
    MomAction,
    MomDeadline,
    MomDecision,
    MomDocument,
    MomEvidence,
    MomFinding,
    MomFlag,
    MomHeader,
    MomOpenQuestion,
    MomParticipant,
    MomQuality,
    MomResult,
    MomRisk,
    MomTopic,
    TranscriptionResult,
    TranscriptSegment,
)

from .config import OutputLanguage
from .draft import Draft, DraftEvidence, DraftFlag, DraftParticipant
from .prompt import speaker_labels


SUBJECT_MAX_CHARS = 120
FALLBACK_QUOTE_MAX_CHARS = 200
# Share of a quote's words that must occur in a segment for it to count as
# that segment's wording. Tolerates dropped hesitations and ASR repeats.
QUOTE_SUPPORT = 0.8

# Reviewer notes added when the model left an item's gap unflagged.
MISSING_OWNER: dict[OutputLanguage, str] = {
    "ro": "Responsabilul nu a fost numit în înregistrare.",
    "ru": "Ответственный не назван в записи.",
    "en": "No owner was named in the recording.",
}
RELATIVE_DEADLINE: dict[OutputLanguage, str] = {
    "ro": "Termen relativ: data exactă trebuie confirmată.",
    "ru": "Относительный срок: точную дату нужно подтвердить.",
    "en": "Relative deadline: confirm the exact date.",
}
INFERRED_DATE: dict[OutputLanguage, str] = {
    "ro": "Data a fost dedusă din termenul rostit: confirmați.",
    "ru": "Дата выведена из названного срока: подтвердите.",
    "en": "The date was inferred from the spoken deadline: confirm it.",
}
# What the model sometimes writes instead of JSON null.
PLACEHOLDERS = {"null", "none", "n/a", "-", "—", "–", "?"}


def meeting_date(
    transcription: TranscriptionResult, uploaded_at: datetime
) -> tuple[date, Literal["recording", "upload"]]:
    """Use the recording time when the audio service found one, else the upload."""
    recorded_at = transcription.audio_metadata.recorded_at
    if recorded_at is not None:
        return recorded_at.astimezone().date(), "recording"
    return uploaded_at.astimezone().date(), "upload"


def _words(text: str) -> list[str]:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.findall(r"\w+", stripped)


def _support(quote: list[str], segment: Counter[str]) -> float:
    found = sum(min(count, segment[word]) for word, count in Counter(quote).items())
    return found / len(quote)


def _timestamp(milliseconds: int) -> str:
    seconds = milliseconds // 1000
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0] + "…"


class _Assembler:
    def __init__(self, transcription: TranscriptionResult) -> None:
        self.segments: list[TranscriptSegment] = transcription.transcript.segments
        self.words = [Counter(_words(segment.text)) for segment in self.segments]
        self.speakers = speaker_labels(transcription)
        self.unsupported_quotes = 0

    def _locate(self, quote: list[str], cited: int) -> int | None:
        """Find the segment holding the quote, preferring the cited one."""
        if not quote:
            return None
        nearest = sorted(range(len(self.segments)), key=lambda i: abs(i - cited))
        for i in nearest:
            if _support(quote, self.words[i]) >= QUOTE_SUPPORT:
                return i
        # A quote may run across an ASR segment boundary.
        for i in nearest:
            if i + 1 < len(self.segments):
                pair = self.words[i] + self.words[i + 1]
                if _support(quote, pair) >= QUOTE_SUPPORT:
                    return i
        return None

    def evidence(self, draft: DraftEvidence) -> MomEvidence:
        cited = min(max(draft.segment, 1), len(self.segments)) - 1
        quote = " ".join(draft.quote.split())
        located = self._locate(_words(quote), cited)
        if located is None:
            self.unsupported_quotes += 1
            quote = _clip(self.segments[cited].text, FALLBACK_QUOTE_MAX_CHARS)
        segment = self.segments[cited if located is None else located]
        return MomEvidence(
            quote=quote,
            lang=draft.lang,
            segment_id=segment.id,
            t=_timestamp(segment.start_ms),
            speaker=self.speakers.get(segment.speaker_id, segment.speaker_id)
            if segment.speaker_id
            else None,
        )


def _flags(drafts: Sequence[DraftFlag]) -> list[MomFlag]:
    flags = []
    for draft in drafts:
        candidates = list(dict.fromkeys(c.strip() for c in draft.candidates if c.strip()))
        flags.append(
            MomFlag(
                type=draft.type,
                reason=draft.reason.strip(),
                blocking=draft.blocking,
                candidates=candidates or None,
            )
        )
    return flags


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _optional(value: str | None) -> str | None:
    stripped = value.strip() if value else ""
    return None if stripped.casefold() in PLACEHOLDERS else stripped or None


def _participant(person: DraftParticipant) -> MomParticipant:
    role = _optional(person.role)
    return MomParticipant(name=person.name.strip(), role=role, role_stated=role is not None)


def assemble(
    draft: Draft,
    transcription: TranscriptionResult,
    uploaded_at: datetime,
    language: OutputLanguage,
) -> tuple[MomResult, int]:
    """Return the MoM result and how many quotes had to be replaced."""
    if not transcription.transcript.segments:
        raise ValueError("The transcription has no segments to cite")
    assembler = _Assembler(transcription)
    held_on, date_source = meeting_date(transcription, uploaded_at)

    decisions = [
        MomDecision(
            id=f"D{number}",
            text=item.text.strip(),
            status=item.status,
            revised_in_meeting=item.revised_in_meeting,
            evidence=assembler.evidence(item.evidence),
            flags=_flags(item.flags),
        )
        for number, item in enumerate(draft.decisions, start=1)
    ]

    actions = []
    for number, item in enumerate(draft.actions, start=1):
        owner = _optional(item.owner)
        deadline = MomDeadline(
            spoken=_optional(item.deadline), resolved=_date(item.deadline_date)
        )
        flags = _flags(item.flags)
        flagged = {flag.type for flag in flags}
        if owner is None and "owner" not in flagged:
            flags.append(
                MomFlag(type="owner", reason=MISSING_OWNER[language], blocking=False)
            )
        # The model may date a relative deadline despite the prompt; either
        # way the reviewer confirms the date.
        if deadline.spoken and "deadline" not in flagged:
            if deadline.resolved is None:
                flags.append(
                    MomFlag(
                        type="deadline", reason=RELATIVE_DEADLINE[language], blocking=False
                    )
                )
            else:
                flags.append(
                    MomFlag(
                        type="deadline",
                        reason=INFERRED_DATE[language],
                        blocking=False,
                        candidates=[deadline.resolved.isoformat()],
                    )
                )
        decision_ids = [
            f"D{index}"
            for index in dict.fromkeys(item.decisions)
            if 1 <= index <= len(decisions)
        ]
        actions.append(
            MomAction(
                id=f"A{number}",
                text=item.text.strip(),
                decision_ids=decision_ids or None,
                owner=owner,
                deadline=deadline,
                evidence=assembler.evidence(item.evidence),
                flags=flags,
            )
        )

    findings = [
        MomFinding(
            text=item.text.strip(),
            source_stated=_optional(item.source_stated),
            evidence=assembler.evidence(item.evidence),
            flags=_flags(item.flags),
        )
        for item in draft.findings
    ]
    risks = [
        MomRisk(
            text=item.text.strip(),
            category=item.category,
            raised_by=_optional(item.raised_by),
            evidence=assembler.evidence(item.evidence) if item.evidence else None,
        )
        for item in draft.risks
    ]
    open_questions = [
        MomOpenQuestion(
            text=item.text.strip(),
            raised_by=_optional(item.raised_by),
            evidence=assembler.evidence(item.evidence) if item.evidence else None,
        )
        for item in draft.open_questions
    ]

    languages = {
        detected.code: detected.proportion
        for detected in transcription.language_detection.languages
        if detected.code in ("ro", "ru", "en")
    }
    also_discussed = [
        kind for kind in dict.fromkeys(draft.also_discussed) if kind != draft.meeting_type
    ]
    header = MomHeader(
        subject=_clip(draft.subject, SUBJECT_MAX_CHARS),
        meeting_type=draft.meeting_type,
        meeting_type_confidence=draft.meeting_type_confidence,
        date=held_on,
        date_source=date_source,
        duration_min=round(transcription.audio_metadata.duration_ms / 60_000),
        languages=languages or None,
        participants_mentioned=[_participant(person) for person in draft.participants]
        or None,
        also_discussed=also_discussed or None,
    )
    document = MomDocument(
        header=header,
        summary=draft.summary.strip(),
        decisions=decisions,
        actions=actions,
        findings=findings,
        topics=[
            MomTopic(title=topic.title.strip(), text=topic.text.strip())
            for topic in draft.topics
        ],
        risks=risks,
        open_questions=open_questions,
    )
    result = MomResult(
        schema_version=1,
        # No calibrated confidence exists yet; a number here would be invented.
        quality=MomQuality(mom_confidence=None, confidence_scale="ZERO_TO_ONE"),
        document=document,
    )
    return result, assembler.unsupported_quotes


def serialize(result: MomResult) -> bytes:
    """Encode only the fields that were set, so optional gaps stay absent."""
    return result.model_dump_json(by_alias=True, exclude_unset=True).encode("utf-8")
