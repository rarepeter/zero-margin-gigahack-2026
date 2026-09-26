# Draft pipeline HTTP API

Status: job creation and status implemented provisionally; remaining routes are not finalized
Last updated: 26 September 2026

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
processing. Send a `transcription.v1alpha1` JSON object and the previously
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
Send a `mom.v1alpha1` JSON object as the raw `application/json` body and the
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

Return the separately persisted `transcription.v1alpha1` JSON result. This keeps
the potentially large segment list out of job-status and review-context reads.
The derived `transcript.txt` remains an internal input to the text/MoM service.

Before the artifact exists, return `409 ARTIFACT_NOT_READY` rather than an empty
transcript.

### `GET /api/v1/jobs/{jobId}/mom`

Return the persisted draft MoM JSON after text processing succeeds. The
`mom.v1alpha1` envelope and quality fields are validated, while the detailed
`document` schema remains open; see `artifact-schemas.md`.

Before the artifact exists, this endpoint returns `409 ARTIFACT_NOT_READY`.

### `GET /api/v1/jobs/{jobId}/review-context`

Return compact `review-context.v1alpha1` metadata for the review page. It
contains the existing workflow state, source-recording and processing metadata,
language/speaker aggregates, transcript and MoM confidence scores, and links to
the separately loaded transcript and MoM resources. It does not contain either
large content artifact, red-word recommendations, issue counters, approval
state, or export gating.

The persisted server-side artifact retains the submitter email for a future
local notification component. The browser response intentionally omits that
email. Before the context exists, return `409 ARTIFACT_NOT_READY`.

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

The initial pipeline API does not provide:

- MoM edit or update endpoints;
- approval endpoints;
- ODF or DOCX download endpoints;
- cancellation;
- job deletion;
- SMTP delivery; or
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
