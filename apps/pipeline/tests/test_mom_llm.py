from __future__ import annotations

import dataclasses
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic, sleep
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from secure_mom_llm.api import create_app
from secure_mom_llm.assemble import assemble, meeting_date
from secure_mom_llm.config import get_llm_settings
from secure_mom_llm.draft import Draft, draft_json_schema
from secure_mom_llm.jobs import MomJobs
from secure_mom_llm.llama import Generation, GenerationError
from secure_mom_pipeline import api as pipeline_api
from secure_mom_pipeline.audio_service import MockAudioService
from secure_mom_pipeline.job_store import JobStore
from secure_mom_pipeline.models import JobStatus, MomResult, TranscriptionResult
from secure_mom_pipeline.text_service import HttpTextService
from secure_mom_pipeline.worker import process_one


UPLOADED_AT = datetime(2026, 9, 26, 7, 30, tzinfo=UTC)
SEGMENTS = [
    "Bună ziua, colegi. Revizuim profilaxia antibiotică perioperatorie.",
    "În trimestrul trei avem patru virgulă doi la sută, față de doi virgulă nouă.",
    "Deci, решили — cefazolina două grame, 30–60 minute înainte de incizie.",
    "Poate facem redosing la patru ore? Да, но надо проверить с фармацией.",
    "Datele pentru auditul pe T4 trebuie scoase din sistem, cineva de la statistică.",
    "Instruirea asistentelor o fac eu, до первого октября.",
]


def transcription(job_id: str, *, recorded_at: str | None = None) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "jobId": job_id,
        "transcript": {
            "text": " ".join(SEGMENTS),
            "segments": [
                {
                    "id": f"seg-{number}",
                    "startMs": number * 60_000,
                    "endMs": number * 60_000 + 30_000,
                    "speakerId": "spk-a" if number % 2 else "spk-b",
                    "languages": ["ro", "ru"],
                    "text": text,
                    "confidence": 0.9,
                }
                for number, text in enumerate(SEGMENTS, start=1)
            ],
        },
        "audioMetadata": {"durationMs": 3_120_000, "recordedAt": recorded_at},
        "languageDetection": {
            "languages": [{"code": "ro", "proportion": 0.7}, {"code": "ru", "proportion": 0.3}]
        },
        "speakers": [
            {"id": "spk-a", "displayName": None, "languages": ["ro"], "speakingTimeProportion": 0.5},
            {"id": "spk-b", "displayName": None, "languages": ["ro", "ru"], "speakingTimeProportion": 0.5},
        ],
        "quality": {"transcriptConfidence": 0.9, "confidenceScale": "ZERO_TO_ONE"},
    }


def evidence(segment: int, quote: str, lang: str = "ro") -> dict[str, Any]:
    return {"segment": segment, "quote": quote, "lang": lang}


DRAFT: dict[str, Any] = {
    "subject": "Profilaxia antibiotică perioperatorie",
    "meeting_type": "medical",
    "meeting_type_confidence": "high",
    "also_discussed": ["medical", "operational"],
    "participants": [],
    "topics": [{"title": "Momentul administrării", "text": "Profilaxia se administrează prea târziu."}],
    "findings": [
        {
            "text": "Rata infecțiilor în T3: 4,2%, față de 2,9%.",
            "source_stated": None,
            "evidence": evidence(2, "patru virgulă doi la sută, față de doi virgulă nouă"),
            "flags": [{"type": "number", "reason": "4,2% sau 4,7%?", "blocking": True, "candidates": ["4,2%", "4,7%", " "]}],
        }
    ],
    "decisions": [
        {
            "text": "Cefazolină 2 g cu 30–60 min înainte de incizie.",
            "status": "decided",
            "revised_in_meeting": False,
            # Cited on the wrong segment; the quote is in segment 3.
            "evidence": evidence(1, "решили — cefazolina două grame", "mixed"),
            "flags": [],
        },
        {
            "text": "Redozare la intervențiile de peste 4 ore.",
            "status": "proposed",
            "revised_in_meeting": False,
            "evidence": evidence(4, "Poate facem redosing la patru ore?"),
            "flags": [],
        },
    ],
    "actions": [
        {
            "text": "Extragerea datelor pentru auditul T4.",
            "decisions": [],
            "owner": None,
            "deadline": None,
            "deadline_date": None,
            # Not what segment 5 says, so the segment's own text replaces it.
            "evidence": evidence(5, "statistica va trimite datele mâine"),
            "flags": [],
        },
        {
            "text": "Reverificarea dozei cu farmacia.",
            "decisions": [],
            "owner": "null",
            "deadline": "luni",
            "deadline_date": "2026-09-28",
            "evidence": evidence(4, "надо проверить с фармацией", "ru"),
            "flags": [],
        },
        {
            "text": "Instruirea asistentelor.",
            "decisions": [1, 7],
            "owner": "Participant 2",
            "deadline": "до первого октября",
            "deadline_date": None,
            "evidence": evidence(6, "Instruirea asistentelor o fac eu", "mixed"),
            "flags": [],
        },
    ],
    "risks": [],
    "open_questions": [
        {"text": "Avizul farmaciei pentru redozare.", "raised_by": None, "evidence": None}
    ],
    "summary": "S-a stabilit profilaxia cu cefazolină; redozarea rămâne o propunere.",
}


class FakeModel:
    """Stands in for llama-server: returns a fixed draft or raises."""

    def __init__(self, draft: dict[str, Any] | None = DRAFT) -> None:
        self.draft = draft
        self.state = "stopped"
        self.prompts: list[tuple[str, str, dict[str, Any]]] = []

    def ensure_ready(self) -> None:
        self.state = "ready"

    def stop(self) -> None:
        self.state = "stopped"

    def generate(self, system: str, user: str, schema: dict[str, Any]) -> Generation:
        self.prompts.append((system, user, schema))
        if self.draft is None:
            raise GenerationError("llama-server stream failed in answer")
        return Generation(json.dumps(self.draft, ensure_ascii=False), 1000, 200, 300)


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> JobStore:
    value = JobStore(tmp_path / "pipeline")
    monkeypatch.setattr(pipeline_api, "job_store", value)
    return value


@pytest.fixture
def pipeline(store: JobStore) -> TestClient:
    del store
    with TestClient(pipeline_api.app) as client:
        yield client


def forward_to(client: TestClient) -> httpx.MockTransport:
    """Deliver the service's callbacks to an in-memory app."""

    def handler(request: httpx.Request) -> httpx.Response:
        response = client.request(
            request.method, request.url.path, content=request.content, headers=request.headers
        )
        return httpx.Response(response.status_code, content=response.content)

    return httpx.MockTransport(handler)


def service_client(
    tmp_path: Path, model: FakeModel, callbacks: httpx.BaseTransport
) -> TestClient:
    settings = dataclasses.replace(get_llm_settings(), storage_root=tmp_path / "mom-llm")
    return TestClient(create_app(MomJobs(settings, model, transport=callbacks)))


def submit(client: TestClient, job_id: str, key: str = "key-1", **overrides: Any) -> httpx.Response:
    files = {
        "transcript": ("transcript.txt", " ".join(SEGMENTS).encode(), "text/plain; charset=utf-8"),
        "transcription": ("transcription.json", json.dumps(transcription(job_id)).encode(), "application/json"),
        **overrides,
    }
    return client.post(
        "/jobs",
        files=files,
        data={"uploadedAt": UPLOADED_AT.isoformat()},
        headers={"X-Pipeline-Job-Id": job_id, "Idempotency-Key": key},
    )


def wait_for(condition, seconds: float = 5.0) -> None:
    deadline = monotonic() + seconds
    while not condition():
        assert monotonic() < deadline
        sleep(0.01)


def assembled(draft: dict[str, Any] = DRAFT, **meta: Any) -> MomResult:
    result, _ = assemble(
        Draft.model_validate(draft),
        TranscriptionResult.model_validate(transcription("job", **meta)),
        UPLOADED_AT,
        "ro",
    )
    return result


def test_generated_mom_reaches_review_through_the_real_pipeline(
    tmp_path: Path, pipeline: TestClient, store: JobStore
) -> None:
    callbacks: list[httpx.Request] = []
    forward = forward_to(pipeline)

    def record(request: httpx.Request) -> httpx.Response:
        callbacks.append(request)
        return forward.handle_request(request)

    model = FakeModel()
    with service_client(tmp_path, model, httpx.MockTransport(record)) as service:
        job_id = pipeline.post(
            "/api/v1/jobs", files={"audio": ("meeting.m4a", b"audio", "audio/mp4")}
        ).json()["jobId"]
        logger = logging.getLogger("test.mom-llm")
        text_service = HttpTextService(
            "http://text.local", "/jobs", 1.0, transport=forward_to(service)
        )
        assert process_one(store, MockAudioService(), logger, text_service)
        audio_job = store.read_state(job_id).model_jobs.audio
        assert pipeline.post(
            f"/api/v1/integrations/audio/jobs/{job_id}/transcription",
            content=json.dumps(transcription(job_id)),
            headers={"Content-Type": "application/json", "X-Audio-Model-Job-Id": audio_job},
        ).status_code == 202

        assert process_one(store, MockAudioService(), logger, text_service)
        wait_for(lambda: store.read_state(job_id).status == JobStatus.AWAITING_REVIEW)

        mom = pipeline.get(f"/api/v1/jobs/{job_id}/mom").json()
        assert mom["schemaVersion"] == 1
        assert mom["quality"] == {"momConfidence": None, "confidenceScale": "ZERO_TO_ONE"}
        uploaded = store.read_state(job_id).created_at.astimezone().date()
        assert mom["document"]["header"]["date"] == uploaded.isoformat()
        assert mom["document"]["header"]["date_source"] == "upload"
        assert mom["document"]["decisions"][0]["evidence"]["segment_id"] == "seg-3"
        assert len(callbacks) == 1
        request = callbacks[0]
        assert request.url.path == f"/api/v1/integrations/text/jobs/{job_id}/mom"
        assert request.headers["x-text-model-job-id"] == store.read_state(job_id).model_jobs.text
        assert request.content == (store.job_directory(job_id) / "mom/draft.json").read_bytes()
        # The model saw numbered segments, never raw segment IDs.
        system, user, schema = model.prompts[0]
        assert "[3] Participant 1: Deci, решили" in user
        assert "seg-3" not in user
        assert "Romanian" in system
        assert schema["$defs"]["DraftEvidence"]["properties"]["segment"]["maximum"] == 6


def test_submission_is_validated_and_idempotent(tmp_path: Path) -> None:
    with service_client(tmp_path, FakeModel(), httpx.MockTransport(lambda r: httpx.Response(202))) as service:
        first = submit(service, "job-1")
        again = submit(service, "job-1")
        other_job = submit(service, "job-2")
        mismatched = submit(
            service,
            "job-3",
            key="key-3",
            transcription=("transcription.json", json.dumps(transcription("job-9")).encode(), "application/json"),
        )
        not_text = submit(
            service, "job-4", key="key-4", transcript=("notes.md", b"x", "text/markdown")
        )
        not_utf8 = submit(
            service, "job-5", key="key-5", transcript=("transcript.txt", b"\xff", "text/plain")
        )

    assert first.status_code == 202
    assert first.json()["status"] == "accepted"
    assert again.status_code == 202
    assert again.json() == first.json()
    assert other_job.status_code == 409
    assert other_job.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert mismatched.status_code == 409
    assert not_text.status_code == 400
    assert not_utf8.status_code == 400


def test_generation_failure_fails_the_pipeline_job(
    tmp_path: Path, pipeline: TestClient, store: JobStore
) -> None:
    job_id = pipeline.post(
        "/api/v1/jobs", files={"audio": ("meeting.m4a", b"audio", "audio/mp4")}
    ).json()["jobId"]
    with service_client(tmp_path, FakeModel(draft=None), forward_to(pipeline)) as service:
        text_service = HttpTextService("http://text.local", "/jobs", 1.0, transport=forward_to(service))
        logger = logging.getLogger("test.mom-llm-failure")
        assert process_one(store, MockAudioService(), logger, text_service)
        audio_job = store.read_state(job_id).model_jobs.audio
        pipeline.post(
            f"/api/v1/integrations/audio/jobs/{job_id}/transcription",
            content=json.dumps(transcription(job_id)),
            headers={"Content-Type": "application/json", "X-Audio-Model-Job-Id": audio_job},
        )
        assert process_one(store, MockAudioService(), logger, text_service)
        wait_for(lambda: store.read_state(job_id).status == JobStatus.FAILED)

    error = pipeline.get(f"/api/v1/jobs/{job_id}").json()["error"]
    assert error["code"] == "GENERATION_FAILED"
    assert error["retryable"] is True


def test_stored_result_is_resent_byte_for_byte_after_restart(tmp_path: Path) -> None:
    bodies: list[bytes] = []
    answers = iter([httpx.Response(503), httpx.Response(202)])

    def pipeline_down_then_up(request: httpx.Request) -> httpx.Response:
        bodies.append(request.content)
        return next(answers)

    with service_client(tmp_path, FakeModel(), httpx.MockTransport(pipeline_down_then_up)) as service:
        submit(service, "job-1")
        wait_for(lambda: len(bodies) == 2)

    job_directory = next((tmp_path / "mom-llm" / "jobs").iterdir())
    assert (job_directory / "delivered").exists()
    assert bodies[0] == bodies[1] == (job_directory / "result.json").read_bytes()

    # A restart with an undelivered stored result resends it without generating.
    (job_directory / "delivered").unlink()
    model = FakeModel()

    def replayed(request: httpx.Request) -> httpx.Response:
        bodies.append(request.content)
        return httpx.Response(200)

    with service_client(tmp_path, model, httpx.MockTransport(replayed)):
        wait_for(lambda: (job_directory / "delivered").exists())
    assert bodies[2] == bodies[0]
    assert model.prompts == []


def test_quotes_are_checked_against_the_transcript() -> None:
    document = assembled().document

    decision = document.decisions[0]
    assert decision.evidence.segment_id == "seg-3"
    assert decision.evidence.quote == "решили — cefazolina două grame"
    assert decision.evidence.t == "00:03:00"
    assert decision.evidence.speaker == "Participant 1"
    unsupported = document.actions[0].evidence
    assert unsupported.segment_id == "seg-5"
    assert unsupported.quote == SEGMENTS[4]


def test_missing_owner_and_deadline_stay_missing_and_are_flagged() -> None:
    unassigned, inferred, relative = assembled().document.actions

    assert unassigned.owner is None
    assert unassigned.deadline.spoken is None and unassigned.deadline.resolved is None
    assert [(flag.type, flag.blocking) for flag in unassigned.flags] == [("owner", False)]
    # A "null" string is not an owner.
    assert inferred.owner is None
    # A date the model worked out from "luni" is kept but must be confirmed.
    assert inferred.deadline.resolved.isoformat() == "2026-09-28"
    assert [(f.type, f.candidates) for f in inferred.flags] == [
        ("owner", None),
        ("deadline", ["2026-09-28"]),
    ]
    # A relative deadline keeps its wording and is not converted to a date.
    assert relative.deadline.spoken == "до первого октября"
    assert relative.deadline.resolved is None
    assert [flag.type for flag in relative.flags] == ["deadline"]
    assert relative.decision_ids == ["D1"]


def test_proposals_and_structure_are_preserved() -> None:
    document = assembled().document

    assert [(d.id, d.status) for d in document.decisions] == [("D1", "decided"), ("D2", "proposed")]
    assert [a.id for a in document.actions] == ["A1", "A2", "A3"]
    assert document.findings[0].flags[0].candidates == ["4,2%", "4,7%"]
    assert document.header.also_discussed == ["operational"]
    assert document.header.duration_min == 52
    assert document.header.languages == {"ro": 0.7, "ru": 0.3}
    assert document.open_questions[0].evidence is None


def test_meeting_date_prefers_the_recording() -> None:
    recorded = TranscriptionResult.model_validate(
        transcription("job", recorded_at="2026-09-25T08:00:00Z")
    )
    uploaded = TranscriptionResult.model_validate(transcription("job"))

    assert meeting_date(recorded, UPLOADED_AT)[1] == "recording"
    assert meeting_date(uploaded, UPLOADED_AT) == (UPLOADED_AT.astimezone().date(), "upload")


def test_draft_schema_bounds_segment_numbers() -> None:
    schema = draft_json_schema(42)
    segment = schema["$defs"]["DraftEvidence"]["properties"]["segment"]

    assert (segment["minimum"], segment["maximum"]) == (1, 42)
    assert list(schema["properties"])[-1] == "summary"
