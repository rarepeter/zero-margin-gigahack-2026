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
  "schemaVersion": 1,
  "jobId": "01J...",
  "status": "TRANSCRIBING",
  "stage": "audio_processing",
  "createdAt": "2026-09-26T12:00:00Z",
  "updatedAt": "2026-09-26T12:01:12Z",
  "attempts": {
    "transcription": 1,
    "momGeneration": 0
  },
  "modelJobs": {
    "audio": "audio-job-123",
    "text": null
  },
  "artifacts": {
    "audio": "input/meeting.wav",
    "transcript": null,
    "mom": null
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

## Transcript artifact

The accepted MVP representation is UTF-8 plain text in spoken order.

```text
transcript/transcript.txt
```

Structured segments, timestamps, speaker identity, language labels, and
confidence values are not required in the current contract. They may be added
later through a versioned supplemental artifact without silently changing the
meaning of the plain-text file.

An empty transcript is invalid unless a later explicit contract defines how a
recording with no intelligible speech is represented.

## Draft MoM artifact

The canonical artifact is UTF-8 JSON:

```text
mom/draft.json
```

The definitive content schema will be agreed later with the text-model and
frontend workstreams. Until then, the pipeline must treat the model-produced MoM
as a JSON document, validate that it is syntactically valid, and retain schema
version information when provided.

A non-binding envelope for integration experiments is:

```json
{
  "schemaVersion": "draft",
  "jobId": "01J...",
  "document": {}
}
```

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
