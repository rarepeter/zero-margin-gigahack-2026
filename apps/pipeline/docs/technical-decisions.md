# Technical decision log

Last updated: 27 September 2026

Statuses used here:

- **Accepted** — agreed for the current MVP.
- **Provisional** — working direction that may change during integration.
- **Open** — requires an explicit decision.
- **Deferred** — intentionally postponed and not required now.
- **Out of scope** — the pipeline will not implement it for this MVP.
- **Superseded** — replaced by the later decision it names.

| ID | Status | Decision | Rationale or consequence |
|---|---|---|---|
| TD-001 | Accepted | Use a thin Python control API plus a separate worker process. | Long-running inference must not live in the frontend request lifecycle. |
| TD-002 | Accepted | Use Python 3.12, FastAPI, Pydantic, Uvicorn, `uv`, and pytest. | All are open-source and suitable for direct MacBook execution. |
| TD-003 | Accepted | Persist queue state and artifacts in per-job filesystem directories. | Expected volume is small and does not justify a database or queue service. |
| TD-004 | Accepted | Make state and artifact installation atomic. | Prevent partially written checkpoints from being treated as valid after interruption. |
| TD-005 | Accepted | Waiting jobs do not block other jobs; the single worker advances one immediately actionable checkpoint at a time and uses per-job locks for state mutation. | Local ML services control their own capacity, while pipeline jobs waiting on callbacks or results must not stall the queue. |
| TD-006 | Accepted | Keep the frontend-facing workflow asynchronous. | Job creation returns promptly and the frontend polls status. |
| TD-007 | Accepted | Require asynchronous behavior from both ML integrations. | No inference call should depend on a long-running HTTP connection. |
| TD-008 | Accepted | Each ML stage pushes its completed artifact to a correlated pipeline callback. | Small local HTTP bodies keep both asynchronous handoffs explicit and restart-safe without long-running requests. |
| TD-009 | Accepted | Give each ML service a separate adapter. Their external contracts may be different or happen to match. | Avoid forcing both ML teams into one implementation shape. |
| TD-010 | Accepted | Treat ML services as externally started local services configured by URL and port. | The pipeline does not own model processes or packaging. |
| TD-011 | Accepted | Pass the recording to the audio service by local filesystem path and upload the prepared transcript to the text/MoM service as a multipart `.txt` file. | The two independently owned ML services use different integration shapes. |
| TD-012 | Accepted | ML services never communicate directly. | The pipeline owns validation, persistence, and artifact handoff. |
| TD-013 | Accepted | Preserve the audio service result as versioned structured JSON and derive plain text for the MoM service. | The portal needs segments and compact audio-derived metadata, while the text service still consumes one UTF-8 text file. |
| TD-014 | Accepted | Produce a review-ready draft MoM JSON, then accept one approved snapshot for local delivery. | Frontend editing and file export remain separate responsibilities; the backend persists only the final approved version needed for delivery. |
| TD-015 | Accepted | Use JSON as the canonical MoM representation. | One machine-readable handoff for the frontend and later exporters. |
| TD-016 | Accepted | Create a job only after its upload is safely persisted. | Avoids a public upload-in-progress state in the MVP. |
| TD-017 | Accepted | Do not implement job cancellation or deletion. | Keeps the MVP state machine and recovery behavior small. |
| TD-018 | Accepted | Retry transient connection failures once; do not retry invalid model output automatically. | Avoids infinite or misleading retries while tolerating a brief local-service failure. |
| TD-019 | Accepted | Preserve the last valid checkpoint and support manual retry conceptually. | Completed transcription should not be recomputed after a text-stage failure. |
| TD-020 | Accepted | Do not require Docker initially. | Direct MacBook execution is the first target. |
| TD-021 | Accepted | Declare and lock source dependencies and preinstall everything needed for offline operation. | The demo cannot depend on runtime internet access. |
| TD-022 | Out of scope | Frontend editing and ODF/DOCX download generation. | These belong to the frontend workstream. |
| TD-023 | Accepted | Notify the submitting author by local email when a draft is review-ready, then deliver the approved MoM locally to recipients selected through internal-directory autocomplete. | Email remains reliable when staff change physical devices while using remote workstations. No external SMTP, directory, or mail API is permitted at runtime; sending as the author requires an authorized local send-as or delegated-sending mechanism. |
| TD-024 | Accepted | Validate schema-version-1 MoM review documents in the pipeline. | The existing portal fields are now a typed backend contract; all evidence uses stable transcript segment IDs. |
| TD-025 | Provisional | Use the existing `POST /jobs/{jobId}/approve` contract for approval with or without recipients. | The backend branches after soft recipient filtering; no second delivery endpoint or compatibility contract is needed before launch. Directory replacement and authentication remain open. |
| TD-026 | Open | Exact contracts exposed by the two ML services. | Adapter specifications depend on ML-owner input. |
| TD-027 | Accepted for current increment | `COMPLETED / approved` means approval had no accepted recipients; `COMPLETED / delivered` additionally means local SMTP accepted the message. | Malformed and non-allowlisted addresses are skipped rather than blocking approval. SMTP failure preserves the approval at `FAILED / delivery_failed`, and the identical approval request retries delivery. |
| TD-043 | Accepted for current increment | The recipient allowlist defaults to `medpark.test`, and all demo identities use that reserved test domain. | It is Mailpit-compatible, clearly non-production, and avoids examples that resemble routable institutional addresses. |
| TD-044 | Accepted for current increment | Keep a small server-owned local demo directory for participant and recipient autocomplete, while allowing reviewers to save an unmatched free-text name for each diarized speaker. | The demo remains offline and useful before an institutional directory is integrated. Speaker-name assignments are separate review artifacts, so the accepted source transcription remains immutable. |
| TD-028 | Deferred | Rich evidence annotations and a reviewer-resolution protocol. | Stable segment-ID references are validated now; word spans, resolution targets, and recommendation semantics remain deferred. |
| TD-029 | Deferred | Content-specific logging restrictions. | No strict policy has been agreed; privacy-safe defaults should be revisited before real institutional use. |
| TD-030 | Deferred | Container packaging and Compose deployment. | Revisit only if direct execution is insufficient. |
| TD-031 | Open | Supported input audio formats and maximum upload size. | Must match the audio ML service and frontend validation. |
| TD-032 | Open | Model polling intervals, stage timeouts, and exact error taxonomy. | Must be tuned after real service behavior is known. |
| TD-033 | Provisional | Accept common audio extensions up to 300 MiB without decoding or transcoding. | Provides a useful upload boundary while the definitive audio contract remains open. |
| TD-034 | Provisional | Use an isolated mock audio adapter that acknowledges pickup and pushes a deterministic transcription callback after five seconds. | Exercises the complete asynchronous handoff without presenting the mock as the real ML contract. |
| TD-035 | Accepted | Persist per-job operational history as versioned, append-only Kafka-shaped NDJSON records. | Gives local services one ordered record envelope without introducing a broker or processor. |
| TD-036 | Accepted | Validate and persist schema-version-1 transcription JSON, then extract `transcript.text` to `transcript.txt`. | The structured source serves the portal and supplies audio metadata; the derived file remains the text/MoM input. |
| TD-037 | Accepted | The text/MoM service accepts a multipart upload of `transcript.txt`, the persisted schema-version-1 transcription, and the job's `uploadedAt`, and returns an asynchronous model job ID. | The transcription supplies the segment IDs that MoM evidence must cite; the upload time is the meeting date when the recording has none. |
| TD-038 | Superseded | The development text/MoM mock was replaced by the local MoM service (TD-045). | The pipeline has no text mock; tests use test doubles. |
| TD-039 | Accepted | Persist schema-version-1 review context beside a review-ready MoM and expose it separately from transcript and MoM content. | Initial portal metadata stays compact; the potentially large transcript is loaded through its own endpoint. |
| TD-040 | Accepted | Keep transcript and MoM confidence in review context; do not include recommendation annotations, issue counts, or export gating. | Confidence is part of the agreed ML outputs, while red-word recommendations require later ML-team validation. |
| TD-041 | Accepted | Keep authentication and SSO outside the MVP API; use one configured local demo submitter identity. | The upload contract remains audio-only while review metadata can still carry the assumed submitter needed by the later notification flow. |
| TD-042 | Provisional | Route embedded development audio-mock callbacks through the real FastAPI handlers using in-process ASGI by default, with actual HTTP available by configuration. | Keeps mock runs deterministic in restricted local environments while preserving the externally visible HTTP callback contract for real ML services and network-level integration tests. |
| TD-045 | Accepted | Generate the MoM with Muse Glimmer 30B, Q4_K_M GGUF, served by a llama.cpp `llama-server` child of the local MoM service (`src/secure_mom_llm`). The model reasons freely, then writes JSON under a grammar derived from the draft schema; code fills segment IDs, timestamps, speakers, date, duration, and languages. | Muse ranked well in the MoM benchmark and runs on the MacBook. The grammar rules out malformed output, and derived fields cannot be invented. Streaming with no read timeout lets long meetings finish. |
| TD-046 | Accepted | The text service reports a generation it cannot complete to a MoM failure callback, which moves the job to `FAILED` with the service's safe error. | Without it a failed generation would leave the portal waiting indefinitely. |
| TD-047 | Provisional | The MoM is written in Romanian by default; `MOM_LLM_OUTPUT_LANGUAGE` selects `ro`, `ru`, or `en` for the service. | The upload contract stays audio-only until the team decides how a user chooses the MoM language. |

## Logging clarification

“Do not log transcript/MoM bodies” would mean avoiding copies of sensitive
meeting content in operational log messages while still logging job IDs, stages,
durations, and errors. The team has not adopted that as a strict requirement at
this stage. The implementation should therefore keep logging configurable and
avoid making a stronger compliance claim than has been agreed.
