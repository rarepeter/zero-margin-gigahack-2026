"""Atomic filesystem persistence and discovery for pipeline jobs."""

from __future__ import annotations

import json
import os
import shutil
import fcntl
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from typing import Iterator
from uuid import UUID, uuid4

from pydantic import ValidationError

from .event_log import EventLog
from .models import ArtifactDescriptor, EventRecord, JobState


class JobNotFoundError(FileNotFoundError):
    """Raised when a caller addresses an unknown or invalid job ID."""


class InvalidJobStateError(ValueError):
    """Raised when persisted job state cannot be validated."""


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class JobStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.jobs_root = root / "jobs"
        self.staging_root = root / ".staging"
        self.worker_lock_path = root / "worker.lock"

    @staticmethod
    def new_job_id() -> str:
        return str(uuid4())

    @staticmethod
    def validate_job_id(job_id: str) -> str:
        try:
            parsed = UUID(job_id)
        except (ValueError, AttributeError) as exc:
            raise JobNotFoundError("Job not found") from exc
        canonical = str(parsed)
        if canonical != job_id:
            raise JobNotFoundError("Job not found")
        return canonical

    def prepare_staging(self, job_id: str) -> Path:
        canonical = self.validate_job_id(job_id)
        self.staging_root.mkdir(parents=True, exist_ok=True)
        directory = self.staging_root / canonical
        directory.mkdir(mode=0o700)
        return directory

    def discard_staging(self, directory: Path) -> None:
        resolved_root = self.staging_root.resolve()
        resolved_directory = directory.resolve()
        if resolved_directory.parent != resolved_root:
            raise ValueError("Refusing to remove a path outside the staging root")
        if resolved_directory.exists():
            shutil.rmtree(resolved_directory)

    def publish(self, staging_directory: Path, job_id: str) -> Path:
        canonical = self.validate_job_id(job_id)
        if staging_directory.resolve().parent != self.staging_root.resolve():
            raise ValueError("The staging directory is outside the staging root")
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        destination = self.jobs_root / canonical
        if destination.exists():
            raise FileExistsError("The job already exists")
        os.replace(staging_directory, destination)
        _fsync_directory(self.jobs_root)
        return destination

    def job_directory(self, job_id: str) -> Path:
        canonical = self.validate_job_id(job_id)
        directory = self.jobs_root / canonical
        if not directory.is_dir():
            raise JobNotFoundError("Job not found")
        resolved = directory.resolve()
        if resolved.parent != self.jobs_root.resolve():
            raise JobNotFoundError("Job not found")
        return resolved

    @contextmanager
    def locked_job(self, job_id: str) -> Iterator[Path]:
        """Serialize state/artifact mutations for one published job."""
        directory = self.job_directory(job_id)
        lock_path = directory / ".job.lock"
        with lock_path.open("a+") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield directory
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _artifact_path(directory: Path, relative_path: str) -> Path:
        candidate = Path(relative_path)
        if candidate.is_absolute():
            raise ValueError("Artifact paths must be relative")
        resolved_directory = directory.resolve()
        resolved = (resolved_directory / candidate).resolve()
        if not resolved.is_relative_to(resolved_directory):
            raise ValueError("The artifact path escapes its job")
        return resolved

    def write_artifact_at(
        self,
        directory: Path,
        *,
        relative_path: str,
        data: bytes,
        media_type: str,
    ) -> ArtifactDescriptor:
        target = self._artifact_path(directory, relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.parent / f".{target.name}-{uuid4()}.tmp"
        digest = sha256(data).hexdigest()
        try:
            with temporary.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            written = temporary.read_bytes()
            if len(written) != len(data) or sha256(written).hexdigest() != digest:
                raise OSError("Artifact verification failed")
            os.replace(temporary, target)
            _fsync_directory(target.parent)
        finally:
            temporary.unlink(missing_ok=True)
        return ArtifactDescriptor(
            path=relative_path,
            media_type=media_type,
            byte_count=len(data),
            sha256=digest,
        )

    def read_artifact_at(
        self,
        directory: Path,
        descriptor: ArtifactDescriptor,
    ) -> bytes:
        data = self._artifact_path(directory, descriptor.path).read_bytes()
        if len(data) != descriptor.byte_count:
            raise InvalidJobStateError("The artifact byte count does not match state")
        if sha256(data).hexdigest() != descriptor.sha256:
            raise InvalidJobStateError("The artifact digest does not match state")
        return data

    def write_state_at(self, directory: Path, state: JobState) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / "state.json"
        temporary = directory / f".state-{uuid4()}.tmp"
        data = (
            json.dumps(
                state.model_dump(mode="json", by_alias=True),
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        try:
            with temporary.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            JobState.model_validate_json(temporary.read_bytes())
            os.replace(temporary, target)
            _fsync_directory(directory)
        finally:
            temporary.unlink(missing_ok=True)

    def write_state(self, state: JobState) -> None:
        self.write_state_at(self.job_directory(state.job_id), state)

    def read_state(self, job_id: str) -> JobState:
        directory = self.job_directory(job_id)
        try:
            state = JobState.model_validate_json((directory / "state.json").read_bytes())
        except FileNotFoundError as exc:
            raise InvalidJobStateError("The job state file is missing") from exc
        except (ValidationError, ValueError) as exc:
            raise InvalidJobStateError("The job state file is invalid") from exc
        if state.job_id != job_id:
            raise InvalidJobStateError("The state job ID does not match its directory")
        return state

    def append_event_at(
        self,
        directory: Path,
        *,
        job_id: str,
        event_type: str,
        producer: str,
        value: dict[str, object],
    ) -> EventRecord:
        return EventLog(directory / "operations.ndjson").append(
            key=job_id,
            event_type=event_type,
            producer=producer,
            value=value,
        )

    def append_event(
        self,
        job_id: str,
        *,
        event_type: str,
        producer: str,
        value: dict[str, object],
    ) -> EventRecord:
        return self.append_event_at(
            self.job_directory(job_id),
            job_id=job_id,
            event_type=event_type,
            producer=producer,
            value=value,
        )

    def read_events(self, job_id: str, from_offset: int = 0) -> list[EventRecord]:
        return EventLog(self.job_directory(job_id) / "operations.ndjson").read(
            from_offset
        )

    def states(self) -> list[JobState]:
        if not self.jobs_root.exists():
            return []
        states: list[JobState] = []
        for directory in self.jobs_root.iterdir():
            if not directory.is_dir():
                continue
            try:
                states.append(self.read_state(directory.name))
            except (JobNotFoundError, InvalidJobStateError):
                continue
        return states
