"""Append-only, Kafka-shaped NDJSON event records for one pipeline job."""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .models import EventRecord, utc_now


class EventLogCorruptError(ValueError):
    """Raised when an existing event log cannot be read as ordered records."""


class EventLog:
    def __init__(self, path: Path) -> None:
        self.path = path

    def append(
        self,
        *,
        key: str,
        event_type: str,
        producer: str,
        value: dict[str, Any],
    ) -> EventRecord:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a+", encoding="utf-8") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                records = self._read_locked(stream)
                offset = records[-1].offset + 1 if records else 0
                record = EventRecord(
                    offset=offset,
                    timestamp=utc_now(),
                    key=key,
                    event_type=event_type,
                    producer=producer,
                    value=value,
                )
                stream.seek(0, os.SEEK_END)
                stream.write(
                    json.dumps(
                        record.model_dump(mode="json", by_alias=True),
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                    + "\n"
                )
                stream.flush()
                os.fsync(stream.fileno())
                return record
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def read(self, from_offset: int = 0) -> list[EventRecord]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_SH)
            try:
                return [
                    record
                    for record in self._read_locked(stream)
                    if record.offset >= from_offset
                ]
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _read_locked(self, stream: Any) -> list[EventRecord]:
        stream.seek(0)
        records: list[EventRecord] = []
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                record = EventRecord.model_validate_json(line)
            except (ValidationError, ValueError) as exc:
                raise EventLogCorruptError(
                    f"Invalid event record at line {line_number}"
                ) from exc
            expected_offset = len(records)
            if record.offset != expected_offset:
                raise EventLogCorruptError(
                    f"Expected offset {expected_offset}, found {record.offset}"
                )
            records.append(record)
        return records
