# Pipeline baseline implementation plan

## Iteration completion rule

Every implementation iteration must end by stopping any running pipeline API
and worker processes, starting both again from the current checkout, and
verifying the live API version and changed workflow. An iteration is not
complete merely because its tests pass while stale processes are still running.

Status: approved on 26 September 2026

This checklist tracks the approved mock baseline. An item is marked complete
only after its implementation has been exercised during the final smoke check.

- [x] 1. Bootstrap the Python project.
- [x] 2. Add centralized provisional configuration.
- [x] 3. Add binary and UTF-8 text filesystem services.
- [x] 4. Add dummy pipeline API endpoints.
- [x] 5. Add the generated pipeline OpenAPI document.
- [x] 6. Add provisional OpenAPI documents for both ML services.
- [x] 7. Add a mock worker and state-machine shell.
- [x] 8. Add configurable local server logging.
- [x] 9. Add local operating and discovery documentation.
- [x] 10. Run the baseline smoke verification.

## Verification result

Completed on 26 September 2026 with Python 3.12.14. The API and mock worker
started successfully; all dummy endpoints returned placeholder responses and
wrote safe events to the configured log; byte and multilingual UTF-8 text
round trips succeeded; all three OpenAPI JSON documents parsed successfully;
and the dependency lockfile passed `uv lock --check`.

## Explicit exclusions

This baseline does not implement real job persistence, queueing, atomic
checkpoints, ML calls, artifact validation, finalized schemas, production state
transitions, retries, recovery, or automated tests.

# Upload-to-audio-pickup implementation plan

Status: approved on 26 September 2026

This increment replaces the mock upload path through the point where an audio
service accepts the persisted recording. The ML service contract is still under
discussion, so its pickup is represented by an isolated mock adapter.

- [x] 1. Add versioned job, response, error, event, and mock-submission models.
- [x] 2. Stream common audio formats up to 300 MiB into a staging job directory.
- [x] 3. Atomically publish the audio, initial state, and event log as a queued job.
- [x] 4. Return `202 Accepted` and expose real persisted job status.
- [x] 5. Add atomic state updates and safe job discovery.
- [x] 6. Replace mock worker transitions with single-active-job dispatch.
- [x] 7. Add a replaceable mock audio-service pickup adapter.
- [x] 8. Record ordered Kafka-shaped events in per-job NDJSON files.
- [x] 9. Add API, persistence, event-log, worker, and failure-path tests.
- [x] 10. Update contracts and operating documentation.
- [x] 11. Run the implementation smoke verification.
- [x] 12. Restart the live API and worker and verify the served API version.

## Implemented boundary

```text
audio upload
    -> atomic filesystem-backed queued job
    -> separate worker
    -> mock audio-service acknowledgement
    -> persisted TRANSCRIBING checkpoint
```

Transcript polling, transcript persistence, text processing, and draft MoM
generation remain later increments.

## Verification result

Completed on 26 September 2026 with Python 3.12.14. All 18 automated tests
passed, the dependency lockfile validated, all OpenAPI JSON documents parsed,
and source/test compilation succeeded. A live API and separate worker smoke
test returned `202`, preserved the uploaded bytes, produced ordered event
offsets 0 through 6, persisted the mock model job ID, transitioned the job to
`TRANSCRIBING`, and exposed that checkpoint through the status endpoint.
The stale baseline processes were then stopped; the current API and worker were
started, and localhost reported API version `0.2.0-provisional`.

# Transcription-result-to-MoM-dispatch implementation plan

Status: completed on 26 September 2026

## Goal and stopping point

This increment starts when the audio-to-text ML service pushes its completed
transcription document to the pipeline as bytes. Audio upload, audio-service
dispatch, and the `TRANSCRIBING / audio_processing` checkpoint were implemented
in the previous increment and are not redesigned here.

The pipeline will persist the received transcription document, pass it through
an explicit bytes-to-text boundary, write a UTF-8 `.txt` file, submit that file
to the text/MoM service, and persist the accepted text-service job ID. The
incoming bytes may contain plain text, JSON text, or CSV text. For now, the
transformer does not interpret those structures: it preserves the decoded
textual content exactly and only changes its stored representation to `.txt`.

The increment is complete at this checkpoint:

```text
audio-to-text ML pushes transcription bytes
    -> pipeline atomically persists the source transcription
    -> bytes-to-text transformer preserves its textual content
    -> pipeline atomically persists transcript.txt as UTF-8
    -> text/MoM service accepts the .txt file asynchronously
    -> persisted GENERATING_MOM / text_processing checkpoint
```

Polling the text service and receiving, validating, persisting, or exposing its
draft MoM result belong to the next increment.

## Provisional contracts for this increment

- Treat the received transcription as a non-empty byte document at the API and
  persistence boundary. Do not parse or infer CSV, JSON, or plain text before it
  reaches the transformer.
- Add a pipeline-owned transcription-result endpoint under the integration
  namespace, separate from frontend routes. It accepts the document as the raw
  request body, the media type from `Content-Type`, and the audio model job ID in
  a correlation header. Its exact route and header names remain provisional
  until agreed with the audio-model owner.
- Configure a small maximum intermediate-document size. Reject empty and
  oversized requests before publishing an artifact, and never put document
  contents in API errors, events, or operational logs.
- Correlate the push with both the pipeline job ID in the route and the stored
  audio model job ID. Accept it only while that job expects its transcription.
- Make retries idempotent: the same bytes for an already accepted result return
  success; different bytes for the same checkpoint return `409 Conflict`. Use a
  SHA-256 digest, byte count, and media type as persisted metadata.
- Introduce a `TranscriptionSource` value containing `data: bytes` and
  `media_type: str`, and a `TextDocument` value containing `text: str`. An
  `IntermediateTransformer` protocol owns
  `TranscriptionSource -> TextDocument`.
  The initial `Utf8IntermediateTransformer` strictly decodes UTF-8 and otherwise
  leaves every decoded character unchanged. Thus JSON remains JSON text and CSV
  remains CSV text inside the `.txt` file. Invalid UTF-8 is a transformation
  failure; it must never be silently replaced or discarded. Later CSV/JSON
  extraction or text concatenation replaces this implementation without
  changing either ML adapter.
- Serialize the transformed text as UTF-8 in `transcript.txt`. Submit it to the
  text/MoM service as a multipart file named `transcript.txt` with content type
  `text/plain; charset=utf-8`, plus pipeline-job and idempotency headers. Expect
  an asynchronous `202` acknowledgement containing a text model job ID. Keep
  route, multipart field name, and acknowledgement translation inside
  `TextService`, because the real ML contract is still provisional.
- Require the text service to deduplicate the stable idempotency key. Without
  that support, recovery can guarantee at-least-once rather than exactly-once
  submission if the worker stops after remote acceptance but before local state
  persistence.

## Persisted artifacts and states

Use a format-neutral filename for the received transcription bytes and an
explicit `.txt` filename for the text-service input:

```text
runtime/jobs/<job-id>/
  transcript/
    source.bin
    transcript.txt
  state.json
  operations.ndjson
```

Extend the artifact state with separate `transcriptionSource` and `textInput`
descriptors containing the relative path, media type, byte count, and digest.
Keep them distinct so the original transcription bytes are preserved and a
future transformer can safely produce different text. The `textInput`
descriptor always records `text/plain; charset=utf-8`; its digest and byte count
describe the encoded file, not Python character count.

Make the state-schema change additive so existing version-1 job files remain
readable; new or changed fields must not turn old checkpoints into invalid jobs.

| Checkpoint | Public status | Stage | Required persisted data |
|---|---|---|---|
| Waiting for transcription | `TRANSCRIBING` | `audio_processing` | audio model job ID |
| Transcription accepted | `TRANSCRIBING` | `transcription_received` | `transcriptionSource` descriptor and file |
| Transformation completed | `TRANSCRIBING` | `text_input_ready` | `textInput` descriptor and file |
| Text service accepted submission | `GENERATING_MOM` | `text_processing` | text model job ID |
| Transformation cannot complete | `FAILED` | `transcript_transform` | source transcription plus safe error |
| Text dispatch cannot complete | `FAILED` | `text_dispatch` | source and `.txt` files plus safe error |

An artifact must be flushed, validated, and atomically installed before state
references it. State remains the canonical checkpoint. A leftover unreferenced
temporary or final artifact after interruption must be safe to overwrite or
reconcile on retry.

## Implementation checklist

- [x] 1. Update `technical-decisions.md`, `architecture.md`, `scope.md`,
  `artifact-schemas.md`, and the two ML discovery OpenAPI documents to record
  the transcription byte callback and the text/MoM `.txt` multipart upload.
  Retain the previous increment's audio upload and dispatch design; update only
  how the finished transcription reaches the pipeline and the MoM service.
- [x] 2. Extend `models.py` with `GENERATING_MOM`, typed artifact descriptors,
  transcription-result acknowledgement/error models, `TranscriptionSource`,
  `TextDocument`, and the text-service submission acknowledgement. Preserve
  validation of existing persisted version-1 states.
- [x] 3. Extend `JobStore` with atomic byte-artifact installation and a
  per-job locked state mutation operation. The lock must serialize the callback
  API and worker so concurrent writes cannot discard a model ID, artifact
  descriptor, status, attempt count, or error.
- [x] 4. Add the transcription-result push route to `api.py`. Stream or read the
  small raw body with a configured limit; validate job/state/correlation;
  atomically persist `transcript/source.bin`; append receipt events containing
  metadata only; advance to `TRANSCRIBING / transcription_received`; and return
  only after the checkpoint is durable.
- [x] 5. Define explicit callback responses: `202` for first acceptance, a
  successful idempotent response for identical replay, `400` for an empty
  body, `404` for an unknown job, `409` for a wrong state/model ID or conflicting
  replay, `413` for an oversized body, and `500` for persistence failure. Invalid
  caller input must not move a valid job to `FAILED`.
- [x] 6. Add `intermediate_transformer.py` with the transformer protocol and
  strict UTF-8 implementation. Unit-test plain text, JSON text, CSV text,
  multilingual content, and invalid UTF-8. The initial implementation changes
  representation from bytes to `str` but does not alter valid decoded content.
- [x] 7. Add `text_service.py` with a replaceable protocol, HTTP adapter, and a
  deterministic test fake. The HTTP adapter uploads the prepared UTF-8 text as a
  multipart `.txt` file with correlation/idempotency headers, applies a bounded
  request timeout, validates the `202` acknowledgement, and maps transport,
  protocol, and rejection errors into safe typed failures. Move `httpx` from a
  development-only dependency to runtime dependencies and update the lockfile.
- [x] 8. Refactor worker selection so the single active `TRANSCRIBING` job can
  resume instead of blocking all work. A job at `audio_processing` waits for its
  transcription push; a job at `transcription_received` runs the transformer;
  and a job at `text_input_ready` submits to the text service. No queued second
  job starts while one of these checkpoints is active.
- [x] 9. After transformation, atomically store
  `transcript/transcript.txt` as strict UTF-8, verify its descriptor, then
  advance to `text_input_ready`. After text-service acceptance, atomically
  persist the text model job ID, increment `momGeneration`, clear prior errors,
  and advance to `GENERATING_MOM / text_processing`.
- [x] 10. Apply the accepted one-retry rule only to transient text-service
  connection failures. Persist safe `FAILED` states for exhausted transient
  failures, invalid acknowledgements, and transformation failures without
  deleting either valid artifact checkpoint.
- [x] 11. Add ordered metadata-only events for transcription received/replayed,
  transformation started/completed/failed, text dispatch started/retried/
  accepted/failed, and each state change. Never include request bytes, decoded
  content, absolute paths, or response bodies in events or logs.
- [x] 12. Update the job-status projection so `GENERATING_MOM` is exposed and
  intermediate availability is derived from persisted descriptors. The existing
  transcript route may remain outside this increment, but its eventual response
  is now unambiguously the persisted UTF-8 `transcript.txt` artifact.
- [x] 13. Add tests for callback validation, identical and conflicting replay,
  valid and invalid UTF-8, atomic-write failures, callback/worker serialization,
  restart from both intermediate checkpoints, multipart filename/content type,
  text-service retry/error mapping, single-active-job behavior, event ordering,
  and the complete successful flow through `GENERATING_MOM` with both model job
  IDs persisted.
- [x] 14. Regenerate `pipeline.openapi.json`, update operating documentation and
  version markers, run the full tests, lock check, JSON/OpenAPI parse checks, and
  source compilation.
- [x] 15. Stop any running API and worker, restart both from this checkout, and
  smoke-test a transcription push through text-service acceptance. Verify the
  live status is `GENERATING_MOM`, stage is `text_processing`, the `.txt` file
  contains exactly the decoded source text, and the configured text-service
  fake received that file as `transcript.txt` with the UTF-8 plain-text media
  type.

## Verification result

Completed on 26 September 2026 with Python 3.12.14. All 34 automated tests
passed; source and tests compiled; all OpenAPI JSON documents parsed; the
dependency lockfile validated; and `git diff --check` passed. The live smoke
test uploaded a recording, persisted a mock audio model job ID, accepted a JSON
transcription byte body, preserved identical bytes in `source.bin` and
`transcript.txt`, uploaded `transcript.txt` as multipart data to a local fake
text/MoM service, persisted its model job ID, and exposed
`GENERATING_MOM / text_processing`. The normal API and worker were then
restarted from the current checkout, and the served API reported version
`0.3.0-provisional` with the transcription callback route present.

The runtime mock was then corrected to exercise the callback automatically:
five seconds after audio pickup it sends a deterministic UTF-8 transcription to
the pipeline, and worker recovery re-schedules callbacks for persisted mock jobs
still waiting at `audio_processing`.

## Explicit exclusions

- Choosing the source byte format or a definitive transcript schema.
- Performing format-specific extraction, normalization, or text concatenation.
- Polling the text/MoM service or accepting its callback/result.
- Validating or storing draft MoM JSON.
- Implementing the frontend transcript download route in this increment.
- Completing the job or exposing a review-ready artifact.
- Running local checkpoint mutations in parallel inside the worker. External ML
  waits may overlap and do not block unrelated jobs.

# Non-blocking scheduling follow-up

Status: completed on 26 September 2026

This follow-up supersedes the earlier single-active-job rule without introducing
parallel state mutation inside the worker.

- [x] Let multiple jobs remain in externally active states simultaneously.
- [x] Re-schedule mock callbacks for every job waiting in `audio_processing`.
- [x] Advance the oldest immediately actionable transcription/text checkpoint.
- [x] Claim the oldest queued job when other jobs are only waiting on ML work.
- [x] Retain per-job filesystem locks and the single worker-process lock.
- [x] Replace blocking-behavior tests with coverage proving that jobs waiting in
  `TRANSCRIBING` or `GENERATING_MOM` do not block the next queued job.
- [x] Update contributor guidance, architecture, scope, decisions, and README.

All 34 automated tests passed after the scheduling change, source and tests
compiled, and `git diff --check` passed. A live two-upload check confirmed that
both jobs were dispatched to the mock audio service and occupied overlapping
`TRANSCRIBING` states; neither waited for the other to finish.

# Text-to-MoM mock completion plan

Status: completed on 26 September 2026

This follow-up adds the development equivalent of the audio mock for the second
ML stage and completes the pipeline through its review-ready artifact boundary.

- [x] Extend the text mock to validate a readable UTF-8 `transcript.txt`, return
  a mock model job ID, and schedule a callback after five seconds.
- [x] Generate a deterministic JSON object with exactly two top-level fields:
  `schemaVersion` and `document`.
- [x] Add a correlated text-model callback accepting UTF-8
  `application/json`, with size, syntax, object-shape, state, and model-job-ID
  validation.
- [x] Make callback delivery idempotent and reject conflicting replays.
- [x] Atomically persist the original result bytes as `mom/draft.json` with an
  artifact descriptor before advancing state.
- [x] Add `AWAITING_REVIEW / review_ready` and expose the persisted JSON through
  `GET /api/v1/jobs/{jobId}/mom`.
- [x] Re-schedule the text mock callback after worker restart for persisted jobs
  waiting in `GENERATING_MOM / text_processing`.
- [x] Add independently configurable text-mock callback URL and five-second
  delay settings.
- [x] Update contracts, architecture, artifact schemas, configuration, README,
  generated OpenAPI, package version, and dependency lockfile.

All 37 automated tests passed, source and tests compiled, all OpenAPI documents
parsed, the lockfile validated, and `git diff --check` passed. A restarted live
API and worker processed job `031e7b07-69f2-4981-a2fc-c26474e02090` through both
delayed mock callbacks, persisted the two-field `mom/draft.json`, exposed it
through the public MoM endpoint, and reached `AWAITING_REVIEW / review_ready`.
The served API version was `0.4.0-provisional`.

# Review-boundary data-contract alignment

Status: completed on 26 September 2026

This increment supersedes the earlier format-neutral transcription input and
two-field mock MoM envelope. It changes data structures only; it does not add a
new workflow, email delivery, portal editing, approval, export, or ML-generated
review recommendations.

- [x] Require `transcription.v1alpha1` JSON from the audio-to-text callback,
  including complete text, display segments, duration, language proportions,
  speakers, and transcript confidence.
- [x] Preserve the structured source separately and derive
  `transcript/transcript.txt` for the existing text/MoM input.
- [x] Require the `mom.v1alpha1` envelope with MoM confidence while leaving its
  detailed `document` object open.
- [x] Persist compact `review-context.v1alpha1` metadata when the MoM is ready;
  retain submitter email server-side but omit it from the browser projection.
- [x] Keep authentication out of the public contract; source the assumed MVP
  submitter from fixed local demo configuration rather than upload headers.
- [x] Keep transcript and MoM content behind separate read endpoints so the
  large transcript does not inflate review-context responses.
- [x] Preserve the existing job statuses and stages.
- [x] Exclude recommendation annotations, issue counters, and export gating.
- [x] Update both ML contracts, the generated pipeline OpenAPI, development
  mocks, artifact documentation, and automated contract tests.

All 36 automated tests passed, source and tests compiled, all three OpenAPI
documents parsed, and `git diff --check` passed. The API and worker were
restarted from this checkout. Live job
`2351deeb-12cc-4fbf-bc77-9b4b52c07723` accepted the structured transcription
and versioned MoM, persisted the structured source, derived plain-text input,
and review context, and reached `AWAITING_REVIEW / review_ready`. The served API
reported `0.5.0-provisional`; the browser review-context response propagated
both confidence scores without exposing the submitter email, and the transcript
was returned through its separate endpoint.
