# Mailpit completion implementation plan

Status: current implementation baseline verified on 27 September 2026; remaining
work is ordered below by demo value and dependency.

This is the authoritative plan for completing the local email flow. Delete it
after the demo-critical definition of done has been verified offline and move
any deliberately deferred items to the normal product backlog.

## Goal and boundaries

Complete the local flow without adding a cloud API, external SMTP server,
external directory, runtime download, or internet dependency:

```text
draft MoM becomes review-ready
  -> one safe local notification to the configured submitting author
  -> author opens a stable local review URL
  -> author approves with zero or more recipients
  -> zero recipients: approve and download
  -> one or more accepted recipients: send the approved MoM through local SMTP
```

The recording remains the source of truth. Notification messages must not
contain transcript or MoM content. Final-delivery messages may contain only the
approved MoM snapshot. Authentication, SSO, real institutional directory
integration, and a production send-as policy remain outside the hackathon MVP.

## Current baseline

### Implemented

- [x] Loopback-only Mailpit environment under `apps/mailpit`, configured for
  SMTP on `127.0.0.1:1025` and its UI on `127.0.0.1:8025`.
- [x] Replaceable standard-library SMTP adapter with bounded timeout and no
  Mailpit HTTP, relay, forwarding, or cloud dependency.
- [x] Persisted server-side demo submitter identity.
- [x] Server-owned local demo directory and
  `GET /api/v1/directory?q=...`, with name, email, and title matching and a
  result limit.
- [x] Recipient picker calls the local directory endpoint. The frontend static
  list is now a fallback, not the primary live source.
- [x] One approval endpoint for both zero-recipient approval and conditional
  final delivery.
- [x] Recipient normalization, de-duplication, allowed-domain enforcement, and
  soft reporting of skipped addresses.
- [x] Immutable approved MoM snapshot, stable final-delivery Message-ID,
  metadata-only delivery result, successful-replay idempotency, and retry after
  a controlled SMTP failure.
- [x] Deterministic structured-text approved-MoM message using the persisted,
  configured demo submitter as `From`.
- [x] Portal success and failure states driven by the approval API result.
- [x] Automated baseline: 78 pipeline tests pass; frontend tests, typecheck, and
  production build pass.

### Not implemented or not live-verified

- [x] Stable URL implementation that restores an unapproved review-ready job
  from a fresh session. Manual browser acceptance remains below.
- [x] Persisted draft-ready notification intent, sending, result, and restart
  behavior.
- [ ] Live Mailpit verification, Mailpit downtime/recovery, and a complete
  Wi-Fi-disabled run. Docker is not installed in the current environment.
- [ ] Immutable directory-person IDs and ID-based approval validation.
- [ ] Server-readable PDF/DOCX artifact and final-message attachment.
- [ ] Institutional send-as/delegated-sending policy beyond the single demo
  identity.

## Priority and implementation order

P0 is required to demonstrate the complete challenge email flow. P1 hardens
the current demo without changing its product shape. P2 is optional for the
hackathon and must not delay P0 verification.

## P0.1 — Stable local review URL and fresh-session restoration

Status: implemented and covered by automated URL/state tests; manual
fresh-browser acceptance remains pending because no controllable browser was
available in the implementation environment.

The notification cannot be useful until its link can restore the review screen
without relying on in-memory state from the upload tab.

### Contract

- [x] Add `PIPELINE_PORTAL_BASE_URL`, defaulting to
  `http://127.0.0.1:3100`, to pipeline configuration and `.env.example`.
- [x] For the current router-free SPA, use the provisional stable URL shape
  `http://127.0.0.1:3100/?review=<jobId>`. Do not embed content, filesystem
  paths, submitter information, or credentials in the URL.
- [x] Normalize the configured base URL and append the encoded job ID using a
  URL builder rather than string concatenation. For the demo profile, reject
  non-loopback hosts so configuration cannot accidentally create an external
  runtime link.
- [x] Treat this as a navigation link, not authorization. Document that a real
  hospital deployment must authorize the viewer; authentication remains out of
  MVP scope.

### Frontend work

- [x] On initial load, recognize `?review=<jobId>` before the normal upload
  flow. It must not conflict with the existing `?approved=<jobId>` completion
  link.
- [x] Fetch job status, draft MoM, transcript, and review context from the local
  API and hydrate the existing Review screen.
- [x] Enter Review only for `AWAITING_REVIEW / review_ready`. Render an honest
  loading, not-found, not-ready, failed, already-approved, or local-server-
  unavailable outcome for every other state.
- [x] Reuse the existing MoM/transcript mapping and review editing behavior;
  do not add a second review implementation.
- [x] Preserve the review URL on reload until approval succeeds. After
  job creation, write `?review=<jobId>` into the current tab; after approval,
  replace it with the existing `?approved=<jobId>` URL.

### Tests and acceptance

- [x] Dependency-free frontend tests cover query precedence, empty targets,
  path preservation, encoding, and decisions for review-ready, not-ready,
  completed, and failed jobs. The existing API error branch handles not-found
  and retryability without inventing success.
- [ ] Opening the review URL in a private/fresh browser session goes directly
  to the correct draft and permits the normal approval flow.
- [x] `npm run typecheck` and a live-mode production build pass.

## P0.2 — Persisted draft-ready notification

Notification creation begins only after `mom/draft.json` and
`review/context.json` are durable and the state is ready to advance to
`AWAITING_REVIEW / review_ready`.

### Data and configuration

- [x] Add a configured system notification sender, defaulting to a clearly
  local test identity such as `secure-mom@medpark.test`. Do not send the
  author's notification from the author's own address.
- [x] Add schema-versioned `NotificationIntent` and `NotificationResult`
  models. The intent contains only job ID, recipient, generic subject, stable
  review URL, stable Message-ID, and creation time. The result contains only
  status, attempt time/count, Message-ID, safe error code, retryability, and
  whether SMTP acceptance is known or uncertain.
- [x] Persist them as `notification/intent.json` and
  `notification/result.json`, referenced by optional descriptors in job state.
  Do not persist a transcript excerpt, MoM text, meeting subject, message body,
  or credentials in either artifact.
- [x] Use a deterministic Message-ID derived from the job ID and message type,
  distinct from the final-delivery Message-ID.

### Lifecycle

- [x] In the MoM callback transaction, write the draft, review context, and
  notification intent before publishing `AWAITING_REVIEW / review_ready`.
  Callback replay must return the existing checkpoint and never create another
  intent.
- [x] Make the pipeline worker own notification submission. Add
  `AWAITING_REVIEW / review_ready` jobs with an unsent intent to the worker's
  actionable scan without blocking unrelated jobs.
- [x] Compose a generic message such as “Your Secure MOM draft is ready for
  review,” containing only the job ID and local review link. Route it through
  the existing `LocalMailAdapter`.
- [x] Keep the job at `AWAITING_REVIEW / review_ready` regardless of
  notification success or failure. The draft must remain reviewable directly
  from the portal.
- [x] Record metadata-only operations for intent creation, attempt start,
  acceptance, known failure, and uncertain outcome.

### Idempotency and recovery policy

SMTP and filesystem persistence cannot form one atomic transaction. A stable
Message-ID helps traceability but does not itself make SMTP exactly-once. The
implementation must therefore prefer avoiding duplicate notifications and
must not claim a stronger guarantee than it provides.

- [x] Atomically claim a pending intent before connecting to SMTP. Normal
  callback replay, worker scans, and restarts after a durable accepted result
  must perform no second submission.
- [x] Extend mail errors if necessary to distinguish “known not accepted” from
  “acceptance uncertain.” A connection refusal before submission may be
  retried with the same Message-ID within a small configured attempt limit.
- [x] If the process stops during submission, or SMTP may have accepted the
  message before the client lost confirmation, persist or reconstruct an
  `unknown` outcome and do not resend automatically. The demo operator may
  inspect Mailpit by Message-ID and explicitly reconcile it.
- [x] Do not convert a notification failure into the job's normal `FAILED`
  state, because processing succeeded and a valid review draft exists.

### Tests and acceptance

- [x] Unit-test safe message composition, configured system sender, recipient
  source, stable URL, and stable Message-ID.
- [x] Pipeline tests cover first send, callback replay, accepted-result
  restart, known pre-acceptance failure and bounded retry, uncertain outcome,
  and concurrent/duplicate worker invocation.
- [x] Tests assert that notification artifacts and events contain no transcript
  or MoM content.
- [x] Regenerate pipeline OpenAPI only if a public schema changes; notification
  artifacts should remain internal unless the UI genuinely needs their state.

## P0.3 — Live Mailpit and offline end-to-end verification

This phase requires Docker Desktop and the pinned Mailpit image on the actual
demo Mac. It cannot be completed in the current environment until Docker is
installed.

### One-time online preparation

- [ ] Install and start Docker Desktop.
- [ ] Run `make config` and `make preload` in `apps/mailpit` while internet is
  available.
- [ ] Confirm `axllent/mailpit:v1.31.2` is present locally and preserve the
  pinned tag.
- [ ] Create the ignored local `.env` from `.env.example`; do not commit it or
  Mailpit runtime data.

### Live acceptance sequence

- [ ] Start Mailpit with `make verify` and run the non-sensitive `make smoke`
  check.
- [ ] Run a new meeting to `AWAITING_REVIEW`; verify exactly one draft-ready
  message in the Mailpit UI with the configured system `From`, submitting
  author in `To`, generic body, stable Message-ID, job ID, and working local
  review link.
- [ ] Approve with no recipients and verify no final-delivery SMTP message.
- [ ] Run another meeting, select multiple internal recipients, and verify the
  final message's submitting-author `From`, normalized `To`, structured body,
  stable Message-ID, and one captured message after request replay.
- [ ] Include malformed, duplicate, and external addresses; verify only
  accepted internal addresses reach SMTP and skipped values are reported.
- [ ] Stop Mailpit before final delivery. Verify a safe retryable API error,
  preserved `mom/approved.json`, and metadata-only failure result. Restart
  Mailpit and repeat the identical approval; verify one accepted final message.
- [ ] Exercise notification downtime according to the known-failure/unknown-
  outcome policy without losing access to the draft.
- [ ] Restart the API and worker at notification and delivery checkpoints and
  verify the documented recovery behavior.

### Offline acceptance sequence

- [ ] Disconnect Wi-Fi and any wired network.
- [ ] Start the frontend, pipeline API, worker, both local ML services, and
  Mailpit using only preinstalled dependencies and images.
- [ ] Process representative Romanian/Russian/English-switching audio through
  notification, fresh-session review, approval, local final delivery, and
  download.
- [ ] Confirm no runtime request targets a non-loopback host and record total
  processing time and test hardware.
- [ ] Save non-sensitive screenshots or a demo checklist for the pitch; do not
  commit captured meeting messages or Mailpit's database.

## P1 — Directory hardening

The current server-owned directory and live autocomplete are sufficient for
the static hackathon demo. These changes improve authority and identity
stability but should follow P0.

- [ ] Add immutable local person IDs to `DirectoryPerson` and the server-owned
  data source. Keep `@medpark.test` addresses for the demo.
- [ ] Decide and document the approval migration: either submit directory IDs
  plus a separate typed-address field, or continue submitting normalized email
  addresses. Do not silently interpret arbitrary strings as IDs.
- [ ] If IDs are adopted, resolve them server-side at approval time, persist
  the resolved ID/email snapshot, reject unknown IDs, and continue soft domain
  filtering only for explicitly supported typed addresses.
- [ ] Remove the static fallback from **live** mode. A directory outage should
  show “local directory unavailable” rather than silently presenting a stale
  browser list. Keep deterministic demo values inside mock mode.
- [ ] Add API and frontend tests for surname search, ID stability, unknown IDs,
  duplicate selections, directory outage, and typed-address policy.
- [ ] Regenerate OpenAPI, synchronize frontend types, and update the frontend
  README/API alignment table.

## P2.1 — Server-readable final document attachment

This is not required for the current structured-text email demo. Do not attach
the browser-print output: the pipeline cannot read or verify it.

- [ ] Confirm with the team whether PDF or DOCX is the required distributable
  format. Record the decision before selecting a renderer.
- [ ] Define a local exporter interface that consumes only the immutable
  `mom/approved.json` snapshot and produces deterministic server-readable
  bytes.
- [ ] Select and lock an offline-capable renderer. Vendor or preinstall all
  required Romanian and Cyrillic fonts and verify licensing, pagination, and
  glyph coverage before the demo.
- [ ] Persist the generated artifact under the job directory with media type,
  byte count, and SHA-256 descriptor. Never regenerate it from a later draft.
- [ ] Extend `LocalMailMessage` and the SMTP adapter with an explicit attachment
  model, safe filename handling, and size limits.
- [ ] Attach only the persisted approved artifact and test MIME type, filename,
  bytes/hash, multilingual rendering, retry behavior, and absence when export
  fails.
- [ ] Decide whether export failure blocks final delivery or falls back to the
  structured-text body. The UI must describe the actual outcome and must not
  claim an attachment that was not sent.

## P2.2 — Sender policy beyond the demo

The existing fixed identity check is appropriate only for the hackathon
profile.

- [x] Keep the browser unable to provide `From`.
- [x] Document the demo policy explicitly: system sender for draft-ready
  notifications; configured demo submitting author for approved-MoM delivery.
- [ ] Before institutional deployment, choose authenticated SMTP submission,
  an on-premise relay allowlist, or another locally authorized delegated-send
  mechanism with the hospital mail administrator.
- [ ] Bind submitter identity to authenticated server-side context and enforce
  per-user send-as rights. Full SSO remains a separate product decision.
- [ ] Add audit-safe sender authorization events without credentials or
  meeting content.

## Documentation and contract reconciliation

Complete these updates in the same increment as the behavior they describe:

- [x] Update `apps/mailpit/README.md` with notification configuration,
  Message-ID inspection, recovery semantics, and the final live commands.
- [x] Update pipeline `.env.example`, README, architecture, scope, API spec,
  artifact schemas, implementation plan, and technical decision log.
- [x] Correct the frontend README and API-alignment documentation: the local
  directory endpoint is already implemented and live autocomplete no longer
  uses the browser list as its primary source.
- [ ] Keep `apps/MAILPIT_RECIPIENT_DELIVERY_PLAN.md` as the implemented
  approval/delivery contract unless that contract actually changes.
- [ ] Re-run pipeline tests, source compilation, OpenAPI export/synchronization,
  frontend typecheck, live-mode build, and the offline smoke checklist after
  every public-contract change.

## Expected implementation touchpoints

Keep each increment narrow; do not mix P1 or P2 contract changes into the P0
notification work.

| Increment | Primary files or modules |
| --- | --- |
| P0.1 review link | `apps/pipeline/src/secure_mom_pipeline/config.py`, pipeline `.env.example`, frontend `src/state/store.tsx`, and focused frontend restoration tests |
| P0.2 notification models and rendering | Pipeline `models.py`, a small notification composer beside `mom_email.py`, `mail_adapter.py` only if acceptance classification must expand, and artifact-schema documentation |
| P0.2 notification lifecycle | Pipeline `api.py` for durable intent creation, `worker.py` for submission/recovery, `job_store.py` only if a new atomic claim primitive is required, and pipeline tests |
| P0.3 live proof | `apps/mailpit/README.md`, its existing Makefile/scripts where necessary, and a non-sensitive manual smoke checklist |
| P1 directory hardening | Pipeline `directory.py`, `models.py`, `api.py`, OpenAPI snapshot, frontend API types, recipient picker, and mock/live directory behavior |
| P2 attachment | A new server-side exporter boundary, `models.py`, `mail_adapter.py`, `mom_email.py`, approval flow, artifact documentation, and multilingual render fixtures |

## Demo-critical definition of done

P0 is complete only when all of the following are demonstrated on the target
Mac with networking disabled:

1. A new recording reaches `AWAITING_REVIEW / review_ready` with durable draft,
   review context, and one notification intent.
2. Mailpit contains one safe draft-ready message to the configured submitting
   author, and normal callback/restart replay does not create another.
3. Its stable local link opens the correct draft in a fresh browser session.
4. Approval with no accepted recipients performs no final SMTP submission.
5. Approval with accepted recipients produces one local final message with the
   authorized submitting author in `From`, the accepted people in `To`, and
   content derived only from the approved MoM.
6. Missing or invalid recipients, Mailpit downtime, retries, and process
   restarts preserve honest state and never discard a valid draft or approved
   snapshot.
7. The full run uses no external service and all automated tests and builds
   pass.

Immutable recipient IDs, a PDF/DOCX attachment, institutional SSO, and a real
delegated-sending policy are explicitly not required to declare the hackathon
P0 email flow complete.
