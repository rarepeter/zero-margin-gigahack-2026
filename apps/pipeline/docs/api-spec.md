# Draft pipeline HTTP API

Status: job creation and status implemented provisionally; remaining routes are not finalized
Last updated: 26 September 2026

## Conventions

- Proposed base path: `/api/v1`.
- Responses are JSON unless an endpoint explicitly returns plain transcript
  text.
- Job IDs are opaque, server-generated identifiers.
- Times use UTC RFC 3339 strings.
- Error responses use a stable machine-readable code plus a human-readable
  message.
- Creating a job is the only proposed multipart request because a browser must
  transfer the recording bytes. Persisted results use JSON, except the accepted
  plain-text transcript artifact.

## Proposed endpoints

### `POST /api/v1/jobs`

Accept one audio file in the `audio` multipart field. The implementation streams
and atomically persists the file, creates a queued job, and returns without
waiting for ML processing.

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
    "momAvailable": false
  },
  "error": null
}
```

The frontend may poll this endpoint every one or two seconds initially. The
interval should become configuration rather than a hard-coded contract.

This endpoint now reads the persisted job state. Unknown IDs return `404`.

### `GET /api/v1/jobs/{jobId}/transcript`

Return the accepted plain-text transcript after transcription succeeds.

Proposed content type: `text/plain; charset=utf-8`.

Before the artifact exists, return a structured JSON error with an appropriate
HTTP status rather than an empty transcript.

### `GET /api/v1/jobs/{jobId}/mom`

Return the persisted draft MoM JSON after text processing succeeds. The exact
schema is intentionally not final; see `artifact-schemas.md`.

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
