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
`mom.v1alpha1.document` schema is still open by backend decision TD-024.

## Component-to-API map

| UI surface | Frontend operation | Backend contract | Alignment status |
|---|---|---|---|
| Upload screen | `createJob` | `POST /api/v1/jobs` | Aligned for multipart field `audio`. Audio-format details remain provisional. |
| Recording screen | Reuses `createJob` | `POST /api/v1/jobs` | Transport aligns; product scope and browser codec/extension coverage need review. |
| Processing screen and sidebar | `getJob` every 2 seconds | `GET /api/v1/jobs/{job_id}` | Status and artifact availability align. Mock now includes `reviewContextAvailable`. |
| Processing transcript preview | `getTranscript` | `GET /api/v1/jobs/{job_id}/transcript` | Aligned to structured `transcription.v1alpha1` JSON. |
| Review transcript pane | `getTranscript` | `GET /api/v1/jobs/{job_id}/transcript` | Aligned through the structured segment mapper. |
| Review minutes pane | `getMom` then `parseMom(result.document)` | `GET /api/v1/jobs/{job_id}/mom` | Envelope aligned; detailed document shape remains explicitly provisional. |
| AI confidence card | `getReviewContext` | `GET /api/v1/jobs/{job_id}/review-context` | Aligned to backend transcript and MoM confidence. |
| Server indicator | `health` | `GET /health` | Route aligns, but backend health is currently a dummy liveness response and does not imply worker/model readiness. |
| Failure screen | `retryJob` | `POST /api/v1/jobs/{job_id}/retry` | Route exists, but backend behavior is a dummy and does not actually recover a job. |
| Recipient picker | Static `directory.ts` | No directory endpoint | Frontend-only prototype behavior. |
| Export/share | `exportMom` | No endpoint | Unsupported by the pipeline contract. Local browser download exists separately. |
| Discard/delete | `discardJob` | No endpoint | Unsupported and conflicts with the pipeline's accepted no-deletion decision. |

## Resolution and deferral register

### B1 — Structured transcript response — resolved

Both frontend modes now consume `transcription.v1alpha1` JSON. The mapper keeps
segment IDs, boundaries, speaker IDs, languages, text, and confidence; it uses
the backend display name when present and otherwise shows the anonymous speaker
ID. The backend's derived internal `transcript.txt` handoff is unchanged.

### B2 — Versioned MoM envelope and open document schema — integrated, schema open

The frontend now consumes the `mom.v1alpha1` envelope and passes its `document`
to the review parser. The backend mock content uses the current provisional
review-document shape. Backend validation remains unchanged and the definitive
document schema remains open under TD-024.

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

### B5 — Export, approval, and local delivery — deferred, unchanged

The UI posts to an endpoint absent from OpenAPI, suppresses failures, and can
still show that the minutes were shared. The approval and local-delivery API
contracts are not implemented yet.

No implementation change was made. The absent backend capability remains
explicitly not implemented.

### B6 — Discard and purge claims — open question, untouched

The UI calls an absent `DELETE` endpoint, suppresses failure, resets local
state, and then says data was purged. The backend deliberately does not support
job deletion in the current MVP.

The team must decide retention/deletion behavior. No frontend or backend change
was made: deletion was neither implemented nor removed.

### B7 — Recipient source — deferred, unchanged

The recipient picker uses hard-coded `@medpark.md` people. No local directory
contract or confirmed distribution-list source exists.

No implementation change was made. The existing local demo directory remains,
and no external directory or SMTP service was introduced.

### B8 — Product/schema coverage — frontend mismatches resolved

The provisional frontend vocabulary now includes `operational` and `crisis`,
and upload validation mirrors the backend's current extension allowlist. The
recording screen remains optional UI and does not make meeting type a required
input.

## Verification at this boundary

- Dependency installation completed.
- `npm run typecheck` passes after synchronizing OpenAPI.
- `npm run build` passes.
- All 37 pipeline tests pass.
- Vite serves the index and transformed React entry module on
  `http://127.0.0.1:3100`.
- A second Vite start fails on the occupied port, confirming `strictPort`.
- An isolated live upload reached `AWAITING_REVIEW`; transcript, MoM, and review
  context were returned through both the pipeline API and Vite proxy using the
  expected versioned JSON contracts.
- Visual browser interaction was not completed because no in-app or connected
  browser was available in the execution environment.
- Retry, export/delivery, deletion, and directory integration were intentionally
  not exercised because they remain deferred, absent, or open as recorded above.
