# Pipeline scope

Status: accepted MVP boundary  
Last updated: 26 September 2026

## In scope

- Local HTTP control API for the frontend.
- Upload and local persistence of one meeting recording per job.
- Filesystem-backed job creation, queueing, state, checkpoints, and errors.
- A separate worker process that claims and executes one job at a time.
- A dedicated adapter for the audio-processing ML service.
- A dedicated adapter for the text-processing ML service.
- Asynchronous submission and status polling for both ML services.
- Passing local filesystem paths to ML services on the same MacBook.
- Validation and persistence of a plain-text transcript.
- Validation and persistence of a draft MoM JSON document.
- Read endpoints for job status and completed artifacts.
- Configurable local ML endpoint URLs, ports, polling intervals, and timeouts.
- Health and readiness checks needed to verify the local pipeline before a demo.
- Recovery from process interruption using persisted state and valid artifacts.
- A single automatic retry for transient ML connection failures.
- A manual retry operation from the last valid checkpoint, subject to the draft
  API being confirmed.
- Local development, tests, dependency manifests, and offline setup guidance for
  the presentation MacBook.

## Pipeline completion boundary

The pipeline is complete when it has persisted and exposed a review-ready draft
MoM JSON artifact.

The frontend may display and edit that draft and may create ODF or DOCX files.
Those editing and export functions are not pipeline responsibilities.

## Out of scope for the MVP

- Running either ML model inside the pipeline process.
- Direct communication between the two ML services.
- Frontend implementation or frontend technology selection.
- Saving user edits to the MoM in the pipeline.
- Human approval workflow.
- ODF or DOCX generation.
- Email delivery or SMTP integration.
- User accounts, authentication, authorization, and multi-user workflows.
- Cancellation of running jobs.
- Job deletion and automatic retention cleanup.
- Parallel or overlapping job execution.
- A database, Redis, RabbitMQ, Kafka, or another external queue.
- Docker or Docker Compose as a current requirement.
- Cloud services, external inference, external telemetry, or runtime internet
  access.
- Audio recording transfer from phones or other capture devices.
- Audio enhancement and noise-removal stages.
- A finalized MoM content schema.
- Evidence linking and statement-level traceability metadata.
- Automatic identification of unnamed speakers.

## Deferred decisions

- Local SMTP and distribution-list delivery.
- Whether the final application is run directly or packaged in containers.
- Final ODF/DOCX generation approach in the frontend workstream.
- Additional meeting categories beyond clinical, financial, administrative,
  executive, operational, and urgent-crisis workflows.
- Data retention, cleanup, and deletion behavior beyond the hackathon.
- A stricter policy for logging meeting-derived content.
