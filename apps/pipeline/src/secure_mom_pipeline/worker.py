"""Filesystem-backed single-job worker through text/MoM service dispatch."""

from __future__ import annotations

import argparse
import fcntl
import logging
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Protocol

from .audio_service import AudioSubmissionError, MockAudioService
from .callback_transport import CallbackSender, make_in_process_callback_sender
from .config import get_settings
from .intermediate_transformer import (
    IntermediateTransformationError,
    IntermediateTransformer,
    StructuredTranscriptionTransformer,
)
from .job_store import InvalidJobStateError, JobStore
from .logging_config import configure_logging
from .models import (
    AudioSubmission,
    JobAttempts,
    JobError,
    JobStatus,
    ModelJobs,
    TextSubmission,
    TranscriptionSource,
    utc_now,
)
from .text_service import (
    MockTextService,
    TextConnectionError,
    TextSubmissionError,
)


class AudioService(Protocol):
    def submit(self, pipeline_job_id: str, audio_path: Path) -> AudioSubmission: ...


class TextService(Protocol):
    def submit(
        self,
        pipeline_job_id: str,
        text_path: Path,
        idempotency_key: str,
    ) -> TextSubmission: ...


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


def _fail_job(
    store: JobStore,
    *,
    state,
    stage: str,
    code: str,
    message: str,
    retryable: bool,
    event_type: str,
    event_value: dict[str, object],
) -> None:
    failed_state = state.model_copy(
        update={
            "status": JobStatus.FAILED,
            "stage": stage,
            "updated_at": utc_now(),
            "error": JobError(
                code=code,
                message=message,
                retryable=retryable,
            ),
        }
    )
    store.write_state(failed_state)
    store.append_event(
        state.job_id,
        event_type="job.state.changed",
        producer="pipeline-worker",
        value={"status": failed_state.status, "stage": failed_state.stage},
    )
    store.append_event(
        state.job_id,
        event_type=event_type,
        producer="pipeline-worker",
        value=event_value,
    )


def _dispatch_audio(
    store: JobStore,
    state,
    audio_service: AudioService,
    logger: logging.Logger,
) -> bool:
    job_id = state.job_id
    next_attempt = state.attempts.transcription + 1
    with store.locked_job(job_id):
        state = store.read_state(job_id)
        if state.status != JobStatus.QUEUED:
            return False
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
                    "attempts": JobAttempts(
                        transcription=next_attempt,
                        mom_generation=state.attempts.mom_generation,
                    )
                }
            )
            _fail_job(
                store,
                state=failed_state,
                stage="audio_dispatch",
                code="AUDIO_DISPATCH_FAILED",
                message="The audio service could not pick up the recording.",
                retryable=True,
                event_type="audio.dispatch.failed",
                event_value={
                    "attempt": next_attempt,
                    "errorCode": "AUDIO_DISPATCH_FAILED",
                    "retryable": True,
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


def _dispatch_text(
    store: JobStore,
    job_id: str,
    text_service: TextService,
    logger: logging.Logger,
) -> bool:
    with store.locked_job(job_id) as directory:
        state = store.read_state(job_id)
        if not (
            state.status == JobStatus.TRANSCRIBING
            and state.stage == "text_input_ready"
            and state.artifacts.text_input is not None
        ):
            return False

        try:
            store.read_artifact_at(directory, state.artifacts.text_input)
            text_path = (directory / state.artifacts.text_input.path).resolve()
        except (InvalidJobStateError, OSError, ValueError):
            _fail_job(
                store,
                state=state,
                stage="text_dispatch",
                code="TEXT_INPUT_INVALID",
                message="The prepared transcript is unavailable or invalid.",
                retryable=False,
                event_type="text.dispatch.failed",
                event_value={
                    "attempt": state.attempts.mom_generation + 1,
                    "errorCode": "TEXT_INPUT_INVALID",
                    "retryable": False,
                },
            )
            return True

        next_attempt = state.attempts.mom_generation + 1
        idempotency_key = f"{job_id}:mom-generation:{next_attempt}"
        store.append_event(
            job_id,
            event_type="text.dispatch.started",
            producer="pipeline-worker",
            value={
                "attempt": next_attempt,
                "artifact": state.artifacts.text_input.path,
                "idempotencyKey": idempotency_key,
            },
        )
        logger.info(
            "event=text_dispatch_started job_id=%s attempt=%d",
            job_id,
            next_attempt,
        )

        failure: TextSubmissionError | None = None
        submission: TextSubmission | None = None
        for transport_attempt in (1, 2):
            try:
                submission = text_service.submit(job_id, text_path, idempotency_key)
                failure = None
                break
            except TextConnectionError as exc:
                failure = exc
                if transport_attempt == 1:
                    store.append_event(
                        job_id,
                        event_type="text.dispatch.retried",
                        producer="pipeline-worker",
                        value={"attempt": next_attempt, "retry": 1},
                    )
                    continue
                break
            except TextSubmissionError as exc:
                failure = exc
                break

        if submission is None:
            retryable = bool(failure and failure.retryable)
            failed_state = state.model_copy(
                update={
                    "attempts": JobAttempts(
                        transcription=state.attempts.transcription,
                        mom_generation=next_attempt,
                    )
                }
            )
            _fail_job(
                store,
                state=failed_state,
                stage="text_dispatch",
                code="TEXT_DISPATCH_FAILED",
                message="The text service did not accept the transcript.",
                retryable=retryable,
                event_type="text.dispatch.failed",
                event_value={
                    "attempt": next_attempt,
                    "errorCode": "TEXT_DISPATCH_FAILED",
                    "retryable": retryable,
                },
            )
            logger.error(
                "event=text_dispatch_failed job_id=%s attempt=%d retryable=%s",
                job_id,
                next_attempt,
                retryable,
            )
            return True

        generating_state = state.model_copy(
            update={
                "status": JobStatus.GENERATING_MOM,
                "stage": "text_processing",
                "updated_at": utc_now(),
                "attempts": JobAttempts(
                    transcription=state.attempts.transcription,
                    mom_generation=next_attempt,
                ),
                "model_jobs": ModelJobs(
                    audio=state.model_jobs.audio,
                    text=submission.model_job_id,
                ),
                "error": None,
            }
        )
        store.write_state(generating_state)
        store.append_event(
            job_id,
            event_type="job.state.changed",
            producer="pipeline-worker",
            value={
                "status": generating_state.status,
                "stage": generating_state.stage,
            },
        )
        store.append_event(
            job_id,
            event_type="text.dispatch.accepted",
            producer="pipeline-worker",
            value={
                "attempt": next_attempt,
                "status": generating_state.status,
                "stage": generating_state.stage,
                "modelJobId": submission.model_job_id,
            },
        )
        logger.info(
            "event=text_dispatch_accepted job_id=%s attempt=%d model_job_id=%s",
            job_id,
            next_attempt,
            submission.model_job_id,
        )
        return True


def _transform_transcription(
    store: JobStore,
    job_id: str,
    transformer: IntermediateTransformer,
    text_service: TextService,
    logger: logging.Logger,
) -> bool:
    with store.locked_job(job_id) as directory:
        state = store.read_state(job_id)
        descriptor = state.artifacts.transcription_source
        if not (
            state.status == JobStatus.TRANSCRIBING
            and state.stage == "transcription_received"
            and descriptor is not None
        ):
            return False

        store.append_event(
            job_id,
            event_type="transcription.transform.started",
            producer="pipeline-worker",
            value={"artifact": descriptor.path},
        )
        try:
            source_bytes = store.read_artifact_at(directory, descriptor)
            document = transformer.transform(
                TranscriptionSource(
                    data=source_bytes,
                    media_type=descriptor.media_type,
                )
            )
            text_bytes = document.text.encode("utf-8")
            text_descriptor = store.write_artifact_at(
                directory,
                relative_path="transcript/transcript.txt",
                data=text_bytes,
                media_type="text/plain; charset=utf-8",
            )
        except (
            IntermediateTransformationError,
            InvalidJobStateError,
            OSError,
            ValueError,
        ):
            _fail_job(
                store,
                state=state,
                stage="transcript_transform",
                code="TRANSCRIPT_TRANSFORM_FAILED",
                message="The transcription could not be converted to UTF-8 text.",
                retryable=False,
                event_type="transcription.transform.failed",
                event_value={
                    "errorCode": "TRANSCRIPT_TRANSFORM_FAILED",
                    "retryable": False,
                },
            )
            logger.error("event=transcription_transform_failed job_id=%s", job_id)
            return True

        artifacts = state.artifacts.model_copy(
            update={
                "text_input": text_descriptor,
            }
        )
        ready_state = state.model_copy(
            update={
                "status": JobStatus.TRANSCRIBING,
                "stage": "text_input_ready",
                "updated_at": utc_now(),
                "artifacts": artifacts,
                "error": None,
            }
        )
        store.write_state(ready_state)
        store.append_event(
            job_id,
            event_type="job.state.changed",
            producer="pipeline-worker",
            value={"status": ready_state.status, "stage": ready_state.stage},
        )
        store.append_event(
            job_id,
            event_type="transcription.transform.completed",
            producer="pipeline-worker",
            value={
                "artifact": text_descriptor.path,
                "bytes": text_descriptor.byte_count,
                "sha256": text_descriptor.sha256,
                "mediaType": text_descriptor.media_type,
            },
        )
        logger.info(
            "event=transcription_transform_completed job_id=%s bytes=%d",
            job_id,
            text_descriptor.byte_count,
        )

    return _dispatch_text(store, job_id, text_service, logger)


def process_one(
    store: JobStore,
    audio_service: AudioService,
    logger: logging.Logger,
    text_service: TextService | None = None,
    transformer: IntermediateTransformer | None = None,
) -> bool:
    """Advance one job through all immediately available checkpoints."""
    text_service = text_service or MockTextService()
    transformer = transformer or StructuredTranscriptionTransformer()

    with _exclusive_worker(store) as acquired:
        if not acquired:
            logger.info("event=worker_busy")
            return False

        states = sorted(
            store.states(),
            key=lambda state: (state.created_at, state.job_id),
        )

        for state in states:
            if (
                state.status == JobStatus.TRANSCRIBING
                and state.stage == "audio_processing"
            ):
                ensure_callback = getattr(audio_service, "ensure_callback", None)
                if callable(ensure_callback) and state.model_jobs.audio is not None:
                    ensure_callback(state.job_id, state.model_jobs.audio)
            if (
                state.status == JobStatus.GENERATING_MOM
                and state.stage == "text_processing"
            ):
                ensure_callback = getattr(text_service, "ensure_callback", None)
                if callable(ensure_callback) and state.model_jobs.text is not None:
                    ensure_callback(state.job_id, state.model_jobs.text)

        for state in states:
            if state.status != JobStatus.TRANSCRIBING:
                continue
            if state.stage == "transcription_received":
                return _transform_transcription(
                    store,
                    state.job_id,
                    transformer,
                    text_service,
                    logger,
                )
            if state.stage == "text_input_ready":
                return _dispatch_text(store, state.job_id, text_service, logger)

        queued = [state for state in states if state.status == JobStatus.QUEUED]
        if not queued:
            waiting_count = sum(
                state.status in {JobStatus.TRANSCRIBING, JobStatus.GENERATING_MOM}
                for state in states
            )
            logger.info("event=worker_idle waiting_jobs=%d", waiting_count)
            return False
        return _dispatch_audio(store, queued[0], audio_service, logger)


def run() -> None:
    parser = argparse.ArgumentParser(description="Run the filesystem-backed worker")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Attempt one queued or resumable job and exit",
    )
    args = parser.parse_args()
    settings = get_settings()
    logger = configure_logging(settings.log_file)
    store = JobStore(settings.storage_root)
    callback_sender: CallbackSender | None
    if settings.mock_callback_transport == "in_process":
        # Import lazily so worker unit tests and adapter modules remain
        # independent from the FastAPI control surface.
        from .api import app

        callback_sender = make_in_process_callback_sender(app)
    elif settings.mock_callback_transport == "http":
        callback_sender = None
    else:
        raise ValueError(
            "PIPELINE_MOCK_CALLBACK_TRANSPORT must be 'in_process' or 'http'"
        )
    callback_url_template = (
        f"{settings.mock_audio_callback_base_url.rstrip('/')}"
        f"{settings.api_prefix}{settings.routes.transcription_result}"
    )
    audio_service = MockAudioService(
        callback_url_template=callback_url_template,
        callback_delay_seconds=settings.mock_audio_callback_delay_seconds,
        callback_sender=callback_sender,
    )
    text_callback_url_template = (
        f"{settings.mock_text_callback_base_url.rstrip('/')}"
        f"{settings.api_prefix}{settings.routes.mom_result}"
    )
    text_service = MockTextService(
        callback_url_template=text_callback_url_template,
        callback_delay_seconds=settings.mock_text_callback_delay_seconds,
        callback_sender=callback_sender,
    )
    transformer = StructuredTranscriptionTransformer()

    if args.once:
        process_one(store, audio_service, logger, text_service, transformer)
        return

    while True:
        process_one(store, audio_service, logger, text_service, transformer)
        time.sleep(settings.mock_worker_interval_seconds)


if __name__ == "__main__":
    run()
