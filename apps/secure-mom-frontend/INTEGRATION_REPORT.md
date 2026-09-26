# Secure MOM frontend/backend integration report

Verification date: 2026-09-27 (Europe/Chisinau)

Backend contract: `0.5.0-provisional`

Canonical live test job: `c1ffce99-1a3f-418c-984f-ee9523a36ae7`

## Outcome

The current frontend and the filesystem-backed pipeline run together on the
agreed local ports. A recording uploaded through the frontend proxy completed
the full mocked pipeline in about 10.25 seconds and reached
`AWAITING_REVIEW`. The live responses were successfully projected through the
same transcript mapper and MoM parser used by the UI.

The verification uses the pipeline's deterministic, in-process audio and text
mock adapters. It verifies the portal/pipeline integration boundary, not real
speech-to-text or transcript-to-MoM inference.

## Confirmed processes, ports, and commands

| Process | Confirmed address | Startup command |
|---|---|---|
| Pipeline API | `http://127.0.0.1:8000` | `cd apps/pipeline && .venv/bin/pipeline-api` |
| Pipeline worker | No listening port | `cd apps/pipeline && .venv/bin/pipeline-worker` |
| Frontend, live mode | `http://127.0.0.1:3100` | `cd apps/secure-mom-frontend && npm run dev:live` |
| Audio service placeholder | `http://127.0.0.1:8101` | Not started; default worker uses its in-process mock adapter. |
| Text service placeholder | `http://127.0.0.1:8102` | Not started; default worker uses its in-process mock adapter. |

Final listener inspection found only the API on `127.0.0.1:8000` and Vite on
`127.0.0.1:3100`; nothing was listening on `8101` or `8102`.

## Live end-to-end evidence

The local source recording was posted as multipart field `audio` to
`http://127.0.0.1:3100/api/v1/jobs`. Vite proxied the request to the pipeline.

Observed transitions for the canonical job:

| Local time | Status | Stage |
|---|---|---|
| 01:11:25 | `QUEUED` | `queued` |
| 01:11:26 | `TRANSCRIBING` | `audio_processing` |
| 01:11:31 | `GENERATING_MOM` | `text_processing` |
| 01:11:36 | `AWAITING_REVIEW` | `review_ready` |

The final job state reported all three artifacts as available. The structured
transcript contained one segment with ID `segment-1`, 0-8000 ms boundaries,
speaker ID `speaker-1`, language `en`, and confidence `0.94`. Running the live
payload through `segmentsFromTranscription()` produced the UI projection with
timestamp `00:00:00` and language label `EN`.

The MoM response had the expected schema-version-1 envelope. Passing
`response.document` to `parseMom()` produced subject "Local pipeline demo
validation", one decision, and one action. Review context supplied transcript
confidence `0.91` and MoM confidence `0.86`; these are the values consumed by
the confidence card.

### Error behavior

| Scenario | Result |
|---|---|
| Transcript requested before completion | `409 ARTIFACT_NOT_READY`, `retryable: true` |
| Unsupported `.md` upload | `415 UNSUPPORTED_AUDIO_FORMAT`, `retryable: false` |
| Unknown job ID | `404 JOB_NOT_FOUND`, `retryable: false` |

### Browser and local-network smoke

- Frontend root returned HTTP 200 on `127.0.0.1:3100`.
- `/health` returned HTTP 200 through the Vite-to-API proxy.
- A Chrome connection to the app was observed only as
  `127.0.0.1 -> 127.0.0.1:3100`.
- The API, worker, and Vite process socket inspection showed no non-loopback
  network connection. The worker had no network sockets in the default
  in-process mock configuration.
- Runtime-source endpoint scanning found only loopback URLs and embedded
  `data:` SVG assets. Fonts are bundled into the build; there is no runtime CDN,
  analytics, external AI, external SMTP, or directory call in this path.

The in-app browser automation controller was unavailable, so pixel-level visual
inspection and automated clicks could not be performed. This is a test-harness
limitation, not an application error. The live proxy/API flow and the exact UI
mapping/parsing functions were exercised, and an active local Chrome connection
was observed, but this report does not claim visual-layout certification.

## UI-component-to-endpoint matrix

| UI component/surface | Frontend operation | Backend endpoint | Result |
|---|---|---|---|
| `UploadScreen` | `createJob` | `POST /api/v1/jobs` | Aligned and live-tested with multipart `audio`. |
| `RecordingScreen` | `createJob` | `POST /api/v1/jobs` | Transport aligned; browser recording remains outside this smoke run. |
| `ProcessingScreen` / `Sidebar` | `getJob` | `GET /api/v1/jobs/{job_id}` | Aligned; all four live transitions observed. |
| Processing transcript preview | `getTranscript` | `GET /api/v1/jobs/{job_id}/transcript` | Aligned to structured transcription JSON with `schemaVersion: 1`. |
| `TranscriptPane` | `getTranscript` + segment mapper | `GET /api/v1/jobs/{job_id}/transcript` | Structured projection live-tested. |
| `SummaryPane` / review store | `getMom` + `parseMom(result.document)` | `GET /api/v1/jobs/{job_id}/mom` | Envelope unwrapping live-tested; document schema remains provisional. |
| `AiConfidence` / review details | `getReviewContext` | `GET /api/v1/jobs/{job_id}/review-context` | Confidence and metadata aligned and live-tested. |
| Server indicator | `health` | `GET /health` | Route works; liveness is not full model/worker readiness. |
| `FailedScreen` | `retryJob` | `POST /api/v1/jobs/{job_id}/retry` | Route exists but remains a backend dummy. |
| `RecipientPicker` | Static local data | No endpoint | Frontend-only prototype behavior. |
| Review export/share | `exportMom` | No endpoint | Backend capability deferred. |
| Discard action | `discardJob` | No endpoint | Open team decision; no delete implementation or removal was made. |

## Conflict register

Resolved at the current integration boundary:

- B1: frontend mock and live modes now consume structured transcript JSON.
- B2: the frontend unwraps the versioned MoM envelope; the backend mock content
  supplies the current provisional review document.
- B3: review-context metadata and confidence are loaded with the artifacts.
- B8: UI meeting-type vocabulary and accepted upload extensions match the
  current backend contract.
- Frontend/API port collision: frontend is fixed to 3100 and the API to 8000;
  Vite uses `strictPort` and proxies `/api`, `/health`, and `/ready` to 8000.

Remaining or deliberately deferred:

- B2 remainder: the detailed MoM `document` contract is still provisional.
- B4: retry acknowledges the request but does not recover a failed job.
- B5: approval, export submission, and local mail delivery have no backend API.
- B6: retention/deletion is an open team decision. Neither side was changed to
  delete data or to claim a backend deletion capability.
- B7: recipients still come from a hard-coded local demo directory.
- Real audio and text model services are not integrated in this verification;
  the worker uses deterministic in-process mocks.
- `/ready` and `/health` remain provisional and do not establish full model or
  worker readiness.

## Verification results

| Check | Result |
|---|---|
| Backend test suite | 37 passed in 0.65 s; one upstream Starlette/httpx deprecation warning |
| Frontend typecheck | Passed: `tsc -b --noEmit` |
| Frontend production build | Passed: 66 modules transformed; JS 297.46 kB (93.57 kB gzip), CSS 77.02 kB (15.33 kB gzip) |
| Live upload and state polling | Passed |
| Structured transcript projection | Passed |
| MoM envelope unwrapping | Passed |
| Review-context confidence | Passed (`0.91` transcript, `0.86` MoM) |
| Error envelopes | Passed for 409, 415, and 404 cases |
| Localhost/runtime socket audit | Passed for application processes; no external connection observed |
| Automated visual browser inspection | Not run: no in-app browser controller available |

## Files changed for contract alignment

Backend changes are limited to mock payload content, its schema documentation,
and corresponding tests:

- `apps/pipeline/docs/artifact-schemas.md`
- `apps/pipeline/src/secure_mom_pipeline/audio_service.py`
- `apps/pipeline/src/secure_mom_pipeline/text_service.py`
- `apps/pipeline/tests/test_pipeline.py`

Frontend integration files:

- `apps/secure-mom-frontend/API_ALIGNMENT.md`
- `apps/secure-mom-frontend/INTEGRATION_REPORT.md`
- `apps/secure-mom-frontend/README.md`
- `apps/secure-mom-frontend/env.example`
- `apps/secure-mom-frontend/openapi/mom.schema.json`
- `apps/secure-mom-frontend/openapi/openapi.json`
- `apps/secure-mom-frontend/package.json`
- `apps/secure-mom-frontend/src/api/examples/transcript.example.json` (new)
- `apps/secure-mom-frontend/src/api/examples/transcript.example.txt` (removed)
- `apps/secure-mom-frontend/src/api/live.ts`
- `apps/secure-mom-frontend/src/api/mock.ts`
- `apps/secure-mom-frontend/src/api/schema.d.ts`
- `apps/secure-mom-frontend/src/api/types.ts`
- `apps/secure-mom-frontend/src/components/layout/AiConfidence.tsx`
- `apps/secure-mom-frontend/src/components/review/TranscriptPane.tsx`
- `apps/secure-mom-frontend/src/domain/mom.ts`
- `apps/secure-mom-frontend/src/domain/transcript.ts`
- `apps/secure-mom-frontend/src/i18n/index.ts`
- `apps/secure-mom-frontend/src/screens/DoneScreen.tsx`
- `apps/secure-mom-frontend/src/screens/UploadScreen.tsx`
- `apps/secure-mom-frontend/src/state/store.tsx`
- `apps/secure-mom-frontend/vite.config.ts`

Other pre-existing dirty worktree files were left unchanged by this integration
work.
