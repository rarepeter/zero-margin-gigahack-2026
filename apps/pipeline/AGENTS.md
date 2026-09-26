# Pipeline contributor guidance

Read the documents in `docs/` before changing this application. In particular,
check `docs/technical-decisions.md` before treating a discovery idea as a fixed
requirement.

## Product boundary

The pipeline owns the flow from an uploaded meeting recording through a
persisted draft MoM JSON artifact. It does not own frontend editing, ODF/DOCX
export, final approval, or email delivery.

The two ML systems are independent, externally started local services. They do
not call one another. The pipeline invokes each service through its own adapter,
validates and persists the returned artifact, and passes that artifact to the
next stage.

## Constraints

- Runtime must remain local and usable offline on the presentation MacBook.
- Do not add cloud inference, external storage, external telemetry, or external
  SMTP dependencies.
- Long-running work must not execute in the frontend-facing request lifecycle.
- Treat both ML integrations as asynchronous; current completion artifacts are
  delivered through correlated pipeline callbacks.
- Keep mutations serialized per job, but do not let a job waiting on an ML
  service prevent other queued or actionable jobs from advancing.
- Persist state changes atomically and preserve valid checkpoints across
  process restarts.
- Keep runtime recordings, transcripts, MoM output, logs, secrets, model
  weights, caches, and machine-specific paths out of Git.
- Declare source dependencies in the project manifest and lock them before the
  offline demo.

## Current technology direction

Use Python 3.12, FastAPI, Pydantic, Uvicorn, `uv`, and pytest unless the decision
log is deliberately updated. These are open-source tools suitable for local
MacBook development and execution.

Run the API and worker as separate processes. Use local job directories rather
than a database or external queue. ML endpoint URLs and ports must be supplied
through configuration, not hard-coded.

## Specification discipline

The public API routes and detailed MoM `document` schema remain drafts. Keep
their version markers and avoid inventing clinical, financial, administrative,
or operational fields or making provisional shapes appear final. The accepted
audio result is `transcription.v1alpha1` JSON; `transcript.text` is derived into
plain text only for the MoM service. The accepted MoM envelope is
`mom.v1alpha1`, and compact portal metadata is `review-context.v1alpha1`.
Traceability/recommendation metadata, content-logging policy, deployment
containers, SMTP, and the definitive MoM `document` schema remain unresolved or
deferred.
