# Pipeline artifact specifications

Status: accepted storage direction; individual shapes are provisional  
Last updated: 26 September 2026

## Job directory

Proposed logical layout:

```text
runtime/jobs/<job-id>/
  state.json
  input/
    meeting.<original-extension>
  transcript/
    source.bin
    transcript.txt
  mom/
    draft.json
  operations.ndjson
```

Names may change during implementation, but every job remains self-contained.
Runtime job directories and all their contents must be ignored by Git.

## `state.json`

The state file is pipeline-owned. A provisional shape is:

```json
{
  "schemaVersion": 2,
  "jobId": "01J...",
  "status": "AWAITING_REVIEW",
  "stage": "review_ready",
  "createdAt": "2026-09-26T12:00:00Z",
  "updatedAt": "2026-09-26T12:01:12Z",
  "attempts": {
    "transcription": 1,
    "momGeneration": 1
  },
  "modelJobs": {
    "audio": "audio-job-123",
    "text": "text-job-456"
  },
  "artifacts": {
    "audio": "input/meeting.wav",
    "transcript": "transcript/transcript.txt",
    "transcriptionSource": {
      "path": "transcript/source.bin",
      "mediaType": "application/json",
      "byteCount": 1234,
      "sha256": "<64 lowercase hexadecimal characters>"
    },
    "textInput": {
      "path": "transcript/transcript.txt",
      "mediaType": "text/plain; charset=utf-8",
      "byteCount": 1234,
      "sha256": "<64 lowercase hexadecimal characters>"
    },
    "mom": "mom/draft.json",
    "momOutput": {
      "path": "mom/draft.json",
      "mediaType": "application/json",
      "byteCount": 82,
      "sha256": "<64 lowercase hexadecimal characters>"
    }
  },
  "error": null
}
```

All paths stored here are relative to the job directory. Absolute paths may be
resolved only at the integration boundary when a local ML service needs them.

The allowed public statuses are:

```text
QUEUED
TRANSCRIBING
GENERATING_MOM
AWAITING_REVIEW
COMPLETED
FAILED
```

The initial pipeline is expected to stop at `AWAITING_REVIEW`. The role of
`COMPLETED` remains open.

## Audio artifact

- The uploaded bytes are preserved without modification by the pipeline.
- The server controls the stored filename and never trusts a client path.
- Original filename and media type may be recorded as metadata, but must not be
  used to resolve filesystem locations.
- Supported formats and maximum size are not yet agreed.

## Transcription artifacts

The audio-to-text service pushes a small non-empty byte document. The pipeline
atomically preserves those original bytes without assuming whether their
textual content uses plain text, JSON, or CSV syntax:

```text
transcript/source.bin
```

The initial transformer strictly decodes the source as UTF-8 and writes every
decoded character unchanged to:

```text
transcript/transcript.txt
```

JSON remains JSON text and CSV remains CSV text inside this file; the current
transformer does not extract fields, normalize content, or concatenate text.
The text/MoM adapter uploads the artifact as multipart file `transcript.txt`
with media type `text/plain; charset=utf-8`.

An empty source or invalid UTF-8 is rejected. A later transformer may implement
format-aware extraction or concatenation without changing the ML adapters.

## Draft MoM artifact

The canonical artifact is UTF-8 JSON:

```text
mom/draft.json
```

The definitive content schema will be agreed later with the text-model and
frontend workstreams. Until then, the pipeline must treat the model-produced MoM
as a JSON document, validate that it is syntactically valid, and retain schema
version information when provided.

A non-binding two-field envelope used by the development mock is:

```json
{
  "schemaVersion": "mock-v1",
  "document": {
    "content": "Mock Minutes of Meeting"
  }
}
```

The mock sends this object to the pipeline callback after a configurable
five-second delay. The pipeline validates that the result is a UTF-8 JSON object
and atomically persists the original bytes before advancing to
`AWAITING_REVIEW`.

This envelope does not define clinical, financial, administrative, executive,
operational, or crisis-meeting MoM fields and must not be presented as the
final model contract.

## Operational events

An append-only NDJSON file may record recovery-relevant operational events such
as queueing, stage transitions, model job IDs, retries, completion, and failure.
It is not the canonical current state; `state.json` is.

The team has not agreed a strict content-logging policy. The implementation must
not claim that operational logs are free of meeting-derived content until that
policy and its tests exist.

The implemented event file uses one UTF-8 JSON object per line and a stable,
Kafka-shaped envelope:

```json
{
  "schemaVersion": 1,
  "offset": 4,
  "timestamp": "2026-09-26T12:01:12Z",
  "topic": "pipeline.job-events",
  "key": "<job-id>",
  "eventType": "audio.dispatch.accepted",
  "producer": "pipeline-worker",
  "value": {
    "status": "TRANSCRIBING",
    "stage": "audio_processing",
    "modelJobId": "mock-audio-..."
  }
}
```

Offsets start at zero and increase within one job file. Writers append under a
filesystem lock and flush each record. Readers validate the envelope and offset
sequence and may start at a selected offset. `state.json`, not the event log,
remains the canonical current state. No broker, consumer checkpoint, or event
processor is part of this increment.

## Atomic persistence rule

Write a new state or artifact to a temporary file in the same filesystem, flush
and close it, validate it, and replace the canonical path atomically. Advance
job state only after the artifact it depends on has been installed successfully.
