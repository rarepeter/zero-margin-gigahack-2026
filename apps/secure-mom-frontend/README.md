# Secure MOM — frontend (v1.0)

A React build of the Secure MOM review interface. It has one page and talks only to the **local Python REST server**. It does not call any external host at runtime: the fonts are self-hosted and there is no CDN or analytics.

Stack: Vite 7, React 19, TypeScript 5.9 and plain CSS. There is no UI framework, router or state library.

## Run

```bash
cd apps/secure-mom-frontend
npm ci
npm run dev        # http://127.0.0.1:3100 — MOCK mode, uses example data, no backend needed
npm run dev:live   # http://127.0.0.1:3100 — LIVE mode, proxies to the Python server
npm run build      # production build (mock by default; `npx vite build --mode live` for the real server) in dist/ (serve it from the Python server or any static host)
```

Development port map:

| Process | Default address |
|---|---|
| Frontend (Vite) | `http://127.0.0.1:3100` |
| Pipeline API | `http://127.0.0.1:8000` |
| Audio-processing service | `http://127.0.0.1:8101` |
| Text/MoM service | `http://127.0.0.1:8102` |

The pipeline worker does not listen on a port. Callback URLs on port `8000`
target the pipeline API and do not represent another server binding. Vite uses
`strictPort`, so a real collision fails visibly instead of silently selecting a
different port.

The mode is chosen by the npm script, so no `.env` file is needed. An optional `.env` / `.env.local` can override the values below (see `env.example`):

| Variable | Default | Meaning |
|---|---|---|
| `VITE_DEV_HOST` | `127.0.0.1` | Local interface used by the Vite dev and preview servers. |
| `VITE_DEV_PORT` | `3100` | Frontend dev and preview port. |
| `VITE_API_MODE` | `mock` | `mock` uses `src/api/mock.ts` with example data. `live` uses `src/api/live.ts` with real `fetch`. |
| `VITE_API_TARGET` | `http://127.0.0.1:8000` | Where the dev proxy sends `/api`, `/health` and `/ready`. |

In dev, the Vite proxy puts the UI and the API on one origin, so the backend needs **no CORS setup**. In production, serve `dist/` from the same origin as the API (for example with FastAPI `StaticFiles`) and the UI will work as is.

Mock-mode shortcuts:

- `http://127.0.0.1:3100/?demo=review` opens the review screen directly.
- Uploading a file whose name contains `fail` demonstrates the FAILED state and Retry.
- An orange "Example data" badge in the top bar shows that you are in mock mode.

## Where the backend plugs in

All server access goes through a single interface, `SecureMomApi`, in `src/api/types.ts`.

| UI action | Method | Endpoint | Current 0.5.0 alignment |
|---|---|---|---|
| Upload / record | `createJob` | `POST /api/v1/jobs` (multipart field `audio`) | ✅ |
| Poll progress (every 2 s) | `getJob` | `GET /api/v1/jobs/{id}` | ✅ |
| Transcript | `getTranscript` | `GET /api/v1/jobs/{id}/transcript` (`transcription.v1alpha1` JSON) | ✅ |
| Minutes | `getMom` | `GET /api/v1/jobs/{id}/mom` (`mom.v1alpha1` envelope) | ✅; detailed document shape remains provisional |
| Review metadata/confidence | `getReviewContext` | `GET /api/v1/jobs/{id}/review-context` | ✅ |
| Retry after failure | `retryJob` | `POST /api/v1/jobs/{id}/retry` | ⚠️ **B4** — route is a backend dummy |
| "Local server: Online" (every 15 s) | `health` | `GET /health` | ✅ liveness only; not full readiness |
| Export (after review) | `exportMom` | No pipeline endpoint | ❌ **B5** |
| Discard | `discardJob` | No pipeline endpoint | ❌ **B6** |
| Recipient directory | (local stub) | `src/data/directory.ts` → e.g. `GET /api/v1/directory?q=` | ❌ **TODO** |

See [API_ALIGNMENT.md](API_ALIGNMENT.md) for the component map, evidence, and
numbered blocker queue. Blockers are intentionally being handled incrementally.

Behaviour while these endpoints are missing:

- **Export:** the UI calls the endpoint, logs any failure, and still finishes. The doctor can always download the reviewed minutes locally as PDF (print) or JSON.
- **Discard:** same pattern as export: the call is attempted, failures are logged, and the flow continues.
- **Confidence:** transcript and MoM confidence come from the backend review context.
- **Recipients:** only `@medpark.md` addresses are accepted. Clinical cases (`meeting_type: patient_case`) are download-only, with no recipients.

The backend-generated OpenAPI document is the source of truth. After it changes,
sync the frontend snapshot and regenerate the types:

```bash
npm run sync:api   # pipeline OpenAPI → frontend snapshot → schema.d.ts
```

### Status mapping

| Backend `status` | Sidebar sub-step |
|---|---|
| `QUEUED` | File received |
| `TRANSCRIBING` | Transcription RO · RU · EN |
| `GENERATING_MOM` | Generating the minutes |
| `AWAITING_REVIEW` | Ready for review, then the Review screen opens |
| `FAILED` | Failed screen (Retry only if `error.retryable`) |

The API returns no progress percentage. The progress bar uses the status as a floor and creeps slowly within each phase.

### Transcript format

Live and mock modes both consume `transcription.v1alpha1` JSON. The UI maps
structured segments such as:

```json
{
  "id": "segment-1",
  "startMs": 0,
  "endMs": 4200,
  "speakerId": "speaker-1",
  "languages": ["ro"],
  "text": "Bună ziua.",
  "confidence": 0.94
}
```

The mapper preserves IDs, millisecond boundaries, language codes, anonymous
speaker IDs, text, and confidence. The red-word → transcript jump uses
`evidence.t` first, then falls back to `evidence.segment` (0-based segment
index).

### Red words = `flags` in the MoM

Every `flags[]` entry on a decision, action or finding becomes a red word, and export stays locked until all `blocking: true` flags are resolved. The first `candidates[]` value is offered as the one-click answer, and the doctor can also type a value. On export, `applyResolutions()` in `src/domain/mom.ts` writes the chosen values back (`status`, `owner`, `deadline.resolved`, or text) and removes the resolved flags.

## Structure

```
src/
  api/          types.ts (contract) · live.ts (fetch) · mock.ts + examples/ · schema.d.ts (generated)
  domain/       mom.ts (MoM types, issues, applyResolutions) · transcript.ts (parser)
  state/        store.tsx — one useReducer store: screens, polling, review state
  screens/      Upload · Recording · Processing · Failed · Review · Done
  components/   layout/ (Sidebar, SecurityBar, AiConfidence) · review/ (TranscriptPane, SummaryPane, FixWord, BottomBar, RecipientPicker)
  i18n/         RO / RU / EN copy
  styles/       app.css (prototype stylesheet, verbatim) · react.css (React-specific additions)
  lib/          exportDoc.ts (local PDF/JSON) · format.ts
```

## Security constraints (hackathon rules)

- No external AI API, cloud service or external SMTP at runtime. The UI only calls same-origin endpoints.
- Audio files are never committed to git. Keep `*.m4a`, `*.mp3` and `*.wav` in the root `.gitignore`.
- Clinical-case minutes are download-only.
