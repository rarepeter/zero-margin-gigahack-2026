# Draft pipeline HTTP API

Status: implemented provisional API; remaining routes are not finalized
Last updated: 27 September 2026

## Conventions

- Proposed base path: `/api/v1`.
- Responses are JSON.
- Job IDs are opaque, server-generated identifiers.
- Times use UTC RFC 3339 strings.
- Error responses use a stable machine-readable code plus a human-readable
  message.
- Creating a job is the only proposed multipart request because a browser must
  transfer the recording bytes. Persisted ML results use versioned JSON; the
  pipeline derives an internal plain-text transcript for the MoM service.

## Proposed endpoints

### `POST /api/v1/jobs`

Accept one audio file in the `audio` multipart field. The implementation streams
and atomically persists the file, creates a queued job, and returns without
waiting for ML processing. Authentication and SSO are outside this API. For the
offline MVP, submitter identity is an assumed local value supplied through
`PIPELINE_DEMO_SUBMITTER_*` process configuration, not request headers or form
fields.

Proposed response: `202 Accepted`

```json
{
  "jobId": "01J...",
  "status": "QUEUED",
  "stage": "queued",
  "createdAt": "2026-09-26T12:00:00Z"
}
```

The current provisional implementation accepts `.mp3`, `.wav`, `.m4a`, `.aac`,
`.flac`, `.ogg`, `.opus`, `.webm`, and `.mp4` up to 300 MiB. MIME type is
advisory. The pipeline preserves bytes and does not decode or transcode audio.
Unsupported extensions return `415`; empty files return `400`; files over the
limit return `413`.

### `GET /api/v1/jobs/{jobId}`

Return current state suitable for frontend polling.

```json
{
  "jobId": "01J...",
  "status": "TRANSCRIBING",
  "stage": "audio_processing",
  "createdAt": "2026-09-26T12:00:00Z",
  "updatedAt": "2026-09-26T12:01:12Z",
  "artifacts": {
    "transcriptAvailable": false,
    "momAvailable": false,
    "reviewContextAvailable": false
  },
  "error": null
}
```

The frontend may poll this endpoint every one or two seconds initially. The
interval should become configuration rather than a hard-coded contract.

This endpoint now reads the persisted job state. Unknown IDs return `404`.

### `POST /api/v1/integrations/audio/jobs/{jobId}/transcription`

Local integration endpoint used by the audio-to-text service after it finishes
processing. Send a schema-version-1 transcription JSON object and the previously
issued audio model job ID in `X-Audio-Model-Job-Id`. The object contains the
complete transcript text, display segments, duration, language proportions,
speakers, and transcript confidence. Its `jobId` must match the route. The
default maximum is 10 MiB and is configurable. The authoritative structure is
also published in `openapi/audio-processing.openapi.json`.

The first durable receipt returns `202 Accepted`:

```json
{
  "jobId": "01J...",
  "status": "TRANSCRIBING",
  "stage": "transcription_received",
  "replayed": false
}
```

An identical replay returns `200` with `replayed: true`. A different body for an
already persisted transcription, a mismatched job/model ID, or a job that is not
expecting a transcription returns `409`. Empty, invalid, oversized, and
non-JSON documents return `400`, `413`, and `415` as applicable. This is an ML
integration route, not a frontend operation.

### `POST /api/v1/integrations/text/jobs/{jobId}/mom`

Local integration endpoint used by the text/MoM service after it finishes.
Send a schema-version-1 MoM JSON object as the raw `application/json` body and the
previously issued text model job ID in `X-Text-Model-Job-Id`. The envelope
requires `quality.momConfidence` on the `ZERO_TO_ONE` scale while the detailed
`document` content schema remains open. The default maximum is 10 MiB and is
configurable. The authoritative envelope is also published in
`openapi/text-processing.openapi.json`.

The first durable receipt returns `202 Accepted`:

```json
{
  "jobId": "01J...",
  "status": "AWAITING_REVIEW",
  "stage": "review_ready",
  "replayed": false
}
```

An identical replay returns `200`; a conflicting body, mismatched model job ID,
or wrong job state returns `409`. Invalid JSON returns `400`, an unsupported
media type returns `415`, and an oversized document returns `413`.

### `GET /api/v1/jobs/{jobId}/transcript`

Return the separately persisted schema-version-1 transcription JSON result. This keeps
the potentially large segment list out of job-status and review-context reads.
The derived `transcript.txt` remains an internal input to the text/MoM service.

Before the artifact exists, return `409 ARTIFACT_NOT_READY` rather than an empty
transcript.

### `GET /api/v1/jobs/{jobId}/mom`

Return the persisted draft MoM JSON after text processing succeeds. The
schema-version-1 MoM envelope, quality fields, and the detailed review `document`
are validated. Every MoM evidence record must reference a valid transcript
`segment_id`; rendered timestamps and positional indexes are not authoritative.
See `artifact-schemas.md`.

Before the artifact exists, this endpoint returns `409 ARTIFACT_NOT_READY`.

### `GET /api/v1/jobs/{jobId}/review-context`

Return compact schema-version-1 review-context metadata for the review page. It
contains the existing workflow state, source-recording and processing metadata,
language/speaker aggregates, transcript and MoM confidence scores, and links to
the separately loaded transcript and MoM resources. It does not contain either
large content artifact, red-word recommendations, issue counters, approval
state, or export gating.

The persisted server-side artifact retains the submitter email for authorized
local delivery. The browser response intentionally omits that
email. Confidence values are nullable and are copied from the accepted audio
and text artifacts without UI-side calculation. `recordedAt`, when supplied by
the audio service from container metadata, is exposed separately from the job
upload time; filesystem creation time is never treated as the meeting date.
Before the context exists, return `409 ARTIFACT_NOT_READY`.

The `processing` object also exposes `audioStageMs` and `momStageMs` when
available. They measure elapsed time from each local model submission to its
validated callback, including service and callback overhead. Their sum is
distinct from the existing job-creation-to-review `elapsedMs`.

### `POST /api/v1/jobs/{jobId}/approve`

Accept `{ "schemaVersion": 1, "document": <edited MoM>, "recipients": [...] }`
while the job is `AWAITING_REVIEW`. The same endpoint covers both outcomes:

- after normalization, an empty accepted-recipient list persists
  `mom/approved.json` and completes at `COMPLETED / approved` without SMTP;
- one or more accepted recipients persist the same immutable approval and then
  deliver its composed message through the configured local SMTP adapter. The
  job reaches `COMPLETED / delivered` only after SMTP accepts the message.

Recipient values that are malformed or outside
`PIPELINE_MAIL_ALLOWED_RECIPIENT_DOMAINS` are returned in
`skippedRecipients`; they do not reject or block approval. Accepted addresses
are normalized and de-duplicated. The sender always comes from the stored,
server-authorized demo submitter identity and is never accepted from the
browser.

The approved artifact records the exact accepted and skipped recipient lists.
An identical retry returns the same completed approval without sending a
duplicate message. If local SMTP fails, `mom/approved.json` is preserved,
`delivery/result.json` records safe failure metadata, and the job becomes
`FAILED / delivery_failed`; repeating the identical approval request retries
delivery. A different document or recipient selection conflicts. This is the
only approval/delivery endpoint; there is no compatibility endpoint or legacy
approved-artifact reader.

### `GET /api/v1/jobs/{jobId}/approved-mom`

Return the persisted approved document after approval. Before approval, return
`409 APPROVAL_NOT_READY`. The draft MoM endpoint remains separate.

### `POST /api/v1/jobs/{jobId}/retry`

Provisional manual recovery operation. Queue the job from its last valid
checkpoint when the current state is `FAILED`. The exact response and retry
eligibility rules remain open.

### `GET /health`

Report whether the API process is alive. This must not imply that the worker or
ML services are ready.

### `GET /ready`

Proposed readiness report covering writable job storage, worker visibility, and
the configured health of both ML endpoints.

```json
{
  "ready": true,
  "checks": {
    "storage": "ok",
    "worker": "ok",
    "audioService": "ok",
    "textService": "ok"
  }
}
```

## Explicitly excluded endpoints

The pipeline API does not provide:

- MoM edit or update endpoints;
- ODF or DOCX download endpoints;
- cancellation;
- job deletion;
- an external SMTP or cloud-mail endpoint; or
- user authentication.

## Draft error envelope

```json
{
  "error": {
    "code": "ARTIFACT_NOT_READY",
    "message": "The draft MoM is not available yet.",
    "retryable": true
  }
}
```

Do not expose stack traces, secrets, or arbitrary local paths in public error
responses. The final list of error codes remains open.
