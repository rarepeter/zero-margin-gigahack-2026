# Pipeline scope

Status: accepted MVP boundary  
Last updated: 27 September 2026

## In scope

- Local HTTP control API for the frontend.
- Upload and local persistence of one meeting recording per job.
- Filesystem-backed job creation, queueing, state, checkpoints, and errors.
- A separate worker process that claims and executes one job at a time.
- A dedicated adapter for the audio-processing ML service.
- A dedicated adapter for the text-processing ML service.
- Asynchronous submission to both ML services and correlated completion
  callbacks for the transcription and draft MoM artifacts.
- Passing the recording path to the audio service and uploading a `.txt` file to
  the text/MoM service.
- Atomic persistence of structured schema-version-1 transcription JSON and a derived
  UTF-8 plain-text input for the MoM service.
- Validation and persistence of a draft MoM JSON document.
- Persistence of compact review-context metadata when the draft becomes ready.
- A server-owned local demo directory, with backend recipient allowlist
  enforcement.
- Persisted, restart-safe notification of the submitting author through local
  SMTP when a draft becomes review-ready. The message contains only the job ID
  and stable loopback review link.
- Local delivery of the approved MoM to accepted recipients selected by the
  reviewer, using the stored and server-authorized submitter identity.
- Separate read endpoints for job status, review context, structured transcript,
  and draft MoM artifacts.
- Configurable local ML endpoint URLs, ports, polling intervals, and timeouts.
- Health and readiness checks needed to verify the local pipeline before a demo.
- Recovery from process interruption using persisted state and valid artifacts.
- A single automatic retry for transient ML connection failures.
- Non-blocking job scheduling: jobs waiting on an ML callback or result do not
  prevent other queued or actionable jobs from advancing.
- A manual retry operation from the last valid checkpoint, subject to the draft
  API being confirmed.
- Local development, tests, dependency manifests, and offline setup guidance for
  the presentation MacBook.

## Pipeline completion boundary

The processing stage is review-ready when the pipeline has persisted and
exposed a draft MoM JSON artifact. The approval stage uses one contract with an
optional recipient list. It completes without SMTP when no addresses survive
soft validation, or only after local SMTP accepts delivery when at least one
address survives. SMTP failure preserves the immutable approved snapshot for an
identical-request retry.

The notification outcome is independent of this completion boundary. A known
pre-submission SMTP failure may retry within a small bound; an interrupted or
acceptance-uncertain attempt is not automatically resent. In every case the
valid draft remains `AWAITING_REVIEW / review_ready`.

The frontend may display and edit that draft and may create ODF or DOCX files.
Those editing and export functions remain frontend responsibilities, while the
pipeline/backend owns local notification and delivery.

## Out of scope for the MVP

- Running either ML model inside the pipeline process.
- Direct communication between the two ML services.
- Frontend implementation or frontend technology selection.
- Incremental draft editing in the pipeline; it persists only the final approved snapshot submitted for delivery.
- ODF or DOCX generation.
- User accounts, authentication, authorization, and multi-user workflows.
- Cancellation of running jobs.
- Job deletion and automatic retention cleanup.
- Parallel execution inside the pipeline worker; it advances one local
  checkpoint at a time, although multiple jobs may overlap while external ML
  services are processing them.
- A database, Redis, RabbitMQ, Kafka, or another external queue.
- Docker or Docker Compose as a current requirement.
- Cloud services, external inference, external telemetry, or runtime internet
  access.
- Audio recording transfer from phones or other capture devices.
- Audio enhancement and noise-removal stages.
- Automatic identification of unnamed speakers.

## Deferred decisions

- Replacing the server-owned local demo directory with an institutional
  directory service and defining its privacy/authorization policy and stable
  person identifiers.
- Replacing the fixed demo submitter authorization check with institutional
  authentication and send-as/delegation policy.
- Whether the final application is run directly or packaged in containers.
- Final ODF/DOCX generation approach in the frontend workstream.
- Additional meeting categories beyond clinical, financial, administrative,
  executive, operational, and urgent-crisis workflows.
- Data retention, cleanup, and deletion behavior beyond the hackathon.
- Extraction reliability for embedded recording timestamps. If an audio model
  supplies `audioMetadata.recordedAt`, the pipeline preserves it; it never
  treats a copied file's filesystem creation time as the meeting date.
- Rich evidence spans, reviewer-resolution validation, and speaker-name
  substitution/persistence after review.
- A stricter policy for logging meeting-derived content.
