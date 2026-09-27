"""Filesystem-backed single-job worker through text/MoM service dispatch."""

from __future__ import annotations

import argparse
import fcntl
import json
import logging
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator, Protocol

from .audio_service import (
    AudioConnectionError,
    AudioSubmissionError,
    HttpAudioService,
)
from .config import get_settings
from .intermediate_transformer import (
    IntermediateTransformationError,
    IntermediateTransformer,
    StructuredTranscriptionTransformer,
)
from .job_store import InvalidJobStateError, JobStore
from .logging_config import configure_logging
from .mail_adapter import LocalMailAdapter, MailAdapterError, make_local_mail_adapter
from .models import (
    ArtifactDescriptor,
    AudioSubmission,
    JobAttempts,
    JobError,
    JobState,
    JobStatus,
    ModelJobs,
    NotificationIntent,
    NotificationResult,
    TextSubmission,
    TranscriptionSource,
    utc_now,
)
from .review_notification import compose_review_notification
from .text_service import (
    HttpTextService,
    TextConnectionError,
    TextSubmissionError,
)


class AudioService(Protocol):
    def submit(
        self, pipeline_job_id: str, audio_path: Path, idempotency_key: str
    ) -> AudioSubmission: ...


class TextService(Protocol):
    def submit(
        self,
        pipeline_job_id: str,
        text_path: Path,
        idempotency_key: str,
        *,
        transcription_path: Path,
        uploaded_at: datetime,
    ) -> TextSubmission: ...


def _notification_bytes(result: NotificationResult) -> bytes:
    return (
        json.dumps(
            result.model_dump(mode="json", by_alias=True),
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")


def _read_notification_result(
    store: JobStore,
    directory: Path,
    state: JobState,
) -> NotificationResult | None:
    descriptor = state.artifacts.notification_result
    if descriptor is None:
        return None
    return NotificationResult.model_validate_json(
        store.read_artifact_at(directory, descriptor)
    )


def _write_notification_result(
    store: JobStore,
    directory: Path,
    state: JobState,
    result: NotificationResult,
) -> JobState:
    descriptor = store.write_artifact_at(
        directory,
        relative_path="notification/result.json",
        data=_notification_bytes(result),
        media_type="application/json",
    )
    artifacts = state.artifacts.model_copy(
        update={"notification_result": descriptor}
    )
    updated = state.model_copy(
        update={"artifacts": artifacts, "updated_at": utc_now()}
    )
    store.write_state_at(directory, updated)
    return updated


def _advance_review_notification(
    store: JobStore,
    job_id: str,
    mail_adapter: LocalMailAdapter,
    *,
    sender: str,
    max_attempts: int,
    logger: logging.Logger,
) -> bool:
    with store.locked_job(job_id) as directory:
        state = store.read_state(job_id)
        if not (
            state.status == JobStatus.AWAITING_REVIEW
            and state.stage == "review_ready"
            and state.artifacts.notification_intent is not None
        ):
            return False

        intent = NotificationIntent.model_validate_json(
            store.read_artifact_at(directory, state.artifacts.notification_intent)
        )
        if intent.job_id != job_id:
            raise InvalidJobStateError("The notification intent job ID is invalid")

        previous = _read_notification_result(store, directory, state)
        if previous is not None and previous.message_id != intent.message_id:
            raise InvalidJobStateError("The notification result does not match its intent")
        if previous is not None and previous.status in {"accepted", "unknown"}:
            return False
        if previous is not None and previous.status == "sending":
            recovered = previous.model_copy(
                update={
                    "status": "unknown",
                    "retryable": False,
                    "acceptance_known": False,
                    "error_code": "NOTIFICATION_ACCEPTANCE_UNKNOWN",
                }
            )
            _write_notification_result(store, directory, state, recovered)
            store.append_event_at(
                directory,
                job_id=job_id,
                event_type="notification.send.unknown",
                producer="pipeline-worker",
                value={
                    "messageId": intent.message_id,
                    "attemptCount": recovered.attempt_count,
                    "acceptanceKnown": False,
                    "errorCode": recovered.error_code,
                },
            )
            logger.warning(
                "event=notification_acceptance_unknown job_id=%s attempt=%d",
                job_id,
                recovered.attempt_count,
            )
            return True
        if previous is not None and (
            not previous.retryable or previous.attempt_count >= max_attempts
        ):
            return False

        attempt_count = 1 if previous is None else previous.attempt_count + 1
        claim = NotificationResult(
            schema_version=1,
            job_id=job_id,
            status="sending",
            attempted_at=utc_now(),
            attempt_count=attempt_count,
            message_id=intent.message_id,
            retryable=False,
            acceptance_known=False,
            error_code=None,
        )
        _write_notification_result(store, directory, state, claim)
        store.append_event_at(
            directory,
            job_id=job_id,
            event_type="notification.send.started",
            producer="pipeline-worker",
            value={
                "messageId": intent.message_id,
                "attemptCount": attempt_count,
            },
        )

    try:
        mail_adapter.send(compose_review_notification(intent, sender=sender))
    except MailAdapterError as exc:
        acceptance_unknown = exc.acceptance_unknown
        result = claim.model_copy(
            update={
                "status": "unknown" if acceptance_unknown else "failed",
                "retryable": (
                    exc.retryable
                    and not acceptance_unknown
                    and attempt_count < max_attempts
                ),
                "acceptance_known": not acceptance_unknown,
                "error_code": (
                    "NOTIFICATION_ACCEPTANCE_UNKNOWN"
                    if acceptance_unknown
                    else "LOCAL_SMTP_FAILED"
                ),
            }
        )
    else:
        result = claim.model_copy(
            update={
                "status": "accepted",
                "retryable": False,
                "acceptance_known": True,
                "error_code": None,
            }
        )

    with store.locked_job(job_id) as directory:
        state = store.read_state(job_id)
        current = _read_notification_result(store, directory, state)
        if current is None or current.status != "sending":
            return True
        if (
            current.message_id != intent.message_id
            or current.attempt_count != attempt_count
        ):
            raise InvalidJobStateError("The notification claim changed during submission")
        _write_notification_result(store, directory, state, result)
        if result.status == "accepted":
            event_type = "notification.send.accepted"
        elif result.status == "unknown":
            event_type = "notification.send.unknown"
        else:
            event_type = "notification.send.failed"
        store.append_event_at(
            directory,
            job_id=job_id,
            event_type=event_type,
            producer="pipeline-worker",
            value={
                "messageId": intent.message_id,
                "attemptCount": attempt_count,
                "retryable": result.retryable,
                "acceptanceKnown": result.acceptance_known,
                "errorCode": result.error_code,
            },
        )
    logger.info(
        "event=notification_send_finished job_id=%s status=%s attempt=%d",
        job_id,
        result.status,
        attempt_count,
    )
    return True


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
    if not audio_path.is_file():
        raise AudioSubmissionError("The persisted audio is missing")
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

        failure: Exception | None = None
        submission: AudioSubmission | None = None
        try:
            audio_path = _resolve_audio_path(store, job_id, state.artifacts.audio)
        except (AudioSubmissionError, OSError, ValueError) as exc:
            failure = exc
        else:
            idempotency_key = f"{job_id}:transcription:{next_attempt}"
            for transport_attempt in (1, 2):
                try:
                    submission = audio_service.submit(job_id, audio_path, idempotency_key)
                    break
                except AudioConnectionError as exc:
                    failure = exc
                    if transport_attempt == 1:
                        store.append_event(
                            job_id,
                            event_type="audio.dispatch.retried",
                            producer="pipeline-worker",
                            value={"attempt": next_attempt, "retry": 1},
                        )
                except (AudioSubmissionError, OSError, ValueError) as exc:
                    failure = exc
                    break

        if submission is None:
            retryable = not isinstance(failure, AudioSubmissionError) or failure.retryable
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
                retryable=retryable,
                event_type="audio.dispatch.failed",
                event_value={
                    "attempt": next_attempt,
                    "errorCode": "AUDIO_DISPATCH_FAILED",
                    "retryable": retryable,
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


def _verified_artifact_path(
    store: JobStore, directory: Path, descriptor: ArtifactDescriptor
) -> Path:
    """Check a persisted artifact against its descriptor and return its path."""
    store.read_artifact_at(directory, descriptor)
    return (directory / descriptor.path).resolve()


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
            and state.artifacts.transcription_source is not None
        ):
            return False

        try:
            text_path = _verified_artifact_path(
                store, directory, state.artifacts.text_input
            )
            transcription_path = _verified_artifact_path(
                store, directory, state.artifacts.transcription_source
            )
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
                submission = text_service.submit(
                    job_id,
                    text_path,
                    idempotency_key,
                    transcription_path=transcription_path,
                    uploaded_at=state.created_at,
                )
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
    text_service: TextService,
    transformer: IntermediateTransformer | None = None,
    mail_adapter: LocalMailAdapter | None = None,
    notification_sender: str = "secure-mom@medpark.test",
    notification_max_attempts: int = 2,
) -> bool:
    """Advance one job through all immediately available checkpoints."""
    transformer = transformer or StructuredTranscriptionTransformer()

    with _exclusive_worker(store) as acquired:
        if not acquired:
            logger.info("event=worker_busy")
            return False

        states = sorted(
            store.states(),
            key=lambda state: (state.created_at, state.job_id),
        )

        if mail_adapter is not None:
            for state in states:
                if _advance_review_notification(
                    store,
                    state.job_id,
                    mail_adapter,
                    sender=notification_sender,
                    max_attempts=notification_max_attempts,
                    logger=logger,
                ):
                    return True

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
    # The speech-to-text service pushes its outcome back to this API.
    callback_base = f"{settings.audio_callback_base_url.rstrip('/')}{settings.api_prefix}"
    audio_service = HttpAudioService(
        settings.audio_service_url,
        settings.audio_service_jobs_route,
        settings.audio_service_timeout_seconds,
        callback_url=f"{callback_base}{settings.routes.transcription_result}",
        failure_url=f"{callback_base}{settings.routes.transcription_failure}",
    )
    text_service = HttpTextService(
        settings.text_service_url,
        settings.text_service_jobs_route,
        settings.text_service_timeout_seconds,
    )
    transformer = StructuredTranscriptionTransformer()
    mail_adapter = make_local_mail_adapter(settings)

    if args.once:
        process_one(
            store,
            audio_service,
            logger,
            text_service,
            transformer,
            mail_adapter,
            settings.notification_sender,
            settings.notification_max_attempts,
        )
        return

    while True:
        process_one(
            store,
            audio_service,
            logger,
            text_service,
            transformer,
            mail_adapter,
            settings.notification_sender,
            settings.notification_max_attempts,
        )
        time.sleep(settings.worker_interval_seconds)


if __name__ == "__main__":
    run()
