# Pipeline artifact specifications

Status: accepted storage direction; individual shapes are provisional  
Last updated: 27 September 2026

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
    approved.json
  delivery/
    result.json
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
    "email": "elena.popescu@medpark.test"
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

The processing flow stops at `AWAITING_REVIEW / review_ready` until a reviewer
submits approval. Approval with no accepted recipients reaches
`COMPLETED / approved`; approval with accepted recipients reaches
`COMPLETED / delivered` only after local SMTP accepts the message. A delivery
failure is `FAILED / delivery_failed` while the approved artifact remains
available.

## Audio artifact

- The uploaded bytes are preserved without modification by the pipeline.
- The server controls the stored filename and never trusts a client path.
- Original filename, media type, and byte count are recorded as metadata, but
  must not be used to resolve filesystem locations.
- Supported formats and maximum size are not yet agreed.

## Transcription artifacts

The audio-to-text service pushes a validated schema-version-1 transcription JSON
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

The schema-version-1 `document` content schema is agreed and validated by the pipeline.
It contains the existing portal header, summary, decisions, actions, findings,
topics, risks, open questions, and optional patient grouping. The canonical
schema is generated in `pipeline.openapi.json` as `MomDocument`.

A valid development-mock envelope is:

```json
{
  "schemaVersion": 1,
  "quality": {
    "momConfidence": 0.86,
    "confidenceScale": "ZERO_TO_ONE"
  },
  "document": {
    "header": {
      "subject": "Local pipeline demo validation",
      "meeting_type": "other",
      "meeting_type_confidence": "high",
      "date": "2026-09-27",
      "date_source": "recording",
      "languages": {"en": 1.0},
      "participants_mentioned": [
        {"name": "integration team", "role": null, "role_stated": false}
      ]
    },
    "summary": "Participants agreed to validate the local pipeline demo, and the integration team will verify the review screen by 27 September 2026. 1 decision, 1 action.",
    "decisions": [
      {
        "id": "D1",
        "text": "Validate the local pipeline demo.",
        "status": "decided",
        "evidence": {
          "quote": "Participants agreed to validate the local pipeline demo.",
          "lang": "en",
          "segment_id": "segment-1",
          "segment": 0,
          "t": "00:00:00",
          "speaker": "speaker-1"
        },
        "flags": []
      }
    ],
    "actions": [
      {
        "id": "A1",
        "text": "Verify the review screen",
        "decision_ids": ["D1"],
        "owner": "integration team",
        "deadline": {
          "spoken": "by 27 September 2026",
          "resolved": "2026-09-27"
        },
        "evidence": {
          "quote": "The integration team will verify the review screen by 27 September 2026.",
          "lang": "en",
          "segment_id": "segment-1",
          "segment": 0,
          "t": "00:00:00",
          "speaker": "speaker-1"
        },
        "flags": []
      }
    ],
    "findings": [],
    "topics": [],
    "risks": [],
    "open_questions": []
  }
}
```

The mock sends this object to the pipeline callback after a configurable
five-second delay. The pipeline validates the versioned envelope and atomically
persists the original bytes before advancing to `AWAITING_REVIEW`.

The development mock uses a richer multilingual review document with anonymous
participants, decisions, actions, findings, and review flags. The pipeline
validates the full document and verifies that every `segment_id` exists in the
persisted transcription. `segment` and `t` are legacy display fallbacks only.

## Review-context artifact

`review/context.json` is created with the MoM checkpoint. It contains compact
portal metadata: the existing workflow state, submitter context, original file
metadata, processing timing, audio duration, language and speaker aggregates,
transcript confidence, MoM confidence, and API links for the two large content
artifacts. It deliberately excludes transcript segments and MoM document
content.

The persisted artifact retains the submitter email for authorized local
delivery. The browser-facing response projects that field out.
All three confidence values are nullable because no aggregation rule or model
confidence calibration is assumed. There are no recommendation annotations,
review-issue counts, or export-blocking fields in this contract.

## Approved MoM and delivery-result artifacts

`mom/approved.json` is the immutable schema-version-1 approval record. It
contains the reviewed `document`, the server approval timestamp, and both
recipient outcomes:

```json
{
  "schemaVersion": 1,
  "jobId": "01J...",
  "approvedAt": "2026-09-27T09:15:00Z",
  "document": {},
  "recipients": ["ana.ionescu@medpark.test"],
  "skippedRecipients": ["outside@example.com", "not-an-email"]
}
```

`recipients` contains normalized, de-duplicated addresses whose domains match
`PIPELINE_MAIL_ALLOWED_RECIPIENT_DOMAINS`. `skippedRecipients` preserves the
submitted malformed or non-allowlisted values for UI feedback. These fields are
required: the pre-launch prototype intentionally provides no compatibility
reader for older approved artifacts.

When delivery is attempted, `delivery/result.json` records metadata but not the
message body:

```json
{
  "schemaVersion": 1,
  "jobId": "01J...",
  "status": "accepted",
  "messageId": "<secure-mom-01J...@medpark.test>",
  "attemptedAt": "2026-09-27T09:15:01Z",
  "recipientCount": 1,
  "errorCode": null
}
```

On an SMTP failure, `status` is `failed` and `errorCode` contains only the safe
adapter error code. Repeating the identical approval request may replace this
result with a later accepted attempt; it never replaces `mom/approved.json`.

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
