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
    source.json
    transcript.txt
  mom/
    draft.json
  review/
    context.json
  operations.ndjson
```

Names may change during implementation, but every job remains self-contained.
Runtime job directories and all their contents must be ignored by Git.

## `state.json`

The state file is pipeline-owned. A provisional shape is:

```json
{
  "schemaVersion": 3,
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
    "transcript": "transcript/source.json",
    "transcriptionSource": {
      "path": "transcript/source.json",
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
    },
    "reviewContext": {
      "path": "review/context.json",
      "mediaType": "application/json",
      "byteCount": 960,
      "sha256": "<64 lowercase hexadecimal characters>"
    }
  },
  "submittedBy": {
    "userId": "sso-user-1842",
    "displayName": "Elena Popescu",
    "email": "elena.popescu@medpark.md"
  },
  "sourceRecording": {
    "originalFileName": "meeting.m4a",
    "mediaType": "audio/mp4",
    "sizeBytes": 733645
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
- Original filename, media type, and byte count are recorded as metadata, but
  must not be used to resolve filesystem locations.
- Supported formats and maximum size are not yet agreed.

## Transcription artifacts

The audio-to-text service pushes a validated `transcription.v1alpha1` JSON
document. The pipeline atomically preserves its original bytes at:

```text
transcript/source.json
```

The structured source contains complete transcript text, display segments,
duration, languages, speakers, and transcript confidence. The transformer
extracts `transcript.text` without rewriting it and writes that value to:

```text
transcript/transcript.txt
```

The text/MoM adapter uploads this derived artifact as multipart file
`transcript.txt` with media type `text/plain; charset=utf-8`. Empty, malformed,
non-JSON, wrong-version, or structurally invalid transcription results are
rejected before a checkpoint is published. The complete structured source is
returned separately by the public transcript endpoint.

## Draft MoM artifact

The canonical artifact is UTF-8 JSON:

```text
mom/draft.json
```

The definitive `document` content schema will be agreed later with the
text-model and frontend workstreams. The surrounding envelope and its confidence
field are agreed and validated now.

A valid development-mock envelope is:

```json
{
  "schemaVersion": "mom.v1alpha1",
  "quality": {
    "momConfidence": 0.86,
    "confidenceScale": "ZERO_TO_ONE"
  },
  "document": {
    "content": "Mock Minutes of Meeting"
  }
}
```

The mock sends this object to the pipeline callback after a configurable
five-second delay. The pipeline validates the versioned envelope and atomically
persists the original bytes before advancing to `AWAITING_REVIEW`.

The `document` object does not yet define clinical, financial, administrative,
executive, operational, or crisis-meeting MoM fields.

## Review-context artifact

`review/context.json` is created with the MoM checkpoint. It contains compact
portal metadata: the existing workflow state, submitter context, original file
metadata, processing timing, audio duration, language and speaker aggregates,
transcript confidence, MoM confidence, and API links for the two large content
artifacts. It deliberately excludes transcript segments and MoM document
content.

The persisted artifact retains the submitter email for future local
notification delivery. The browser-facing response projects that field out.
`overallConfidence` is nullable because no aggregation rule has been agreed.
There are no recommendation annotations, review-issue counts, or export-blocking
fields in this contract.

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
