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

- [x] Require schema-version-1 transcription JSON from the audio-to-text callback,
  including complete text, display segments, duration, language proportions,
  speakers, and transcript confidence.
- [x] Preserve the structured source separately and derive
  `transcript/transcript.txt` for the existing text/MoM input.
- [x] Require the schema-version-1 MoM envelope with MoM confidence while leaving its
  detailed `document` object open.
- [x] Persist compact schema-version-1 review context when the MoM is ready;
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

# Portal UI integration

Status: next implementation iteration

The portal is connected to the existing review-ready backend boundary. A
developer or notification may open the router-free portal with
`?review=<jobId>`; the fresh session loads the durable draft, transcript, and
review context only at `AWAITING_REVIEW / review_ready`. Email notification
remains paused below.

The portal should:

- resolve the job ID supplied by its route or local navigation state;
- load `GET /api/v1/jobs/{jobId}/review-context` for compact page metadata;
- load `GET /api/v1/jobs/{jobId}/mom` for the generated draft content;
- load `GET /api/v1/jobs/{jobId}/transcript` separately and only when required;
- represent loading, `ARTIFACT_NOT_READY`, not-found, and invalid-artifact
  responses clearly;
- display the existing workflow status, recording metadata, processing timing,
  language and speaker aggregates, and quality scores alongside the MoM; and
- avoid assuming authentication, recommendation annotations, issue counters,
  export gating, or an approval/delivery contract.

This increment covers loading and displaying the draft-review data. Editing,
approval, download, export, and distribution are not silently included.

# Post-MoM review and delivery requirements

Status: stable review link, live demo directory, approval, and final-delivery
slice implemented; notification remains pending

These items extend the workflow from a review-ready MoM through author
notification, portal review, recipient selection, approval, and local delivery.
They must run entirely inside the hospital environment and remain usable while
the demonstration machine is disconnected from the internet.

## Stable internal review link

- [x] Define a configurable internal portal base URL suitable for the offline
  demonstration environment.
- [x] Generate a stable `?review=<jobId>` URL without embedding meeting content
  or local filesystem paths; preserve configured base paths and encode job IDs.
- [x] Keep the URL out of schema-version-1 review context. It will be derived
  into the persisted notification intent in the notification increment.
- [x] Keep authorization enforcement outside the MVP while documenting the
  assumption that the hospital platform would authorize the authenticated user.
- [x] Test URL generation for configured base paths, ports, job IDs, unsafe
  hosts, credentials, existing query strings, and fragments.

## Local notification email

- [ ] Define a small notification model containing the recipient, subject,
  review URL, job ID, and safe non-sensitive message text.
- [ ] Create the notification only after `mom/draft.json` and
  `review/context.json` are durably available at `AWAITING_REVIEW /
  review_ready`.
- [ ] Read the recipient from the server-side persisted submitter metadata; do
  not expose the email through the browser-facing review-context response.
- [x] Add a replaceable local mail adapter. Tests use a deterministic recording
  adapter; the demo uses Mailpit through loopback SMTP.
- [x] Use only the local demonstration mail environment. External SMTP, cloud
  mail APIs, and runtime internet dependencies are prohibited.
- [ ] Define idempotency so callback replay or process restart does not send
  duplicate notifications.
- [ ] Define bounded retry and failure behavior without discarding the valid MoM
  and review-context artifacts.
- [ ] Record metadata-only notification events without logging meeting content,
  message bodies, or credentials.
- [ ] Add automated and offline smoke coverage for message preparation and local
  delivery.

## Recipient selection, approval, and final delivery

- [ ] Provide a local, internally maintained recipient-directory lookup that
  supports surname-based autocomplete; do not use an external directory at
  runtime.
- [x] Use the existing portal-to-backend approval request to persist the final edited
  MoM and the author-selected recipient addresses or directory identifiers.
- [x] Generate the delivery email from the approved MoM and supported meeting
  information; do not invent missing metadata.
- [x] Deliver through the replaceable local mail adapter only after approval,
  using the submitting author's authorized institutional address as sender.
- [ ] Confirm and document the local mail environment's send-as or delegated
  sending policy; never spoof an arbitrary sender identity.
- [x] Make approval and final delivery idempotent, with clear delivery state,
  bounded retries, and metadata-only operational events.
- [x] Use `COMPLETED / approved` for no-email approval and
  `COMPLETED / delivered` only after local SMTP acceptance. Preserve the
  approved artifact at `FAILED / delivery_failed` if delivery fails.
- [x] Add offline tests for recipient filtering, sender authorization, email
  composition, idempotency, failure preservation, and local delivery.

SSO implementation, account management, and full authorization enforcement
remain outside the hackathon MVP. Word-level recommendations and ambiguity
annotations also remain excluded until the ML team confirms it can provide
reliable source data.

# Current portal/pipeline contract decisions

Status: implemented where marked; remaining items are deliberate backlog.

- [x] Validate the existing schema-version-1 MoM review-document schema in the
  pipeline, including stable evidence `segment_id` references.
- [x] Make pipeline mock artifacts multilingual and review-rich, using anonymous
  `Participant N` speaker labels rather than invented staff identities.
- [x] Preserve optional `audioMetadata.recordedAt` through
  `review/context.json`. This is a timestamp extracted by the audio service,
  not a copied file's filesystem creation time or an assumed meeting date.
- [x] Make transcript and MoM confidence nullable and propagate them unchanged
  into review context; the UI hides rings when either value is unavailable.
- [x] Remove the frontend rule that inferred `patient_case` implies
  download-only delivery.
- [ ] Define word-level review flags, editable-field targets, resolution
  validation, and speaker-name substitution persistence when the ML team can
  supply reliable annotations. The current frontend-only red-word behaviour is
  not a backend contract.
- [x] Define and implement idempotent approval and approved-MoM retrieval for
  both the zero-recipient and conditional-delivery branches.
- [x] Extend the same approval endpoint with idempotent local-delivery
  success/failure states; do not introduce a second delivery endpoint.
- [ ] Define retention, discard, and purge policy. There is no job deletion API;
  current deletion claims remain a known UI issue, not an implemented backend
  capability.
- [ ] Add a local recipient-directory endpoint. The current portal directory
  remains a `@medpark.test` demo stub; the server-side allowed-domain policy is
  implemented independently.
- [ ] Implement manual retry and readiness semantics after real local model
  behaviour supplies the final timeout and error taxonomy.

# Approval and completion-screen baseline: no recipients

Status: implemented on 27 September 2026, then extended by the conditional
delivery increment below; visual PDF verification remains pending.
The browser starts with an audio-only upload,
the reviewer edits the displayed draft, and Export approves that exact result.
With an empty recipient list, the job ends on a download screen and **no email
is composed, queued, or sent**.

## Starting behavior addressed

- The portal called an absent `/export` endpoint, ignored its failure,
  and still showed **Shared**. There was no persisted approved MoM.
- The recipient picker could prefill addresses inferred from mentioned names
  and could not remove its last address. This made zero recipients unreliable.
- **Download PDF** opens a print window. Keep that behavior in this
  increment; a direct, polished PDF download is deferred.
- **Your time** initially measured only review-screen time, then reused a
  session-storage timestamp across visits to the upload screen. That could
  overstate a fresh run. The prior `review-context.processing.elapsedMs`
  covers queue and handoff time, rather than the sum of model stages.
- The completion screen displayed **Meeting data deleted** although there is
  no deletion API or retention/cleanup implementation.

## Implemented user flow and success states

1. Start a per-meeting wall-clock timer when the portal URL first opens. Upload
   the audio, process it locally, edit the review pane, and allow an empty
   recipient list. No recipient is selected automatically from meeting names.
2. On Export click, capture the elapsed user time and build one immutable
   approved MoM snapshot from the visible edits and resolved flags. Keep the
   existing blocking-review rule. Disable repeat submissions while saving.
3. Submit that snapshot with `recipients: []` to a local approval endpoint. The
   pipeline validates the schema-version-1 document, persists it under the job,
   and marks the job `COMPLETED`. No mail adapter is invoked.
   The separate, currently unimplemented ready-for-review notification must
   stay disabled for this no-email demo. Because recipients are selected only
   at Export, that earlier notification cannot be controlled by the empty
   recipient list.
4. Navigate to the completion screen only after approval is confirmed. Show
   **Approved / Ready to download** and **No email sent** rather than **Shared**
   or an internal-email claim. If saving fails, stay on Review, preserve edits,
   show the error, and allow retry. Never report approval after a failed call.
5. Keep the current print-based PDF control, using the approved document
   returned by the server. Reloading the completion URL retrieves the approved
   document again.

### Approval contract

- `POST /api/v1/jobs/{job_id}/approve` with
  `{ "schemaVersion": 1, "document": <reviewed MoM>, "recipients": [] }`.
  Return the approved document, job ID, and approval timestamp.
- `GET /api/v1/jobs/{job_id}/approved-mom` returns only the approved snapshot
  after approval. Keep the draft endpoint distinct so a changed draft cannot
  silently alter an approved download.
- Make identical approval retries idempotent. A different document after
  approval requires an explicit conflict or revision rule; it must not silently
  overwrite the approved artifact. Persist the approval and job-state change
  atomically, with metadata-only events.
- Use the normal terminal **COMPLETED** status for an approved document,
  whether or not delivery occurs. The completion screen separately says
  **No email sent** when the recipient list is empty. Do not add a special
  no-recipient job status.
- This baseline's earlier nonempty-recipient restriction is superseded by the
  conditional delivery increment below. The endpoint itself did not change.

## Completion-screen work and deferred PDF improvement

- Keep `printPdf` unchanged this iteration. Later, choose a local PDF renderer
  and align its sections with the review pane, including topics and any
  uncertain or missing details. Verify Romanian and Russian fonts, pagination,
  and that output comes from the approved snapshot.
- In `DoneScreen`, keep one prominent **Download PDF** action and hide the
  **Download JSON** action. JSON remains the internal approved format, but
  direct JSON download is outside this screen's current scope.
- Hide the entire **Meeting data deleted** box and its heading. Also remove
  other visible deletion claims tied to Export (for example upload privacy and
  recording labels) so the portal does not imply cleanup happened. Do not
  delete the source audio, transcript, draft, or approved MoM in this increment.
- Treat cleanup as a later, likely post-MVP step: agree retention and deletion
  timing, add a separate cleanup operation/status, and only then restore
  deletion wording after verifying which artifacts were removed. The existing
  Discard copy and absent delete endpoint need the same honest treatment.

## Timing

| Metric | Source and boundary | Display rule |
| --- | --- | --- |
| **Portal elapsed time** | Browser starts a fresh timer on each portal page load or **New meeting**, then captures Export click time before awaiting the approval API. This wall-clock interval includes upload, processing wait, and review. Do not reuse a start timestamp from a previous visit. Save the final elapsed seconds against the approved job for a completion-page reload. | Show the measured interval beneath the savings estimate so the comparison remains transparent. A retry uses the successful Export click. |
| **Estimated time saved** | Use the team's illustrative 60-minute manual-writing comparison minus the portal elapsed time, rounded to whole minutes and floored at zero. | Make this the prominent completion-card value and restore the time-saved message. Label it as an estimate, not a measured clinical productivity claim. |
| **Automatic processing** | Persist separate `audioStageMs` and `momStageMs` for the two local ML stages, measured from accepted model submission to validated callback. These are *stage elapsed times*, including service and callback overhead. | Show `audioStageMs + momStageMs` with an audio/MoM-stage label. Show `—` when either duration is unavailable; do not substitute `processing.elapsedMs`. |
| **End-to-end processing** | Existing `review-context.processing.elapsedMs` from persisted job creation to review readiness. | Keep for diagnostics or a separate total; it includes queue and coordination time and is not the sum of the two ML stages. |

Persist stage boundaries in job state or metadata so worker restarts and browser
reloads do not reset them. Use server-side timestamps and idempotent callbacks;
do not infer stage durations from the frontend's two-second status polling.
Update the development mocks with distinct, plausible stage and end-to-end
durations. The 60-minute manual-writing value is an explicit comparison
assumption for the demo; display the actual portal time alongside it. The
audio length is source metadata, not a timing substitute.

## Implementation order and acceptance checks

- [x] Agree the narrow approval/status/timing contract and record changes
  to the pipeline decision log, scope, OpenAPI, and portal API alignment notes.
- [x] Add atomic approved-artifact persistence, idempotent approval/retrieval,
  and the no-recipient branch. Verify that an empty list produces no mail call
  or queued email; rejected input leaves no success claim.
- [x] Capture both ML-stage timings and expose their definitions in review
  context. Verify their sum separately from the existing end-to-end elapsed
  time. A resumed-job timing check remains useful if retry is implemented.
- [x] Update the portal to start the URL-open timer, permit zero recipients,
  submit the approved snapshot, handle errors, and restore the completion
  screen from the approved endpoint after reload.
- [ ] Check that the existing print-based PDF control receives the approved
  document. The direct PDF download remains a later increment.
- [x] Change completion copy for zero recipients, hide JSON and deletion UI,
  and show estimated savings with the measured portal time in RO/RU/EN.
- [ ] Run the frontend typecheck/build, pipeline tests, and an offline live
  smoke test from upload through approval and PDF download. For any pipeline
  implementation iteration, apply the restart-and-live-verification rule at
  the top of this plan.

Decisions still open: direct PDF generation, notification email, live directory
integration, and cleanup policy. They do not block approval or final local
delivery.

# Mailpit pipeline integration — step 1

Status: implemented and verified on 27 September 2026. This increment created
the SMTP boundary; the conditional delivery increment below now uses it.

- [x] Added `PIPELINE_MAIL_HOST`, `PIPELINE_MAIL_PORT`,
  `PIPELINE_MAIL_TIMEOUT_SECONDS`, and `PIPELINE_MAIL_USE_STARTTLS` to the
  central pipeline configuration and `.env.example`. Demo defaults are
  `127.0.0.1:1025`, a five-second bounded timeout, and STARTTLS disabled.
- [x] Added `mail_adapter.py`: a replaceable `LocalMailAdapter` protocol and
  `SmtpMailAdapter` implementation using only Python `smtplib` and
  `EmailMessage`. It has no Mailpit HTTP API, cloud-mail API, relay, or
  forwarding dependency.
- [x] Added validation before SMTP connection for required recipients and safe
  header values, and a safe retry classification for SMTP failures.
- [x] Documented the boundary and offline demo configuration in the pipeline
  README.

Verification output: `uv run pytest` passed all 44 tests (including five new
mail-adapter tests); source compilation and a temporary generated OpenAPI JSON
parse both passed. The suite emitted one existing FastAPI/Starlette TestClient
deprecation warning.

# Mailpit pipeline integration — step 4: conditional approval delivery

Status: implemented on 27 September 2026.

## Implemented contract

- [x] Kept `POST /api/v1/jobs/{jobId}/approve` as the only approval action. No
  `approve-and-deliver` endpoint or backward-compatibility branch was added.
- [x] Made `recipients` and `skippedRecipients` required fields of every newly
  persisted approved artifact. Older approved artifacts without the new shape
  intentionally do not load in this pre-launch prototype.
- [x] Normalized and de-duplicated recipient addresses. Malformed addresses and
  domains outside `PIPELINE_MAIL_ALLOWED_RECIPIENT_DOMAINS` are soft failures:
  they are recorded in `skippedRecipients`, while approval continues.
- [x] Used `medpark.test` as the default allowed domain and for the frontend
  directory, demo submitter, message IDs, mocks, tests, and documentation.
- [x] If no accepted addresses remain, persisted the approval and transitioned
  to `COMPLETED / approved` without invoking SMTP.
- [x] If accepted addresses remain, composed a deterministic text email from
  approved MoM fields only and sent it through the loopback SMTP adapter. The
  sender is read from persisted submitter metadata and checked against the
  configured server identity; the browser cannot choose it.
- [x] Transitioned to `COMPLETED / delivered` only after SMTP acceptance. On
  failure, persisted safe metadata at `delivery/result.json`, preserved
  `mom/approved.json`, and exposed `FAILED / delivery_failed` with a safe
  `LOCAL_SMTP_FAILED` response and adapter-provided retry classification.
- [x] Made an identical `/approve` replay idempotent after success and the retry
  mechanism after delivery failure. A changed document or changed normalized
  recipient outcome conflicts with the immutable approval.
- [x] Updated the frontend's existing bottom action in place: it says
  **Approve and download** with no selected recipients and **Approve and send**
  otherwise. It submits the same request in both cases, reports skipped
  addresses softly, locks the approved content after SMTP failure, and renders
  the delivered completion state only from the server response.
- [x] Kept the existing print-based document export. There is no attachment
  until a server-owned PDF/DOCX artifact contract exists.

## Verification

- [x] Pipeline tests cover empty recipients, a mixed accepted/skipped list,
  duplicate normalization, composed content, SMTP acceptance, no duplicate
  send on replay, failure preservation, and same-request retry.
- [x] Pipeline OpenAPI was regenerated and synchronized into the frontend.
- [x] Frontend typecheck and production build passed with the new generated
  contract and conditional UI behavior.

Final verification output: `uv run pytest` passed all 47 pipeline tests
(including five SMTP-adapter tests and the conditional approval/delivery
coverage) with one existing Starlette TestClient deprecation warning. Python
source compilation and OpenAPI export passed. After synchronizing that OpenAPI
document, frontend `npm run typecheck` and `npm run build` passed; Vite built 66
modules. A live Mailpit container smoke check could not run on this machine
because the `docker` executable is not installed; the loopback SMTP boundary is
therefore verified by the adapter and approval-flow test doubles, not by a live
container in this increment.
