from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from secure_mom_pipeline import api
from secure_mom_pipeline.audio_service import MockAudioService
from secure_mom_pipeline.event_log import EventLog
from secure_mom_pipeline.job_store import JobStore
from secure_mom_pipeline.models import JobStatus, utc_now
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


def test_worker_does_not_dispatch_second_job_while_one_is_active(
    client: TestClient, store: JobStore
) -> None:
    first = upload(client, content=b"first").json()["jobId"]
    second = upload(client, content=b"second").json()["jobId"]
    logger = logging.getLogger("test.worker.single")

    assert process_one(store, MockAudioService(), logger) is True
    assert process_one(store, MockAudioService(), logger) is False

    assert store.read_state(first).status == JobStatus.TRANSCRIBING
    assert store.read_state(second).status == JobStatus.QUEUED


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
