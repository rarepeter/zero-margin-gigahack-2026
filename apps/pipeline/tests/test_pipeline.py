from __future__ import annotations

import json
import logging
import os
from copy import deepcopy
from datetime import datetime
from threading import Event
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import monotonic, sleep

import httpx
import pytest
from fastapi.testclient import TestClient

from secure_mom_pipeline import api
from secure_mom_pipeline.audio_service import MockAudioService
from secure_mom_pipeline.callback_transport import make_in_process_callback_sender
from secure_mom_pipeline.event_log import EventLog
from secure_mom_pipeline.intermediate_transformer import (
    IntermediateTransformationError,
    StructuredTranscriptionTransformer,
)
from secure_mom_pipeline.job_store import JobStore
from secure_mom_pipeline.mail_adapter import (
    LocalMailMessage,
    MailAdapterError,
    MailSubmission,
)
from secure_mom_pipeline.models import (
    JobStatus,
    TextSubmission,
    TranscriptionSource,
    utc_now,
)
from secure_mom_pipeline.text_service import (
    HttpTextService,
    TextConnectionError,
    TextProtocolError,
)
from secure_mom_pipeline.worker import process_one


MOM_FIXTURE = {
    # A schema-version-1 document citing segment-2..6 of transcription_document.
    "schemaVersion": 1,
    "quality": {"momConfidence": 0.86, "confidenceScale": "ZERO_TO_ONE"},
    "document": {
        "header": {
            "subject": "Revizuirea profilaxiei antibiotice perioperatorii",
            "meeting_type": "medical",
            "meeting_type_confidence": "high",
            "date": "2026-09-25",
            "date_source": "recording",
            "duration_min": 52,
            "languages": {"ro": 0.71, "ru": 0.21, "en": 0.08},
            "participants_mentioned": [
                {"name": "Participant 1", "role": None, "role_stated": False},
                {"name": "Participant 2", "role": None, "role_stated": False},
                {"name": "Participant 3", "role": None, "role_stated": False},
                {"name": "Participant 4", "role": None, "role_stated": False},
            ],
        },
        "summary": (
            "A fost analizat momentul administrării profilaxiei antibiotice și "
            "datele privind infecțiile postoperatorii. Două decizii, trei acțiuni."
        ),
        "decisions": [
            {
                "id": "D1",
                "text": "Cefazolină 2 g i.v., cu 30–60 min înainte de incizie, devine prima linie în chirurgia generală electivă.",
                "status": "decided",
                "evidence": {"quote": "Deci, решили — cefazolina două grame, 30–60 minute înainte de incizie.", "lang": "mixed", "segment_id": "segment-4", "t": "00:41:12", "speaker": "Participant 1"},
                "flags": [],
            },
            {
                "id": "D2",
                "text": "Momentul administrării se înregistrează în lista de verificare, înainte de time-out.",
                "status": "decided",
                "evidence": {"quote": "OK, agreed — timpul administrării intră în checklist, înainte de time-out.", "lang": "mixed", "segment_id": "segment-5", "t": "00:44:30", "speaker": "Participant 4"},
                "flags": [],
            },
            {
                "id": "D3",
                "text": "Redozare la intervențiile de peste 4 ore, cu avizul farmaciei.",
                "status": "proposed",
                "evidence": {"quote": "Poate facem redosing la patru ore? — Да, но надо проверить с фармацией.", "lang": "mixed", "segment_id": "segment-6", "t": "00:46:05", "speaker": "Participant 2"},
                "flags": [{"type": "decision_status", "reason": "A fost decis sau doar propus?", "blocking": True, "candidates": ["decided", "proposed"]}],
            },
        ],
        "actions": [
            {
                "id": "A1", "text": "Actualizarea protocolului de profilaxie", "decision_ids": ["D1"], "owner": "Participant 3",
                "deadline": {"spoken": "până vineri viitoare", "resolved": "2026-10-02"},
                "evidence": {"quote": "Protocolul actualizat — până vineri viitoare.", "lang": "ro", "segment_id": "segment-4", "t": "00:43:10", "speaker": "Participant 1"},
                "flags": [{"type": "deadline", "reason": "„Până vineri viitoare” a fost calculat ca 02.10.2026. Corect?", "blocking": True, "candidates": ["2026-10-02", "2026-10-09"]}],
            },
            {
                "id": "A2", "text": "Instruirea asistentelor din blocul operator", "decision_ids": ["D1", "D2"], "owner": "Participant 4",
                "deadline": {"spoken": "до первого октября", "resolved": "2026-09-30"},
                "evidence": {"quote": "Instruirea asistentelor o fac eu, до первого октября.", "lang": "mixed", "segment_id": "segment-5", "t": "00:44:52", "speaker": "Participant 4"},
                "flags": [],
            },
            {
                "id": "A3", "text": "Extragerea datelor pentru auditul T4", "owner": None,
                "deadline": {"spoken": None, "resolved": None},
                "evidence": {"quote": "Datele pentru auditul pe T4 trebuie scoase din sistem… cineva de la statistică.", "lang": "ro", "segment_id": "segment-6", "t": "00:47:03", "speaker": "Participant 1"},
                "flags": [{"type": "owner", "reason": "Nimeni nu a fost desemnat. Cine răspunde?", "blocking": True, "candidates": ["Participant 2", "Participant 4"]}],
            },
        ],
        "findings": [
            {
                "text": "Rata infecțiilor de plagă postoperatorie în T3: 4,2%, față de 2,9% în T2.",
                "evidence": {"quote": "Patru virgulă doi la sută, față de doi virgulă nouă.", "lang": "ro", "segment_id": "segment-2", "t": "00:12:40", "speaker": "Participant 1"},
                "flags": [{"type": "number", "reason": "S-a auzit „4,2%” sau „4,7%”?", "blocking": True, "candidates": ["4,2%", "4,7%"]}],
            },
            {
                "text": "Antibioticul este administrat după incizie în 37% din cazuri.",
                "evidence": {"quote": "в тридцати семи процентах случаев antibioticul se face după incizie", "lang": "mixed", "segment_id": "segment-3", "t": "00:14:05", "speaker": "Participant 4"},
                "flags": [],
            },
        ],
        "topics": [{"title": "Momentul administrării", "text": "Profilaxia este administrată prea târziu într-o parte semnificativă a cazurilor."}],
        "risks": [{"text": "Pacienții alergici la beta-lactamine: alternativa nu a fost stabilită.", "category": "clinical", "raised_by": "Participant 2", "evidence": {"quote": "alergia la beta-lactamine trebuie clarificată separat", "lang": "ro", "segment_id": "segment-6", "t": "00:50:18", "speaker": "Participant 2"}}],
        "open_questions": [{"text": "Schema alternativă pentru alergia la beta-lactamine.", "raised_by": "Participant 2"}],
    },
}


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> JobStore:
    value = JobStore(tmp_path / "data")
    monkeypatch.setattr(api, "job_store", value)
    return value


@pytest.fixture
def client(store: JobStore) -> TestClient:
    del store
    with TestClient(api.app) as value:
        yield value


def upload(
    client: TestClient,
    *,
    name: str = "meeting.mp3",
    content: bytes = b"ID3-audio",
    media_type: str = "audio/mpeg",
):
    return client.post(
        "/api/v1/jobs",
        files={"audio": (name, content, media_type)},
    )


def transcription_document(
    job_id: str,
    text: str = "Mock multilingual transcript.",
    *,
    confidence: float | None = 0.91,
) -> bytes:
    return json.dumps(
        {
            "schemaVersion": 1,
            "jobId": job_id,
            "transcript": {
                "text": text,
                "segments": [
                    {
                        "id": f"segment-{index}",
                        "startMs": (index - 1) * 3000,
                        "endMs": index * 3000,
                        "speakerId": "speaker-1",
                        "languages": ["ro", "ru", "en"],
                        "text": text,
                        "confidence": confidence,
                    }
                    for index in range(1, 7)
                ],
            },
            "audioMetadata": {"durationMs": 3000},
            "languageDetection": {
                "languages": [
                    {"code": "ro", "proportion": 0.6},
                    {"code": "ru", "proportion": 0.3},
                    {"code": "en", "proportion": 0.1},
                ]
            },
            "speakers": [
                {
                    "id": "speaker-1",
                    "displayName": None,
                    "languages": ["ro", "ru", "en"],
                    "speakingTimeProportion": 1.0,
                }
            ],
            "quality": {
                "transcriptConfidence": confidence,
                "confidenceScale": "ZERO_TO_ONE",
            },
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def mom_document(
    content: str = "Mock Minutes", confidence: float | None = 0.86
) -> bytes:
    payload = deepcopy(MOM_FIXTURE)
    payload["quality"]["momConfidence"] = confidence
    payload["document"]["summary"] = content
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def dispatch_audio(store: JobStore, job_id: str) -> str:
    assert process_one(
        store,
        MockAudioService(),
        logging.getLogger("test.dispatch-audio"),
        RecordingTextService(),
    )
    model_job_id = store.read_state(job_id).model_jobs.audio
    assert model_job_id is not None
    return model_job_id


def push_transcription(
    client: TestClient,
    job_id: str,
    audio_model_job_id: str,
    content: bytes,
    media_type: str = "application/json",
):
    return client.post(
        f"/api/v1/integrations/audio/jobs/{job_id}/transcription",
        content=content,
        headers={
            "Content-Type": media_type,
            "X-Audio-Model-Job-Id": audio_model_job_id,
        },
    )


def push_mom(
    client: TestClient,
    job_id: str,
    text_model_job_id: str,
    content: bytes,
    media_type: str = "application/json",
):
    return client.post(
        f"/api/v1/integrations/text/jobs/{job_id}/mom",
        content=content,
        headers={
            "Content-Type": media_type,
            "X-Text-Model-Job-Id": text_model_job_id,
        },
    )


class RecordingTextService:
    def __init__(self) -> None:
        self.submissions: list[tuple[str, str, bytes]] = []
        self.transcriptions: list[tuple[bytes, datetime]] = []

    def submit(
        self,
        pipeline_job_id: str,
        text_path: Path,
        idempotency_key: str,
        *,
        transcription_path: Path,
        uploaded_at: datetime,
    ) -> TextSubmission:
        self.submissions.append(
            (pipeline_job_id, idempotency_key, text_path.read_bytes())
        )
        self.transcriptions.append((transcription_path.read_bytes(), uploaded_at))
        return TextSubmission(model_job_id="text-job-1", status="accepted")


class RecordingMailAdapter:
    def __init__(
        self,
        *,
        fail: bool = False,
        acceptance_unknown: bool = False,
    ) -> None:
        self.fail = fail
        self.acceptance_unknown = acceptance_unknown
        self.messages: list[LocalMailMessage] = []

    def send(self, message: LocalMailMessage) -> MailSubmission:
        self.messages.append(message)
        if self.fail:
            raise MailAdapterError(
                "simulated local SMTP failure",
                retryable=not self.acceptance_unknown,
                acceptance_unknown=self.acceptance_unknown,
            )
        return MailSubmission(
            message_id=message.message_id,
            recipient_count=len(message.recipients),
        )


def push_mom_failure(client: TestClient, job_id: str, text_model_job_id: str, body: dict):
    return client.post(
        f"/api/v1/integrations/text/jobs/{job_id}/failure",
        json=body,
        headers={"X-Text-Model-Job-Id": text_model_job_id},
    )


class CrashingMailAdapter:
    def send(self, message: LocalMailMessage) -> MailSubmission:
        del message
        raise KeyboardInterrupt("simulated stop during SMTP submission")


class BlockingMailAdapter(RecordingMailAdapter):
    def __init__(self, started: Event, release: Event) -> None:
        super().__init__()
        self.started = started
        self.release = release

    def send(self, message: LocalMailMessage) -> MailSubmission:
        self.messages.append(message)
        self.started.set()
        assert self.release.wait(timeout=2)
        return MailSubmission(
            message_id=message.message_id,
            recipient_count=len(message.recipients),
        )


def create_review_ready_job(
    client: TestClient,
    store: JobStore,
    *,
    transcript_text: str = "meeting transcript",
    mom_text: str = "Mock Minutes",
) -> tuple[str, bytes]:
    job_id = upload(client).json()["jobId"]
    audio_model_job_id = dispatch_audio(store, job_id)
    assert push_transcription(
        client,
        job_id,
        audio_model_job_id,
        transcription_document(job_id, transcript_text),
    ).status_code == 202
    assert process_one(
        store,
        MockAudioService(),
        logging.getLogger("test.review-ready"),
        RecordingTextService(),
    )
    payload = mom_document(mom_text)
    assert push_mom(client, job_id, "text-job-1", payload).status_code == 202
    return job_id, payload


def test_upload_persists_bytes_state_and_ordered_events(
    client: TestClient, store: JobStore, tmp_path: Path
) -> None:
    original = b"ID3\x00\x01confidential bytes"

    response = upload(client, name="../../unsafe.MP3", content=original)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "QUEUED"
    assert body["stage"] == "queued"
    job_id = body["jobId"]
    directory = store.job_directory(job_id)
    assert (directory / "input/meeting.mp3").read_bytes() == original
    assert not (tmp_path / "unsafe.MP3").exists()
    assert store.read_state(job_id).artifacts.audio == "input/meeting.mp3"
    assert store.read_state(job_id).submitted_by is not None
    assert store.read_state(job_id).submitted_by.user_id == "demo-user"

    events = store.read_events(job_id)
    assert [event.offset for event in events] == [0, 1, 2]
    assert [event.event_type for event in events] == [
        "upload.started",
        "upload.persisted",
        "job.queued",
    ]
    serialized = (directory / "operations.ndjson").read_text(encoding="utf-8")
    assert "unsafe" not in serialized
    assert str(directory) not in serialized


def test_upload_openapi_has_no_authentication_parameters() -> None:
    operation = api.app.openapi()["paths"]["/api/v1/jobs"]["post"]
    assert "parameters" not in operation
    request_schema = operation["requestBody"]["content"]["multipart/form-data"]
    assert "$ref" in request_schema["schema"]


@pytest.mark.parametrize(
    "extension",
    ["aac", "flac", "m4a", "mp3", "mp4", "ogg", "opus", "wav", "webm"],
)
def test_popular_audio_extensions_are_accepted(
    client: TestClient, extension: str
) -> None:
    response = upload(client, name=f"audio.{extension}", content=b"audio")
    assert response.status_code == 202


def test_upload_rejections_leave_no_published_or_staged_job(
    client: TestClient, store: JobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    unsupported = upload(client, name="notes.txt", content=b"not audio")
    assert unsupported.status_code == 415
    assert unsupported.json()["error"]["code"] == "UNSUPPORTED_AUDIO_FORMAT"

    empty = upload(client, content=b"")
    assert empty.status_code == 400
    assert empty.json()["error"]["code"] == "EMPTY_AUDIO_FILE"

    monkeypatch.setattr(api, "MAX_UPLOAD_BYTES", 3)
    too_large = upload(client, content=b"four")
    assert too_large.status_code == 413
    assert too_large.json()["error"]["code"] == "UPLOAD_TOO_LARGE"

    assert store.states() == []
    assert not store.staging_root.exists() or list(store.staging_root.iterdir()) == []


def test_upload_limit_is_300_mib() -> None:
    assert api.MAX_UPLOAD_BYTES == 300 * 1024 * 1024


def test_status_endpoint_reads_persisted_state(
    client: TestClient,
) -> None:
    created = upload(client).json()

    response = client.get(f"/api/v1/jobs/{created['jobId']}")

    assert response.status_code == 200
    assert response.json() == {
        "jobId": created["jobId"],
        "status": "QUEUED",
        "stage": "queued",
        "createdAt": created["createdAt"],
        "updatedAt": created["createdAt"],
        "artifacts": {
            "transcriptAvailable": False,
            "momAvailable": False,
            "reviewContextAvailable": False,
        },
        "error": None,
    }

    missing = client.get("/api/v1/jobs/not-a-job-id")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "JOB_NOT_FOUND"


def test_failed_atomic_state_replace_preserves_previous_checkpoint(
    client: TestClient,
    store: JobStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = upload(client).json()["jobId"]
    original = store.read_state(job_id)
    replacement = original.model_copy(
        update={"stage": "replacement", "updated_at": utc_now()}
    )

    def fail_replace(source: Path, destination: Path) -> None:
        del source, destination
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated replace failure"):
        store.write_state(replacement)

    assert store.read_state(job_id) == original
    assert not list(store.job_directory(job_id).glob(".state-*.tmp"))


def test_worker_dispatches_to_mock_service_and_persists_checkpoint(
    client: TestClient, store: JobStore
) -> None:
    job_id = upload(client, content=b"audio-one").json()["jobId"]
    logger = logging.getLogger("test.worker.success")

    assert process_one(store, MockAudioService(), logger, RecordingTextService()) is True

    state = store.read_state(job_id)
    assert state.status == JobStatus.TRANSCRIBING
    assert state.stage == "audio_processing"
    assert state.attempts.transcription == 1
    assert state.model_jobs.audio is not None
    assert state.model_jobs.audio.startswith("mock-audio-")
    assert [event.event_type for event in store.read_events(job_id)] == [
        "upload.started",
        "upload.persisted",
        "job.queued",
        "worker.job.claimed",
        "audio.dispatch.started",
        "job.state.changed",
        "audio.dispatch.accepted",
    ]


def test_waiting_transcription_does_not_block_second_job(
    client: TestClient, store: JobStore
) -> None:
    first = upload(client, content=b"first").json()["jobId"]
    second = upload(client, content=b"second").json()["jobId"]
    logger = logging.getLogger("test.worker.single")

    assert process_one(store, MockAudioService(), logger, RecordingTextService()) is True
    assert process_one(store, MockAudioService(), logger, RecordingTextService()) is True

    assert store.read_state(first).status == JobStatus.TRANSCRIBING
    assert store.read_state(second).status == JobStatus.TRANSCRIBING


def test_worker_records_safe_failure_when_audio_is_missing(
    client: TestClient, store: JobStore
) -> None:
    job_id = upload(client).json()["jobId"]
    state = store.read_state(job_id)
    (store.job_directory(job_id) / state.artifacts.audio).unlink()

    assert process_one(
        store,
        MockAudioService(),
        logging.getLogger("test.worker.failure"),
        RecordingTextService(),
    )

    failed = store.read_state(job_id)
    assert failed.status == JobStatus.FAILED
    assert failed.error is not None
    assert failed.error.code == "AUDIO_DISPATCH_FAILED"
    failure_event = store.read_events(job_id)[-1]
    assert failure_event.event_type == "audio.dispatch.failed"
    assert "path" not in failure_event.value


def test_event_log_appends_concurrently_and_reads_from_offset(tmp_path: Path) -> None:
    event_log = EventLog(tmp_path / "operations.ndjson")

    def append(index: int) -> None:
        event_log.append(
            key="job",
            event_type="test.recorded",
            producer="pytest",
            value={"index": index},
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(append, range(12)))

    records = event_log.read()
    assert [record.offset for record in records] == list(range(12))
    assert [record.offset for record in event_log.read(from_offset=9)] == [9, 10, 11]


def test_structured_transcription_is_preserved_and_text_is_dispatched(
    client: TestClient,
    store: JobStore,
) -> None:
    job_id = upload(client).json()["jobId"]
    audio_model_job_id = dispatch_audio(store, job_id)
    transcript_text = "Bună ziua. Hello. Здравствуйте."
    source = transcription_document(job_id, transcript_text)

    received = push_transcription(
        client,
        job_id,
        audio_model_job_id,
        source,
    )

    assert received.status_code == 202
    assert received.json() == {
        "jobId": job_id,
        "status": "TRANSCRIBING",
        "stage": "transcription_received",
        "replayed": False,
    }
    source_path = store.job_directory(job_id) / "transcript/source.json"
    assert source_path.read_bytes() == source

    text_service = RecordingTextService()
    assert process_one(
        store,
        MockAudioService(),
        logging.getLogger("test.transcription-flow"),
        text_service,
    )

    state = store.read_state(job_id)
    assert state.status == JobStatus.GENERATING_MOM
    assert state.stage == "text_processing"
    assert state.model_jobs.text == "text-job-1"
    assert state.attempts.mom_generation == 1
    assert state.artifacts.transcript == "transcript/source.json"
    assert state.artifacts.text_input is not None
    assert state.artifacts.text_input.media_type == "text/plain; charset=utf-8"
    transcript_path = store.job_directory(job_id) / state.artifacts.text_input.path
    assert transcript_path.read_text(encoding="utf-8") == transcript_text
    assert text_service.submissions == [
        (job_id, f"{job_id}:mom-generation:1", transcript_text.encode("utf-8"))
    ]
    assert text_service.transcriptions == [(source, state.created_at)]
    assert client.get(f"/api/v1/jobs/{job_id}").json()["artifacts"] == {
        "transcriptAvailable": True,
        "momAvailable": False,
        "reviewContextAvailable": False,
    }
    assert client.get(f"/api/v1/jobs/{job_id}/transcript").json() == json.loads(
        source
    )


def test_transcription_push_is_idempotent_and_rejects_conflicts(
    client: TestClient,
    store: JobStore,
) -> None:
    job_id = upload(client).json()["jobId"]
    audio_model_job_id = dispatch_audio(store, job_id)

    first_payload = transcription_document(job_id, "hello")
    conflicting_payload = transcription_document(job_id, "different")
    wrong_model = push_transcription(client, job_id, "wrong", first_payload)
    assert wrong_model.status_code == 409
    assert wrong_model.json()["error"]["code"] == "TRANSCRIPTION_CORRELATION_MISMATCH"

    first = push_transcription(client, job_id, audio_model_job_id, first_payload)
    replay = push_transcription(client, job_id, audio_model_job_id, first_payload)
    conflict = push_transcription(
        client,
        job_id,
        audio_model_job_id,
        conflicting_payload,
    )

    assert first.status_code == 202
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "TRANSCRIPTION_CONFLICT"
    assert (
        store.job_directory(job_id) / "transcript/source.json"
    ).read_bytes() == first_payload


def test_transcription_push_rejects_empty_and_oversized_documents(
    client: TestClient,
    store: JobStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = upload(client).json()["jobId"]
    audio_model_job_id = dispatch_audio(store, job_id)

    empty = push_transcription(client, job_id, audio_model_job_id, b"")
    assert empty.status_code == 400
    assert empty.json()["error"]["code"] == "EMPTY_TRANSCRIPTION"

    monkeypatch.setattr(api, "MAX_TRANSCRIPTION_BYTES", 3)
    oversized = push_transcription(
        client,
        job_id,
        audio_model_job_id,
        transcription_document(job_id),
    )
    assert oversized.status_code == 413
    assert oversized.json()["error"]["code"] == "TRANSCRIPTION_TOO_LARGE"
    assert store.read_state(job_id).stage == "audio_processing"


def test_transcription_push_rejects_invalid_contract_and_media_type(
    client: TestClient,
    store: JobStore,
) -> None:
    job_id = upload(client).json()["jobId"]
    audio_model_job_id = dispatch_audio(store, job_id)
    invalid = push_transcription(
        client,
        job_id,
        audio_model_job_id,
        b"\xff\xfe",
    )
    wrong_media = push_transcription(
        client,
        job_id,
        audio_model_job_id,
        transcription_document(job_id),
        "text/plain",
    )
    mismatched_job = push_transcription(
        client,
        job_id,
        audio_model_job_id,
        transcription_document("00000000-0000-0000-0000-000000000000"),
    )

    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "INVALID_TRANSCRIPTION_JSON"
    assert wrong_media.status_code == 415
    assert wrong_media.json()["error"]["code"] == (
        "UNSUPPORTED_TRANSCRIPTION_MEDIA_TYPE"
    )
    assert mismatched_job.status_code == 409
    assert mismatched_job.json()["error"]["code"] == "TRANSCRIPTION_JOB_MISMATCH"
    assert store.read_state(job_id).stage == "audio_processing"


def test_structured_transformer_extracts_complete_transcript_text() -> None:
    source = transcription_document("pipeline-job", "Bună ziua")
    result = StructuredTranscriptionTransformer().transform(
        TranscriptionSource(
            data=source,
            media_type="application/json",
        )
    )
    assert result.text == "Bună ziua"

    with pytest.raises(IntermediateTransformationError):
        StructuredTranscriptionTransformer().transform(
            TranscriptionSource(data=b"\xff", media_type="application/octet-stream")
        )


def test_text_dispatch_retries_one_transient_connection_failure(
    client: TestClient,
    store: JobStore,
) -> None:
    class FlakyTextService(RecordingTextService):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def submit(
            self,
            pipeline_job_id: str,
            text_path: Path,
            idempotency_key: str,
            **inputs,
        ) -> TextSubmission:
            self.calls += 1
            if self.calls == 1:
                raise TextConnectionError("temporary")
            return super().submit(pipeline_job_id, text_path, idempotency_key, **inputs)

    job_id = upload(client).json()["jobId"]
    audio_model_job_id = dispatch_audio(store, job_id)
    assert push_transcription(
        client,
        job_id,
        audio_model_job_id,
        transcription_document(job_id, "transcript"),
    ).status_code == 202
    service = FlakyTextService()

    assert process_one(
        store,
        MockAudioService(),
        logging.getLogger("test.retry"),
        service,
    )

    assert service.calls == 2
    assert store.read_state(job_id).status == JobStatus.GENERATING_MOM
    assert "text.dispatch.retried" in [
        event.event_type for event in store.read_events(job_id)
    ]


def test_worker_resumes_from_persisted_text_input_checkpoint(
    client: TestClient,
    store: JobStore,
) -> None:
    class SimulatedStopTextService:
        def submit(self, *args, **kwargs) -> TextSubmission:
            del args, kwargs
            raise KeyboardInterrupt("simulated process stop")

    job_id = upload(client).json()["jobId"]
    audio_model_job_id = dispatch_audio(store, job_id)
    assert push_transcription(
        client,
        job_id,
        audio_model_job_id,
        transcription_document(job_id, "checkpoint"),
    ).status_code == 202

    with pytest.raises(KeyboardInterrupt, match="simulated process stop"):
        process_one(
            store,
            MockAudioService(),
            logging.getLogger("test.stop"),
            SimulatedStopTextService(),
        )
    assert store.read_state(job_id).stage == "text_input_ready"

    service = RecordingTextService()
    assert process_one(
        store,
        MockAudioService(),
        logging.getLogger("test.resume"),
        service,
    )
    assert store.read_state(job_id).status == JobStatus.GENERATING_MOM
    assert service.submissions[0][2] == b"checkpoint"


def test_http_text_service_uploads_transcript_and_transcription(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = request.headers
        captured["body"] = request.content
        return httpx.Response(
            202,
            json={"modelJobId": "text-http-1", "status": "accepted"},
        )

    text_path = tmp_path / "transcript.txt"
    text_path.write_text("Bună", encoding="utf-8")
    transcription_path = tmp_path / "source.json"
    transcription_path.write_bytes(b'{"schemaVersion":1}')
    service = HttpTextService(
        "http://text.local",
        "/jobs",
        1.0,
        transport=httpx.MockTransport(handler),
    )

    result = service.submit(
        "pipeline-job",
        text_path.resolve(),
        "stable-key",
        transcription_path=transcription_path.resolve(),
        uploaded_at=datetime.fromisoformat("2026-09-25T08:00:00+00:00"),
    )

    assert result.model_job_id == "text-http-1"
    headers = captured["headers"]
    assert isinstance(headers, httpx.Headers)
    assert headers["x-pipeline-job-id"] == "pipeline-job"
    assert headers["idempotency-key"] == "stable-key"
    assert headers["content-type"].startswith("multipart/form-data; boundary=")
    body = captured["body"]
    assert isinstance(body, bytes)
    assert b'name="transcript"; filename="transcript.txt"' in body
    assert b"text/plain; charset=utf-8" in body
    assert "Bună".encode("utf-8") in body
    assert b'name="transcription"; filename="transcription.json"' in body
    assert b'{"schemaVersion":1}' in body
    assert b'name="uploadedAt"\r\n\r\n2026-09-25T08:00:00+00:00' in body


def test_job_lock_serializes_mutations(
    client: TestClient,
    store: JobStore,
) -> None:
    job_id = upload(client).json()["jobId"]
    attempted = Event()
    entered = Event()

    def acquire() -> None:
        attempted.set()
        with store.locked_job(job_id):
            entered.set()

    with ThreadPoolExecutor(max_workers=1) as executor:
        with store.locked_job(job_id):
            future = executor.submit(acquire)
            assert attempted.wait(timeout=1)
            assert not entered.wait(timeout=0.05)
        future.result(timeout=1)
        assert entered.is_set()


def test_failed_atomic_artifact_replace_preserves_previous_file(
    client: TestClient,
    store: JobStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = upload(client).json()["jobId"]
    directory = store.job_directory(job_id)
    store.write_artifact_at(
        directory,
        relative_path="transcript/source.json",
        data=b"original",
        media_type="application/json",
    )

    def fail_replace(source: Path, destination: Path) -> None:
        del source, destination
        raise OSError("simulated artifact replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated artifact replace failure"):
        store.write_artifact_at(
            directory,
            relative_path="transcript/source.json",
            data=b"replacement",
            media_type="application/json",
        )

    assert (directory / "transcript/source.json").read_bytes() == b"original"
    assert not list((directory / "transcript").glob(".source.json-*.tmp"))


def test_worker_resumes_transcription_received_after_store_restart(
    client: TestClient,
    store: JobStore,
) -> None:
    job_id = upload(client).json()["jobId"]
    audio_model_job_id = dispatch_audio(store, job_id)
    assert push_transcription(
        client,
        job_id,
        audio_model_job_id,
        transcription_document(job_id, "restart checkpoint"),
    ).status_code == 202

    restarted_store = JobStore(store.root)
    service = RecordingTextService()
    assert process_one(
        restarted_store,
        MockAudioService(),
        logging.getLogger("test.source-restart"),
        service,
    )
    assert restarted_store.read_state(job_id).status == JobStatus.GENERATING_MOM
    assert service.submissions[0][2] == b"restart checkpoint"


def test_http_text_service_maps_rejection_and_invalid_acknowledgement(
    tmp_path: Path,
) -> None:
    text_path = tmp_path / "transcript.txt"
    text_path.write_text("transcript", encoding="utf-8")
    inputs = {"transcription_path": text_path.resolve(), "uploaded_at": utc_now()}

    rejected = HttpTextService(
        "http://text.local",
        "/jobs",
        1.0,
        transport=httpx.MockTransport(lambda request: httpx.Response(400)),
    )
    with pytest.raises(TextProtocolError, match="rejected"):
        rejected.submit("job", text_path.resolve(), "key", **inputs)

    invalid = HttpTextService(
        "http://text.local",
        "/jobs",
        1.0,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(202, json={"unexpected": True})
        ),
    )
    with pytest.raises(TextProtocolError, match="invalid acknowledgement"):
        invalid.submit("job", text_path.resolve(), "key", **inputs)


def test_generating_job_does_not_block_next_queued_job(
    client: TestClient,
    store: JobStore,
) -> None:
    first = upload(client, content=b"first").json()["jobId"]
    first_audio_job = dispatch_audio(store, first)
    assert push_transcription(
        client,
        first,
        first_audio_job,
        transcription_document(first, "first transcript"),
    ).status_code == 202
    assert process_one(
        store,
        MockAudioService(),
        logging.getLogger("test.first-text"),
        RecordingTextService(),
    )
    second = upload(client, content=b"second").json()["jobId"]

    assert process_one(
        store,
        MockAudioService(),
        logging.getLogger("test.generating-blocks"),
        RecordingTextService(),
    )
    assert store.read_state(first).status == JobStatus.GENERATING_MOM
    assert store.read_state(second).status == JobStatus.TRANSCRIBING


def test_mock_audio_service_pushes_transcription_callback_after_delay(
    tmp_path: Path,
) -> None:
    received = Event()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        received.set()
        return httpx.Response(202)

    audio_path = tmp_path / "meeting.mp3"
    audio_path.write_bytes(b"mock audio")
    service = MockAudioService(
        "http://pipeline.local/api/v1/integrations/audio/jobs/{job_id}/transcription",
        callback_delay_seconds=0.01,
        transport=httpx.MockTransport(handler),
    )

    submission = service.submit("pipeline-job", audio_path.resolve())

    assert received.wait(timeout=1)
    assert len(requests) == 1
    request = requests[0]
    assert request.url.path.endswith(
        "/integrations/audio/jobs/pipeline-job/transcription"
    )
    assert request.headers["x-audio-model-job-id"] == submission.model_job_id
    assert request.headers["content-type"] == "application/json"
    document = json.loads(request.content)
    assert document["schemaVersion"] == 1
    assert document["jobId"] == "pipeline-job"
    assert document["quality"]["transcriptConfidence"] == 0.91
    assert "cefazolina" in document["transcript"]["text"]
    assert len(document["transcript"]["segments"]) == 6
    assert document["audioMetadata"]["recordedAt"] == "2026-09-25T08:00:00Z"

    service.ensure_callback("pipeline-job", submission.model_job_id)
    assert len(requests) == 1


def test_mom_callback_persists_json_and_advances_to_review(
    client: TestClient,
    store: JobStore,
) -> None:
    job_id = upload(client).json()["jobId"]
    audio_model_job_id = dispatch_audio(store, job_id)
    assert push_transcription(
        client,
        job_id,
        audio_model_job_id,
        transcription_document(job_id, "meeting transcript"),
    ).status_code == 202
    assert process_one(
        store,
        MockAudioService(),
        logging.getLogger("test.mom-result"),
        RecordingTextService(),
    )
    assert store.read_state(job_id).status == JobStatus.GENERATING_MOM

    payload = mom_document()
    received = push_mom(client, job_id, "text-job-1", payload)

    assert received.status_code == 202
    assert received.json() == {
        "jobId": job_id,
        "status": "AWAITING_REVIEW",
        "stage": "review_ready",
        "replayed": False,
    }
    state = store.read_state(job_id)
    assert state.status == JobStatus.AWAITING_REVIEW
    assert state.stage == "review_ready"
    assert state.artifacts.mom == "mom/draft.json"
    assert state.artifacts.mom_output is not None
    assert state.artifacts.review_context is not None
    assert state.artifacts.notification_intent is not None
    assert (store.job_directory(job_id) / "mom/draft.json").read_bytes() == payload
    assert client.get(f"/api/v1/jobs/{job_id}").json()["artifacts"] == {
        "transcriptAvailable": True,
        "momAvailable": True,
        "reviewContextAvailable": True,
    }
    assert client.get(f"/api/v1/jobs/{job_id}/mom").json() == json.loads(payload)
    review_context = client.get(f"/api/v1/jobs/{job_id}/review-context")
    assert review_context.status_code == 200
    context = review_context.json()
    assert context["submittedBy"] == {
        "userId": "demo-user",
        "displayName": "Demo User",
    }
    assert "email" not in context["submittedBy"]
    assert context["quality"] == {
        "transcriptConfidence": 0.91,
        "momConfidence": 0.86,
        "overallConfidence": None,
        "confidenceScale": "ZERO_TO_ONE",
    }
    assert context["artifacts"]["transcript"]["href"].endswith(
        f"/jobs/{job_id}/transcript"
    )
    persisted_context = json.loads(
        (store.job_directory(job_id) / "review/context.json").read_text(
            encoding="utf-8"
        )
    )
    assert persisted_context["submittedBy"]["email"] == "demo@medpark.test"
    notification_path = store.job_directory(job_id) / "notification/intent.json"
    notification = json.loads(notification_path.read_text(encoding="utf-8"))
    assert notification == {
        "schemaVersion": 1,
        "jobId": job_id,
        "recipient": "demo@medpark.test",
        "subject": "Your Secure MOM draft is ready for review",
        "reviewUrl": f"http://127.0.0.1:3100/?review={job_id}",
        "messageId": f"<secure-mom-review-{job_id}@medpark.test>",
        "createdAt": notification["createdAt"],
    }
    intent_events = [
        event
        for event in store.read_events(job_id)
        if event.event_type == "notification.intent.created"
    ]
    assert len(intent_events) == 1
    assert intent_events[0].value == {"messageId": notification["messageId"]}
    persisted_notification_metadata = notification_path.read_text(encoding="utf-8")
    assert "meeting transcript" not in persisted_notification_metadata
    assert "Mock Minutes" not in persisted_notification_metadata

    replay = push_mom(client, job_id, "text-job-1", payload)
    conflict = push_mom(
        client,
        job_id,
        "text-job-1",
        mom_document("Different Minutes"),
    )
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "MOM_CONFLICT"
    assert len(
        [
            event
            for event in store.read_events(job_id)
            if event.event_type == "notification.intent.created"
        ]
    ) == 1


def test_worker_sends_one_persisted_review_notification(
    client: TestClient,
    store: JobStore,
) -> None:
    transcript_secret = "PRIVATE-TRANSCRIPT-CONTENT"
    mom_secret = "PRIVATE-MOM-CONTENT"
    job_id, _ = create_review_ready_job(
        client,
        store,
        transcript_text=transcript_secret,
        mom_text=mom_secret,
    )
    mail = RecordingMailAdapter()

    assert process_one(
        store,
        MockAudioService(),
        logging.getLogger("test.notification.accepted"),
        RecordingTextService(),
        mail_adapter=mail,
    )
    state = store.read_state(job_id)
    assert state.status == JobStatus.AWAITING_REVIEW
    assert state.stage == "review_ready"
    assert state.error is None
    assert state.artifacts.notification_result is not None
    result = json.loads(
        (store.job_directory(job_id) / "notification/result.json").read_text(
            encoding="utf-8"
        )
    )
    assert result["status"] == "accepted"
    assert result["attemptCount"] == 1
    assert result["acceptanceKnown"] is True
    assert result["retryable"] is False
    assert len(mail.messages) == 1
    message = mail.messages[0]
    assert message.sender == "secure-mom@medpark.test"
    assert message.recipients == ("demo@medpark.test",)
    assert message.message_id == f"<secure-mom-review-{job_id}@medpark.test>"
    notification_metadata = (
        (store.job_directory(job_id) / "notification/intent.json").read_text()
        + (store.job_directory(job_id) / "notification/result.json").read_text()
        + (store.job_directory(job_id) / "operations.ndjson").read_text()
    )
    assert transcript_secret not in notification_metadata
    assert mom_secret not in notification_metadata
    assert transcript_secret not in message.text_body
    assert mom_secret not in message.text_body

    restarted_mail = RecordingMailAdapter()
    assert not process_one(
        store,
        MockAudioService(),
        logging.getLogger("test.notification.restart"),
        RecordingTextService(),
        mail_adapter=restarted_mail,
    )
    assert restarted_mail.messages == []


def test_worker_retries_only_known_pre_acceptance_failure_with_a_bound(
    client: TestClient,
    store: JobStore,
) -> None:
    job_id, _ = create_review_ready_job(client, store)
    failing_mail = RecordingMailAdapter(fail=True)

    assert process_one(
        store,
        MockAudioService(),
        logging.getLogger("test.notification.failed-one"),
        RecordingTextService(),
        mail_adapter=failing_mail,
        notification_max_attempts=2,
    )
    first = json.loads(
        (store.job_directory(job_id) / "notification/result.json").read_text()
    )
    assert first["status"] == "failed"
    assert first["attemptCount"] == 1
    assert first["acceptanceKnown"] is True
    assert first["retryable"] is True

    assert process_one(
        store,
        MockAudioService(),
        logging.getLogger("test.notification.failed-two"),
        RecordingTextService(),
        mail_adapter=failing_mail,
        notification_max_attempts=2,
    )
    second = json.loads(
        (store.job_directory(job_id) / "notification/result.json").read_text()
    )
    assert second["status"] == "failed"
    assert second["attemptCount"] == 2
    assert second["retryable"] is False
    assert [message.message_id for message in failing_mail.messages] == [
        f"<secure-mom-review-{job_id}@medpark.test>",
        f"<secure-mom-review-{job_id}@medpark.test>",
    ]

    assert not process_one(
        store,
        MockAudioService(),
        logging.getLogger("test.notification.failed-stopped"),
        RecordingTextService(),
        mail_adapter=failing_mail,
        notification_max_attempts=2,
    )
    assert len(failing_mail.messages) == 2


def test_worker_does_not_retry_uncertain_or_interrupted_submission(
    client: TestClient,
    store: JobStore,
) -> None:
    uncertain_job, _ = create_review_ready_job(client, store)
    uncertain_mail = RecordingMailAdapter(fail=True, acceptance_unknown=True)
    assert process_one(
        store,
        MockAudioService(),
        logging.getLogger("test.notification.uncertain"),
        RecordingTextService(),
        mail_adapter=uncertain_mail,
    )
    uncertain = json.loads(
        (store.job_directory(uncertain_job) / "notification/result.json").read_text()
    )
    assert uncertain["status"] == "unknown"
    assert uncertain["acceptanceKnown"] is False
    assert uncertain["retryable"] is False
    assert not process_one(
        store,
        MockAudioService(),
        logging.getLogger("test.notification.uncertain-restart"),
        RecordingTextService(),
        mail_adapter=RecordingMailAdapter(),
    )

    interrupted_job, _ = create_review_ready_job(client, store)
    with pytest.raises(KeyboardInterrupt):
        process_one(
            store,
            MockAudioService(),
            logging.getLogger("test.notification.interrupted"),
            RecordingTextService(),
            mail_adapter=CrashingMailAdapter(),
        )
    sending = json.loads(
        (store.job_directory(interrupted_job) / "notification/result.json").read_text()
    )
    assert sending["status"] == "sending"
    recovered_mail = RecordingMailAdapter()
    assert process_one(
        store,
        MockAudioService(),
        logging.getLogger("test.notification.recovered"),
        RecordingTextService(),
        mail_adapter=recovered_mail,
    )
    recovered = json.loads(
        (store.job_directory(interrupted_job) / "notification/result.json").read_text()
    )
    assert recovered["status"] == "unknown"
    assert recovered_mail.messages == []


def test_concurrent_worker_invocation_submits_notification_once(
    client: TestClient,
    store: JobStore,
) -> None:
    create_review_ready_job(client, store)
    started = Event()
    release = Event()
    mail = BlockingMailAdapter(started, release)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            process_one,
            store,
            MockAudioService(),
            logging.getLogger("test.notification.concurrent-one"),
            RecordingTextService(),
            None,
            mail,
        )
        assert started.wait(timeout=2)
        second = executor.submit(
            process_one,
            store,
            MockAudioService(),
            logging.getLogger("test.notification.concurrent-two"),
            RecordingTextService(),
            None,
            mail,
        )
        assert second.result(timeout=2) is False
        release.set()
        assert first.result(timeout=2) is True

    assert len(mail.messages) == 1


def test_local_directory_searches_names_emails_and_titles(client: TestClient) -> None:
    by_name = client.get("/api/v1/directory", params={"q": "ciobanu"})
    by_email = client.get("/api/v1/directory", params={"q": "m.lungu"})
    by_title = client.get("/api/v1/directory", params={"q": "anestezie"})

    assert by_name.status_code == 200
    assert [person["name"] for person in by_name.json()] == ["dr. Ciobanu"]
    assert [person["name"] for person in by_email.json()] == [
        "farmacist clinician Lungu"
    ]
    assert [person["name"] for person in by_title.json()] == ["dr. Munteanu"]


def test_participant_names_accept_directory_or_custom_values_and_persist(
    client: TestClient,
    store: JobStore,
) -> None:
    job_id = upload(client).json()["jobId"]
    audio_job_id = dispatch_audio(store, job_id)
    assert push_transcription(
        client, job_id, audio_job_id, transcription_document(job_id)
    ).status_code == 202
    assert process_one(
        store,
        MockAudioService(),
        logging.getLogger("test.participants"),
        RecordingTextService(),
    )
    assert push_mom(client, job_id, "text-job-1", mom_document()).status_code == 202

    response = client.put(
        f"/api/v1/jobs/{job_id}/participants",
        json={
            "schemaVersion": 1,
            "assignments": [
                {"speakerId": "speaker-1", "displayName": "  Custom Participant  "}
            ],
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["assignments"] == [
        {"speakerId": "speaker-1", "displayName": "Custom Participant"}
    ]
    state = store.read_state(job_id)
    assert state.artifacts.participant_assignments is not None
    persisted = json.loads(
        (store.job_directory(job_id) / "review/participant-assignments.json").read_text(
            encoding="utf-8"
        )
    )
    assert persisted == response.json()
    assert client.get(f"/api/v1/jobs/{job_id}/transcript").json()["speakers"][0][
        "displayName"
    ] == "Custom Participant"
    context = client.get(f"/api/v1/jobs/{job_id}/review-context").json()
    assert context["speakers"][0]["displayName"] == "Custom Participant"
    assert context["meetingMetadata"]["namedSpeakerCount"] == 1
    assert store.read_events(job_id)[-1].event_type == "participants.updated"


def test_participant_names_reject_unknown_speakers(
    client: TestClient,
    store: JobStore,
) -> None:
    job_id = upload(client).json()["jobId"]
    audio_job_id = dispatch_audio(store, job_id)
    assert push_transcription(
        client, job_id, audio_job_id, transcription_document(job_id)
    ).status_code == 202
    assert process_one(
        store,
        MockAudioService(),
        logging.getLogger("test.participants.invalid"),
        RecordingTextService(),
    )
    assert push_mom(client, job_id, "text-job-1", mom_document()).status_code == 202

    response = client.put(
        f"/api/v1/jobs/{job_id}/participants",
        json={
            "schemaVersion": 1,
            "assignments": [
                {"speakerId": "speaker-missing", "displayName": "Unknown"}
            ],
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNKNOWN_SPEAKER"
    assert store.read_state(job_id).artifacts.participant_assignments is None


def test_approval_persists_edited_mom_without_delivery(
    client: TestClient,
    store: JobStore,
) -> None:
    job_id = upload(client).json()["jobId"]
    audio_job_id = dispatch_audio(store, job_id)
    assert push_transcription(
        client, job_id, audio_job_id, transcription_document(job_id)
    ).status_code == 202
    assert process_one(
        store, MockAudioService(), logging.getLogger("test.approval"), RecordingTextService()
    )
    draft = mom_document()
    assert push_mom(client, job_id, "text-job-1", draft).status_code == 202

    processing = client.get(f"/api/v1/jobs/{job_id}/review-context").json()["processing"]
    assert processing["audioStageMs"] >= 0
    assert processing["momStageMs"] >= 0
    assert processing["audioStageMs"] + processing["momStageMs"] <= processing["elapsedMs"]

    document = json.loads(draft)["document"]
    document["summary"] = "Hotărârea aprobată — решение подтверждено."
    request = {"schemaVersion": 1, "document": document, "recipients": []}
    approved = client.post(f"/api/v1/jobs/{job_id}/approve", json=request)
    assert approved.status_code == 200, approved.text
    assert approved.json()["document"]["summary"] == document["summary"]
    assert approved.json()["recipients"] == []
    assert approved.json()["skippedRecipients"] == []
    assert client.get(f"/api/v1/jobs/{job_id}").json()["status"] == "COMPLETED"
    assert client.get(f"/api/v1/jobs/{job_id}/approved-mom").json() == approved.json()
    assert client.get(f"/api/v1/jobs/{job_id}/mom").json() == json.loads(draft)
    assert (store.job_directory(job_id) / "mom/approved.json").is_file()
    assert client.post(f"/api/v1/jobs/{job_id}/approve", json=request).json() == approved.json()

    changed = deepcopy(request)
    changed["document"]["summary"] = "Different approval"
    assert client.post(f"/api/v1/jobs/{job_id}/approve", json=changed).status_code == 409
    assert client.post(f"/api/v1/jobs/{job_id}/approve", json={**request, "recipients": ["staff@medpark.test"]}).status_code == 409


def test_approval_softly_skips_external_recipients_and_delivers_locally(
    client: TestClient,
    store: JobStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = upload(client).json()["jobId"]
    audio_job_id = dispatch_audio(store, job_id)
    assert push_transcription(
        client, job_id, audio_job_id, transcription_document(job_id)
    ).status_code == 202
    assert process_one(
        store,
        MockAudioService(),
        logging.getLogger("test.delivery"),
        RecordingTextService(),
    )
    draft = mom_document()
    assert push_mom(client, job_id, "text-job-1", draft).status_code == 202
    mail = RecordingMailAdapter()
    monkeypatch.setattr(api, "mail_adapter", mail)

    request = {
        "schemaVersion": 1,
        "document": json.loads(draft)["document"],
        "recipients": [
            "Doctor@medpark.test",
            "external@example.com",
            "not-an-email",
            "attacker@example.com,doctor@medpark.test",
            "doctor@medpark.test",
        ],
    }
    response = client.post(f"/api/v1/jobs/{job_id}/approve", json=request)

    assert response.status_code == 200, response.text
    assert response.json()["recipients"] == ["doctor@medpark.test"]
    assert response.json()["skippedRecipients"] == [
        "external@example.com",
        "not-an-email",
        "attacker@example.com,doctor@medpark.test",
    ]
    assert len(mail.messages) == 1
    message = mail.messages[0]
    assert message.sender == "demo@medpark.test"
    assert message.recipients == ("doctor@medpark.test",)
    assert message.message_id == f"<secure-mom-{job_id}@medpark.test>"
    assert "Mock Minutes" in message.text_body
    state = store.read_state(job_id)
    assert state.status == JobStatus.COMPLETED
    assert state.stage == "delivered"
    assert state.artifacts.delivery_result is not None
    result = json.loads(
        (store.job_directory(job_id) / "delivery/result.json").read_text()
    )
    assert result["status"] == "accepted"
    assert result["recipientCount"] == 1

    replay = client.post(f"/api/v1/jobs/{job_id}/approve", json=request)
    assert replay.status_code == 200
    assert len(mail.messages) == 1


def test_delivery_failure_preserves_approval_and_same_request_retries(
    client: TestClient,
    store: JobStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = upload(client).json()["jobId"]
    audio_job_id = dispatch_audio(store, job_id)
    assert push_transcription(
        client, job_id, audio_job_id, transcription_document(job_id)
    ).status_code == 202
    assert process_one(
        store,
        MockAudioService(),
        logging.getLogger("test.delivery-retry"),
        RecordingTextService(),
    )
    draft = mom_document()
    assert push_mom(client, job_id, "text-job-1", draft).status_code == 202
    request = {
        "schemaVersion": 1,
        "document": json.loads(draft)["document"],
        "recipients": ["reviewer@medpark.test"],
    }

    monkeypatch.setattr(api, "mail_adapter", RecordingMailAdapter(fail=True))
    failed = client.post(f"/api/v1/jobs/{job_id}/approve", json=request)
    assert failed.status_code == 502
    assert (store.job_directory(job_id) / "mom/approved.json").is_file()
    state = store.read_state(job_id)
    assert state.status == JobStatus.FAILED
    assert state.stage == "delivery_failed"

    working_mail = RecordingMailAdapter()
    monkeypatch.setattr(api, "mail_adapter", working_mail)
    retried = client.post(f"/api/v1/jobs/{job_id}/approve", json=request)
    assert retried.status_code == 200, retried.text
    assert len(working_mail.messages) == 1
    assert store.read_state(job_id).stage == "delivered"


def test_all_disallowed_recipients_are_skipped_without_smtp(
    client: TestClient,
    store: JobStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = upload(client).json()["jobId"]
    audio_job_id = dispatch_audio(store, job_id)
    assert push_transcription(
        client, job_id, audio_job_id, transcription_document(job_id)
    ).status_code == 202
    assert process_one(
        store,
        MockAudioService(),
        logging.getLogger("test.delivery-skipped"),
        RecordingTextService(),
    )
    draft = mom_document()
    assert push_mom(client, job_id, "text-job-1", draft).status_code == 202
    mail = RecordingMailAdapter()
    monkeypatch.setattr(api, "mail_adapter", mail)

    response = client.post(
        f"/api/v1/jobs/{job_id}/approve",
        json={
            "schemaVersion": 1,
            "document": json.loads(draft)["document"],
            "recipients": ["outside@example.com"],
        },
    )
    assert response.status_code == 200
    assert response.json()["recipients"] == []
    assert response.json()["skippedRecipients"] == ["outside@example.com"]
    assert mail.messages == []
    assert store.read_state(job_id).stage == "approved"


def test_review_context_preserves_missing_model_confidence(
    client: TestClient,
    store: JobStore,
) -> None:
    job_id = upload(client).json()["jobId"]
    audio_model_job_id = dispatch_audio(store, job_id)
    assert push_transcription(
        client,
        job_id,
        audio_model_job_id,
        transcription_document(job_id, confidence=None),
    ).status_code == 202
    assert process_one(
        store,
        MockAudioService(),
        logging.getLogger("test.null-confidence"),
        RecordingTextService(),
    )
    assert push_mom(client, job_id, "text-job-1", mom_document(confidence=None)).status_code == 202

    context = client.get(f"/api/v1/jobs/{job_id}/review-context").json()
    assert context["quality"] == {
        "transcriptConfidence": None,
        "momConfidence": None,
        "overallConfidence": None,
        "confidenceScale": "ZERO_TO_ONE",
    }

def test_mom_callback_validates_contract(
    client: TestClient,
    store: JobStore,
) -> None:
    job_id = upload(client).json()["jobId"]
    audio_model_job_id = dispatch_audio(store, job_id)
    assert push_transcription(
        client,
        job_id,
        audio_model_job_id,
        transcription_document(job_id, "meeting transcript"),
    ).status_code == 202
    assert process_one(
        store,
        MockAudioService(),
        logging.getLogger("test.mom-validation"),
        RecordingTextService(),
    )

    wrong_model = push_mom(client, job_id, "wrong", mom_document())
    invalid_json = push_mom(client, job_id, "text-job-1", b"not json")
    wrong_shape = push_mom(client, job_id, "text-job-1", b"[]")
    wrong_media = push_mom(
        client,
        job_id,
        "text-job-1",
        b'{"a":1,"b":2}',
        "text/plain",
    )

    assert wrong_model.status_code == 409
    assert wrong_model.json()["error"]["code"] == "MOM_CORRELATION_MISMATCH"
    assert invalid_json.status_code == 400
    assert invalid_json.json()["error"]["code"] == "INVALID_MOM_JSON"
    assert wrong_shape.status_code == 400
    assert wrong_shape.json()["error"]["code"] == "INVALID_MOM_JSON"
    assert wrong_media.status_code == 415
    assert wrong_media.json()["error"]["code"] == "UNSUPPORTED_MOM_MEDIA_TYPE"
    assert store.read_state(job_id).status == JobStatus.GENERATING_MOM


def test_in_process_audio_mock_callback_completes_without_loopback_network(
    client: TestClient,
    store: JobStore,
) -> None:
    job_id = upload(client).json()["jobId"]
    audio_service = MockAudioService(
        "http://unreachable.local/api/v1/integrations/audio/jobs/"
        "{job_id}/transcription",
        callback_delay_seconds=0.02,
        callback_sender=make_in_process_callback_sender(api.app),
    )
    text_service = RecordingTextService()

    assert process_one(
        store, audio_service, logging.getLogger("test.in-process.audio"), text_service
    )

    deadline = monotonic() + 2
    while store.read_state(job_id).stage != "transcription_received":
        assert monotonic() < deadline
        sleep(0.01)

    assert process_one(
        store, audio_service, logging.getLogger("test.in-process.text"), text_service
    )
    assert store.read_state(job_id).status == JobStatus.GENERATING_MOM
    assert len(text_service.submissions) == 1


def test_mom_failure_callback_fails_the_job_idempotently(
    client: TestClient,
    store: JobStore,
) -> None:
    job_id = upload(client).json()["jobId"]
    audio_model_job_id = dispatch_audio(store, job_id)
    assert push_transcription(
        client, job_id, audio_model_job_id, transcription_document(job_id)
    ).status_code == 202
    assert process_one(
        store, MockAudioService(), logging.getLogger("test.mom-failure"), RecordingTextService()
    )
    failure = {
        "code": "INVALID_MODEL_OUTPUT",
        "message": "The local language model returned minutes in an invalid structure.",
        "retryable": True,
    }

    wrong_model = push_mom_failure(client, job_id, "wrong", failure)
    received = push_mom_failure(client, job_id, "text-job-1", failure)
    replay = push_mom_failure(client, job_id, "text-job-1", failure)
    late_mom = push_mom(client, job_id, "text-job-1", mom_document())

    assert wrong_model.status_code == 409
    assert wrong_model.json()["error"]["code"] == "MOM_CORRELATION_MISMATCH"
    assert received.status_code == 202
    assert received.json() == {
        "jobId": job_id,
        "status": "FAILED",
        "stage": "text_processing",
        "replayed": False,
    }
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert late_mom.status_code == 409
    job = client.get(f"/api/v1/jobs/{job_id}").json()
    assert job["status"] == "FAILED"
    assert job["error"] == failure
    assert store.read_events(job_id)[-1].event_type == "mom.generation.failed"
