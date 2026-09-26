# Technical decision log

Last updated: 26 September 2026

Statuses used here:

- **Accepted** — agreed for the current MVP.
- **Provisional** — working direction that may change during integration.
- **Open** — requires an explicit decision.
- **Deferred** — intentionally postponed and not required now.
- **Out of scope** — the pipeline will not implement it for this MVP.

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
| TD-013 | Accepted | Use plain text as the transcript artifact for now. | Keeps the initial integration contract small. |
| TD-014 | Accepted | Stop the pipeline at a review-ready draft MoM JSON. | Frontend editing and file export are separate responsibilities. |
| TD-015 | Accepted | Use JSON as the canonical MoM representation. | One machine-readable handoff for the frontend and later exporters. |
| TD-016 | Accepted | Create a job only after its upload is safely persisted. | Avoids a public upload-in-progress state in the MVP. |
| TD-017 | Accepted | Do not implement job cancellation or deletion. | Keeps the MVP state machine and recovery behavior small. |
| TD-018 | Accepted | Retry transient connection failures once; do not retry invalid model output automatically. | Avoids infinite or misleading retries while tolerating a brief local-service failure. |
| TD-019 | Accepted | Preserve the last valid checkpoint and support manual retry conceptually. | Completed transcription should not be recomputed after a text-stage failure. |
| TD-020 | Accepted | Do not require Docker initially. | Direct MacBook execution is the first target. |
| TD-021 | Accepted | Declare and lock source dependencies and preinstall everything needed for offline operation. | The demo cannot depend on runtime internet access. |
| TD-022 | Out of scope | Frontend editing and ODF/DOCX download generation. | These belong to the frontend workstream. |
| TD-023 | Deferred | SMTP and distribution-list delivery. | The team will decide this later. |
| TD-024 | Open | Definitive MoM JSON schema. | The text-model and frontend contracts still need alignment. |
| TD-025 | Open | Final public HTTP API contract. | Current endpoints are a draft and do not include approval. |
| TD-026 | Open | Exact contracts exposed by the two ML services. | Adapter specifications depend on ML-owner input. |
| TD-027 | Open | Meaning and ownership of the final `COMPLETED` state. | The pipeline ends at `AWAITING_REVIEW`, while later frontend actions occur outside it. |
| TD-028 | Deferred | Statement-level supporting evidence and traceability fields. | Explicitly outside the current design. |
| TD-029 | Deferred | Content-specific logging restrictions. | No strict policy has been agreed; privacy-safe defaults should be revisited before real institutional use. |
| TD-030 | Deferred | Container packaging and Compose deployment. | Revisit only if direct execution is insufficient. |
| TD-031 | Open | Supported input audio formats and maximum upload size. | Must match the audio ML service and frontend validation. |
| TD-032 | Open | Model polling intervals, stage timeouts, and exact error taxonomy. | Must be tuned after real service behavior is known. |
| TD-033 | Provisional | Accept common audio extensions up to 300 MiB without decoding or transcoding. | Provides a useful upload boundary while the definitive audio contract remains open. |
| TD-034 | Provisional | Use an isolated mock audio adapter that acknowledges pickup and pushes a deterministic transcription callback after five seconds. | Exercises the complete asynchronous handoff without presenting the mock as the real ML contract. |
| TD-035 | Accepted | Persist per-job operational history as versioned, append-only Kafka-shaped NDJSON records. | Gives local services one ordered record envelope without introducing a broker or processor. |
| TD-036 | Accepted | Persist the pushed transcription bytes before transforming them, then write the same decoded UTF-8 content to `transcript.txt`. | The source may contain plain, JSON, or CSV text; this increment changes representation without parsing or restructuring it. |
| TD-037 | Provisional | The text/MoM service accepts `transcript.txt` through multipart upload and returns an asynchronous model job ID. | The adapter isolates route and response details until the ML owner confirms the final contract. |
| TD-038 | Provisional | The development text/MoM mock pushes a two-field JSON object to a correlated pipeline callback after five seconds. | Exercises JSON validation, atomic persistence, recovery, and the `AWAITING_REVIEW` transition without defining the final MoM schema. |

## Logging clarification

“Do not log transcript/MoM bodies” would mean avoiding copies of sensitive
meeting content in operational log messages while still logging job IDs, stages,
durations, and errors. The team has not adopted that as a strict requirement at
this stage. The implementation should therefore keep logging configurable and
avoid making a stronger compliance claim than has been agreed.
