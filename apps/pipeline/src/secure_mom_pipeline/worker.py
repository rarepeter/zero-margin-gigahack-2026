"""Filesystem-backed single-job worker through mock audio-service pickup."""

from __future__ import annotations

import argparse
import fcntl
import logging
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Protocol

from .audio_service import AudioSubmissionError, MockAudioService
from .config import get_settings
from .job_store import JobStore
from .logging_config import configure_logging
from .models import (
    AudioSubmission,
    JobAttempts,
    JobError,
    JobStatus,
    ModelJobs,
    utc_now,
)


class AudioService(Protocol):
    def submit(self, pipeline_job_id: str, audio_path: Path) -> AudioSubmission: ...


@contextmanager
def _exclusive_worker(store: JobStore) -> Iterator[bool]:
    store.root.mkdir(parents=True, exist_ok=True)
    with store.worker_lock_path.open("a+") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _resolve_audio_path(store: JobStore, job_id: str, relative_path: str) -> Path:
    job_directory = store.job_directory(job_id)
    candidate_path = Path(relative_path)
    if candidate_path.is_absolute():
        raise AudioSubmissionError("The persisted audio path must be relative")
    audio_path = (job_directory / candidate_path).resolve()
    if not audio_path.is_relative_to(job_directory):
        raise AudioSubmissionError("The persisted audio path escapes its job")
    return audio_path


def process_one(
    store: JobStore,
    audio_service: AudioService,
    logger: logging.Logger,
) -> bool:
    """Dispatch one queued job, returning whether a job was attempted."""
    with _exclusive_worker(store) as acquired:
        if not acquired:
            logger.info("event=worker_busy")
            return False

        states = store.states()
        if any(state.status == JobStatus.TRANSCRIBING for state in states):
            logger.info("event=worker_waiting reason=active_job")
            return False

        queued = sorted(
            (state for state in states if state.status == JobStatus.QUEUED),
            key=lambda state: (state.created_at, state.job_id),
        )
        if not queued:
            logger.info("event=worker_idle")
            return False

        state = queued[0]
        job_id = state.job_id
        next_attempt = state.attempts.transcription + 1
        store.append_event(
            job_id,
            event_type="worker.job.claimed",
            producer="pipeline-worker",
            value={"attempt": next_attempt, "status": state.status},
        )
        store.append_event(
            job_id,
            event_type="audio.dispatch.started",
            producer="pipeline-worker",
            value={"attempt": next_attempt, "artifact": state.artifacts.audio},
        )
        logger.info(
            "event=audio_dispatch_started job_id=%s attempt=%d",
            job_id,
            next_attempt,
        )

        try:
            audio_path = _resolve_audio_path(store, job_id, state.artifacts.audio)
            submission = audio_service.submit(job_id, audio_path)
        except (AudioSubmissionError, OSError, ValueError):
            failed_state = state.model_copy(
                update={
                    "status": JobStatus.FAILED,
                    "stage": "audio_dispatch",
                    "updated_at": utc_now(),
                    "attempts": JobAttempts(
                        transcription=next_attempt,
                        mom_generation=state.attempts.mom_generation,
                    ),
                    "error": JobError(
                        code="AUDIO_DISPATCH_FAILED",
                        message="The audio service could not pick up the recording.",
                        retryable=True,
                    ),
                }
            )
            store.write_state(failed_state)
            store.append_event(
                job_id,
                event_type="job.state.changed",
                producer="pipeline-worker",
                value={"status": failed_state.status, "stage": failed_state.stage},
            )
            store.append_event(
                job_id,
                event_type="audio.dispatch.failed",
                producer="pipeline-worker",
                value={
                    "attempt": next_attempt,
                    "errorCode": failed_state.error.code,
                    "retryable": failed_state.error.retryable,
                },
            )
            logger.error(
                "event=audio_dispatch_failed job_id=%s attempt=%d",
                job_id,
                next_attempt,
            )
            return True

        transcribing_state = state.model_copy(
            update={
                "status": JobStatus.TRANSCRIBING,
                "stage": "audio_processing",
                "updated_at": utc_now(),
                "attempts": JobAttempts(
                    transcription=next_attempt,
                    mom_generation=state.attempts.mom_generation,
                ),
                "model_jobs": ModelJobs(
                    audio=submission.model_job_id,
                    text=state.model_jobs.text,
                ),
                "error": None,
            }
        )
        store.write_state(transcribing_state)
        store.append_event(
            job_id,
            event_type="job.state.changed",
            producer="pipeline-worker",
            value={
                "status": transcribing_state.status,
                "stage": transcribing_state.stage,
            },
        )
        store.append_event(
            job_id,
            event_type="audio.dispatch.accepted",
            producer="pipeline-worker",
            value={
                "attempt": next_attempt,
                "status": transcribing_state.status,
                "stage": transcribing_state.stage,
                "modelJobId": submission.model_job_id,
            },
        )
        logger.info(
            "event=audio_dispatch_accepted job_id=%s attempt=%d model_job_id=%s",
            job_id,
            next_attempt,
            submission.model_job_id,
        )
        return True


def run() -> None:
    parser = argparse.ArgumentParser(description="Run the filesystem-backed worker")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Attempt one queued job and exit",
    )
    args = parser.parse_args()
    settings = get_settings()
    logger = configure_logging(settings.log_file)
    store = JobStore(settings.storage_root)
    audio_service = MockAudioService()

    if args.once:
        process_one(store, audio_service, logger)
        return

    while True:
        process_one(store, audio_service, logger)
        time.sleep(settings.mock_worker_interval_seconds)


if __name__ == "__main__":
    run()
