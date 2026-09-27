"""The JSON object the model writes, and the grammar schema that enforces it.

The draft holds only what must come from reading the meeting. Segment IDs,
timestamps, speakers, the meeting date, duration, and language shares are
filled in by `assemble.py` from the transcription, so the model cannot invent
them. Field order is generation order: the summary comes last so it is
written after the details it summarizes.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from secure_mom_pipeline.models import (
    DecisionStatus,
    MeetingType,
    MeetingTypeConfidence,
    MomLanguage,
    RiskCategory,
)


Text = Annotated[str, Field(min_length=1)]


class DraftModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DraftEvidence(DraftModel):
    segment: int  # the [n] number of a transcript segment, 1-based
    quote: Text
    lang: MomLanguage


# Each item takes only the flag types that can apply to it: a decision's open
# point is its status, a finding's is a value or term in its text, and an
# action's may also be its owner or deadline.
class DecisionFlag(DraftModel):
    type: Literal["decision_status"]
    reason: Text
    blocking: bool
    candidates: list[DecisionStatus]


class FindingFlag(DraftModel):
    type: Literal["number", "term"]
    reason: Text
    blocking: bool
    candidates: list[str]


class ActionFlag(DraftModel):
    type: Literal["number", "owner", "deadline", "term"]
    reason: Text
    blocking: bool
    candidates: list[str]


DraftFlag = DecisionFlag | FindingFlag | ActionFlag


class DraftParticipant(DraftModel):
    name: Text
    role: str | None


class DraftTopic(DraftModel):
    title: Text
    text: Text


class DraftFinding(DraftModel):
    text: Text
    source_stated: str | None
    evidence: DraftEvidence
    flags: list[FindingFlag]


class DraftDecision(DraftModel):
    text: Text
    status: DecisionStatus
    revised_in_meeting: bool
    evidence: DraftEvidence
    flags: list[DecisionFlag]


class DraftAction(DraftModel):
    text: Text
    decisions: list[int]  # 1-based positions in Draft.decisions
    owner: str | None
    deadline: str | None  # as spoken
    deadline_date: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")] | None
    evidence: DraftEvidence
    flags: list[ActionFlag]


class DraftRisk(DraftModel):
    text: Text
    category: RiskCategory | None
    raised_by: str | None
    evidence: DraftEvidence | None


class DraftOpenQuestion(DraftModel):
    text: Text
    raised_by: str | None
    evidence: DraftEvidence | None


class Draft(DraftModel):
    subject: Text
    meeting_type: MeetingType
    meeting_type_confidence: MeetingTypeConfidence
    also_discussed: list[MeetingType]
    participants: list[DraftParticipant]
    topics: list[DraftTopic]
    findings: list[DraftFinding]
    decisions: list[DraftDecision]
    actions: list[DraftAction]
    risks: list[DraftRisk]
    open_questions: list[DraftOpenQuestion]
    summary: Text


def draft_json_schema(segment_count: int) -> dict[str, Any]:
    """Return the draft schema with evidence limited to existing segments.

    llama.cpp compiles this into a grammar, so the model cannot emit malformed
    JSON, a missing field, or a segment number outside the transcript.
    """
    schema = Draft.model_json_schema()
    schema["$defs"]["DraftEvidence"]["properties"]["segment"].update(
        minimum=1, maximum=segment_count
    )
    return schema
