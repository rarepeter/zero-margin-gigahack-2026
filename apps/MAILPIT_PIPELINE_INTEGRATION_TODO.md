# Temporary — Mailpit/pipeline integration checklist

Delete this file after the Mailpit delivery flow is implemented and verified.

## Already available

- `apps/mailpit/` provides a Docker-based, loopback-only local Mailpit SMTP
  environment on `127.0.0.1:1025` and inbox UI on `127.0.0.1:8025`.
- The pipeline already persists the server-side submitting-author email and
  reaches `AWAITING_REVIEW` after a draft MoM is available.
- The portal has a temporary static recipient picker.

## Remaining implementation work

### 1. Add pipeline mail configuration and adapter — implemented

- Add `PIPELINE_MAIL_HOST`, `PIPELINE_MAIL_PORT`, and any bounded-timeout
  settings to the pipeline configuration.
- Implement a replaceable local SMTP adapter using Python's standard
  `smtplib` and `EmailMessage`; do not make the pipeline depend on Mailpit's
  HTTP API.
- Configure the demo adapter to send to `127.0.0.1:1025` without STARTTLS.
- Do not add cloud email APIs, external SMTP endpoints, relaying, or
  forwarding.

### 2. Notify the submitting author when review begins

- After `mom/draft.json` and `review/context.json` are durable, create a
  persisted notification intent and send exactly one local email to the
  server-side `submitted_by.email`.
- The notification must contain only safe text, a local review link, and a job
  identifier; it must not contain the MoM or transcript.
- Persist a stable message ID and metadata-only result so callback replay or a
  restart cannot create duplicate notifications.
- Record a clear retryable/non-retryable delivery failure without discarding a
  valid draft.

### 3. Introduce a server-owned recipient directory

- Store a minimal local directory with immutable IDs, display names, emails,
  and optional role/title. Use only test addresses such as `@medpark.test` in
  the demo.
- Add a surname-search endpoint, e.g. `GET /api/v1/directory?q=popescu`, with
  a small result limit.
- Replace the browser-only static directory as the source of truth.
- Validate submitted recipient IDs on the server; if typed addresses remain
  supported, restrict and validate them against the permitted internal domain.

### 4. Add approval and final delivery — implemented

- Keep the existing `POST /api/v1/jobs/{jobId}/approve` request for both
  branches. An empty recipient list approves without email; a non-empty list
  continues into local delivery in the same operation.
- Persist one immutable approved MoM snapshot with the accepted and softly
  skipped recipients. Invalid or out-of-policy domains do not block approval;
  the backend omits them from SMTP delivery and reports them in the response.
- Compose the final email from the approved MoM and supported meeting
  information only; do not invent missing metadata.
- Do not attach the browser-print PDF. Attach a final document only after a
  server-readable PDF/DOCX export contract exists.
- Set `From` to the stored submitting-author email only after server-side
  authorization validates that identity. Never accept an arbitrary sender from
  the browser.
- Mark `COMPLETED` only after local SMTP accepts the delivery request. Preserve
  the approved artifact if delivery fails; an identical `/approve` request
  retries that same delivery.

### 5. Connect the review portal — partially implemented

- Change recipient autocomplete to call the local directory endpoint.
- Change the same final action by recipient count: **Approve and download**
  with no recipients and **Approve and send** with one or more.
- Show delivery success only after the approval API responds
  successfully; otherwise show a clear retryable error.

### 6. Verify locally and offline

- Start Mailpit from `apps/mailpit` with `make verify`.
- Confirm draft-ready notification reaches the submitting author's test
  address in the Mailpit UI.
- Confirm the approved MoM message has the submitting author in `From`, the
  selected people in `To`, and the final document attachment when implemented.
- Test duplicate callback replay, invalid/external recipient soft skipping, Mailpit
  downtime, and a full Wi-Fi-disabled demo run.
- Run the pipeline and frontend automated tests, add integration coverage for
  the mail adapter and delivery state, then regenerate relevant OpenAPI files.

## Definition of done

With Wi-Fi disabled, a recording reaches review; the submitting author receives
one local ready-for-review email; the author finds recipients by surname,
approves the MoM, and Mailpit shows the final message from that author to the
selected recipients. No external service receives meeting data.
