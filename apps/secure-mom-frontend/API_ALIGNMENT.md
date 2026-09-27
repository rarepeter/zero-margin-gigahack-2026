# Frontend/backend alignment status

Status: implemented contract alignment with explicitly deferred capabilities.

This document records the agreed frontend/backend boundary. It does not turn
the provisional API or MoM document shape into final requirements.

## Local development ports

| Process | Default address | Notes |
|---|---|---|
| Frontend (Vite) | `http://127.0.0.1:3100` | Fails if the port is occupied. |
| Pipeline API | `http://127.0.0.1:8000` | Receives browser API traffic through the Vite proxy. |
| Audio-processing service | `http://127.0.0.1:8101` | Independently started local service. |
| Text/MoM service | `http://127.0.0.1:8102` | Independently started local service. |
| Pipeline worker | No port | Advances filesystem-backed jobs. |

Pipeline callback URLs on port `8000` point to the pipeline API. They do not
bind additional processes to that port.

## Contract source

The pipeline-generated `apps/pipeline/docs/openapi/pipeline.openapi.json` is the
source of truth. From this directory, `npm run sync:api` copies that document to
`openapi/openapi.json` and regenerates `src/api/schema.d.ts`.

The synchronized API is currently `0.5.0-provisional`. The detailed
schema-version-1 MoM document is now validated by the backend; its
snake_case field naming remains the current portal contract.

## Component-to-API map

| UI surface | Frontend operation | Backend contract | Alignment status |
|---|---|---|---|
| Upload screen | `createJob` | `POST /api/v1/jobs` | Aligned for multipart field `audio`. Audio-format details remain provisional. |
| Recording screen | Reuses `createJob` | `POST /api/v1/jobs` | Transport aligns; product scope and browser codec/extension coverage need review. |
| Processing screen and sidebar | `getJob` every 2 seconds | `GET /api/v1/jobs/{job_id}` | Status and artifact availability align. Mock now includes `reviewContextAvailable`. |
| Processing transcript preview | `getTranscript` | `GET /api/v1/jobs/{job_id}/transcript` | Aligned to structured transcription JSON with `schemaVersion: 1`. |
| Review transcript pane | `getTranscript` | `GET /api/v1/jobs/{job_id}/transcript` | Aligned through the structured segment mapper. |
| Review minutes pane | `getMom` then `parseMom(result.document)` | `GET /api/v1/jobs/{job_id}/mom` | Envelope and detailed review document are validated; evidence uses stable segment IDs. |
| AI confidence card | `getReviewContext` | `GET /api/v1/jobs/{job_id}/review-context` | Aligned to backend transcript and MoM confidence. |
| Server indicator | `health` | `GET /health` | Route aligns, but backend health is currently a dummy liveness response and does not imply worker/model readiness. |
| Failure screen | `retryJob` | `POST /api/v1/jobs/{job_id}/retry` | Route exists, but backend behavior is a dummy and does not actually recover a job. |
| Recipient picker | `searchDirectory` with mock-only fallback | `GET /api/v1/directory?q=` | Live mode uses the server-owned local demo directory; immutable person IDs remain deferred. |
| Approve, optionally deliver | `approveMom` | `POST /api/v1/jobs/{job_id}/approve` | Same request with or without recipients; backend skips invalid/non-allowlisted values and sends through local SMTP only when accepted recipients remain. |
| Reload approved MoM | `getApprovedMom` | `GET /api/v1/jobs/{job_id}/approved-mom` | Reads the persisted approved document. |
| Discard/delete | `discardJob` | No endpoint | Unsupported and conflicts with the pipeline's accepted no-deletion decision. |

## Resolution and deferral register

### B1 — Structured transcript response — resolved

Both frontend modes now consume transcription JSON with `schemaVersion: 1`. The mapper keeps
segment IDs, boundaries, speaker IDs, languages, text, and confidence; it uses
the backend display name when present and otherwise shows the anonymous speaker
ID. The backend's derived internal `transcript.txt` handoff is unchanged.

### B2 — Versioned MoM envelope and review document schema — resolved

The frontend consumes the schema-version-1 MoM envelope and passes its `document` to
the review parser. The backend validates the full schema-version-1 review document and
checks every evidence `segment_id` against the persisted transcription.

### B3 — Review context and confidence — resolved

The frontend loads review context with the transcript and MoM, uses its quality
fields without rewriting them after human review, and uses its duration,
languages, speakers, source filename, and processing elapsed time in existing
UI fields.

### B4 — Retry behavior — deferred, unchanged

The frontend presents retry as functional. The backend route returns a dummy
success response and does not transition the failed job.

No implementation change was made. The route remains a provisional backend
dummy.

### B5 — Approval and conditional local delivery implemented

The UI posts the edited document to the approval endpoint and shows completion
only after success. An empty or fully skipped recipient list produces no email.
If accepted recipients remain, the same request succeeds only after local SMTP
acceptance. The pipeline persists the approved document before attempting
delivery and exposes it through the read endpoint. SMTP failure leaves the UI
on Review with edits and recipients locked so the same request can retry. The
current PDF button still uses browser print.

### B6 — Discard and purge claims — open question, untouched

The UI calls an absent `DELETE` endpoint, suppresses failure, resets local
state, and then says data was purged. The backend deliberately does not support
job deletion in the current MVP.

The team must decide retention/deletion behavior. No frontend or backend change
was made: deletion was neither implemented nor removed.

### B7 — Local participant and recipient directory — resolved for the demo

The participant and recipient pickers query the server-owned
`GET /api/v1/directory?q=` endpoint. Its current `@medpark.test` data is a small
static demo list and does not call an external directory.

Participant names are saved through `PUT /api/v1/jobs/{jobId}/participants`.
Unmatched free-text names are accepted and persisted as a separate review
artifact. The backend still independently enforces its configured email-domain
allowlist and softly reports skipped recipient addresses. Delivery uses only
the loopback SMTP adapter; no external directory or SMTP service is used.

### B9 — Inferred meeting type must not control delivery — resolved in the UI

The portal no longer treats `patient_case` as download-only. Delivery policy is
a backend decision to be added with the directory and approval contract; the
current inferred meeting type only affects wording.

### B8 — Product/schema coverage — frontend mismatches resolved

The provisional frontend vocabulary now includes `operational` and `crisis`,
and upload validation mirrors the backend's current extension allowlist. The
recording screen remains optional UI and does not make meeting type a required
input.

## Verification at this boundary

- Dependency installation completed.
- `npm run typecheck` passes after synchronizing OpenAPI.
- `npm run build` passes.
- All 78 pipeline tests pass, including restart-safe draft-notification
  coverage.
- Vite serves the index and transformed React entry module on
  `http://127.0.0.1:3100`.
- A second Vite start fails on the occupied port, confirming `strictPort`.
- An isolated live upload reached `AWAITING_REVIEW`; transcript, MoM, and review
  context were returned through both the pipeline API and Vite proxy using the
  expected versioned JSON contracts.
- Visual browser interaction was not completed because no in-app or connected
  browser was available in the execution environment.
- Notification and delivery paths are covered with recording adapters in
  pipeline tests; live Mailpit capture, deletion, institutional directory
  integration, and a server-rendered attachment remain deferred or absent as
  recorded above.
