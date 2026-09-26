from __future__ import annotations

import json
import logging
import os
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
from secure_mom_pipeline.models import (
    JobStatus,
    TextSubmission,
    TranscriptionSource,
    utc_now,
)
from secure_mom_pipeline.text_service import (
    HttpTextService,
    MockTextService,
    TextConnectionError,
    TextProtocolError,
)
from secure_mom_pipeline.worker import process_one


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
    confidence: float = 0.91,
) -> bytes:
    return json.dumps(
        {
            "schemaVersion": "transcription.v1alpha1",
            "jobId": job_id,
            "transcript": {
                "text": text,
                "segments": [
                    {
                        "id": "segment-1",
                        "startMs": 0,
                        "endMs": 3000,
                        "speakerId": "speaker-1",
                        "languages": ["ro", "ru", "en"],
                        "text": text,
                        "confidence": confidence,
                    }
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


def mom_document(content: str = "Mock Minutes", confidence: float = 0.86) -> bytes:
    return json.dumps(
        {
            "schemaVersion": "mom.v1alpha1",
            "quality": {
                "momConfidence": confidence,
                "confidenceScale": "ZERO_TO_ONE",
            },
            "document": {"content": content},
        },
        separators=(",", ":"),
    ).encode("utf-8")


def dispatch_audio(store: JobStore, job_id: str) -> str:
    assert process_one(
        store,
        MockAudioService(),
        logging.getLogger("test.dispatch-audio"),
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

    def submit(
        self,
        pipeline_job_id: str,
        text_path: Path,
        idempotency_key: str,
    ) -> TextSubmission:
        self.submissions.append(
            (pipeline_job_id, idempotency_key, text_path.read_bytes())
        )
        return TextSubmission(model_job_id="text-job-1", status="accepted")


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

    assert process_one(store, MockAudioService(), logger) is True

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

    assert process_one(store, MockAudioService(), logger) is True
    assert process_one(store, MockAudioService(), logger) is True

    assert store.read_state(first).status == JobStatus.TRANSCRIBING
    assert store.read_state(second).status == JobStatus.TRANSCRIBING


def test_worker_records_safe_failure_when_audio_is_missing(
    client: TestClient, store: JobStore
) -> None:
    job_id = upload(client).json()["jobId"]
    state = store.read_state(job_id)
    (store.job_directory(job_id) / state.artifacts.audio).unlink()

    assert process_one(
        store, MockAudioService(), logging.getLogger("test.worker.failure")
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
        ) -> TextSubmission:
            self.calls += 1
            if self.calls == 1:
                raise TextConnectionError("temporary")
            return super().submit(pipeline_job_id, text_path, idempotency_key)

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
        def submit(
            self,
            pipeline_job_id: str,
            text_path: Path,
            idempotency_key: str,
        ) -> TextSubmission:
            del pipeline_job_id, text_path, idempotency_key
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


def test_http_text_service_uploads_transcript_as_multipart_txt(tmp_path: Path) -> None:
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
    service = HttpTextService(
        "http://text.local",
        "/jobs",
        1.0,
        transport=httpx.MockTransport(handler),
    )

    result = service.submit("pipeline-job", text_path.resolve(), "stable-key")

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

    rejected = HttpTextService(
        "http://text.local",
        "/jobs",
        1.0,
        transport=httpx.MockTransport(lambda request: httpx.Response(400)),
    )
    with pytest.raises(TextProtocolError, match="rejected"):
        rejected.submit("job", text_path.resolve(), "key")

    invalid = HttpTextService(
        "http://text.local",
        "/jobs",
        1.0,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(202, json={"unexpected": True})
        ),
    )
    with pytest.raises(TextProtocolError, match="invalid acknowledgement"):
        invalid.submit("job", text_path.resolve(), "key")


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
    assert document["schemaVersion"] == "transcription.v1alpha1"
    assert document["jobId"] == "pipeline-job"
    assert document["quality"]["transcriptConfidence"] == 0.91
    assert document["transcript"]["text"] == (
        "Mock transcription for pipeline job pipeline-job."
    )

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


def test_mock_text_service_pushes_versioned_mom_callback_after_delay(
    tmp_path: Path,
) -> None:
    received = Event()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        received.set()
        return httpx.Response(202)

    text_path = tmp_path / "transcript.txt"
    text_path.write_text("meeting transcript", encoding="utf-8")
    service = MockTextService(
        "http://pipeline.local/api/v1/integrations/text/jobs/{job_id}/mom",
        callback_delay_seconds=0.01,
        transport=httpx.MockTransport(handler),
    )

    submission = service.submit("pipeline-job", text_path.resolve(), "key")

    assert received.wait(timeout=1)
    assert len(requests) == 1
    request = requests[0]
    assert request.url.path.endswith("/integrations/text/jobs/pipeline-job/mom")
    assert request.headers["x-text-model-job-id"] == submission.model_job_id
    assert request.headers["content-type"] == "application/json"
    document = json.loads(request.content)
    assert list(document) == ["schemaVersion", "quality", "document"]
    assert document == {
        "schemaVersion": "mom.v1alpha1",
        "quality": {
            "momConfidence": 0.86,
            "confidenceScale": "ZERO_TO_ONE",
        },
        "document": {"content": "Mock Minutes of Meeting"},
    }

    service.ensure_callback("pipeline-job", submission.model_job_id)
    assert len(requests) == 1


def test_in_process_mock_callbacks_complete_without_loopback_network(
    client: TestClient,
    store: JobStore,
) -> None:
    job_id = upload(client).json()["jobId"]
    callback_sender = make_in_process_callback_sender(api.app)
    audio_service = MockAudioService(
        "http://unreachable.local/api/v1/integrations/audio/jobs/"
        "{job_id}/transcription",
        callback_delay_seconds=0.02,
        callback_sender=callback_sender,
    )
    text_service = MockTextService(
        "http://unreachable.local/api/v1/integrations/text/jobs/{job_id}/mom",
        callback_delay_seconds=0.02,
        callback_sender=callback_sender,
    )

    assert process_one(
        store,
        audio_service,
        logging.getLogger("test.in-process.audio"),
        text_service,
    )

    deadline = monotonic() + 2
    while store.read_state(job_id).stage != "transcription_received":
        assert monotonic() < deadline
        sleep(0.01)

    assert process_one(
        store,
        audio_service,
        logging.getLogger("test.in-process.text"),
        text_service,
    )

    while store.read_state(job_id).status != JobStatus.AWAITING_REVIEW:
        assert monotonic() < deadline
        sleep(0.01)

    state = store.read_state(job_id)
    assert state.stage == "review_ready"
    assert state.artifacts.mom_output is not None
    assert state.artifacts.review_context is not None
