# Pipeline contributor guidance

Read the documents in `docs/` before changing this application. In particular,
check `docs/technical-decisions.md` before treating a discovery idea as a fixed
requirement.

## Product boundary

The pipeline owns the flow from an uploaded meeting recording through a
persisted draft MoM JSON artifact, notification of the configured submitting
author, and the local delivery boundary after the portal records approval. The
frontend owns draft editing, recipient interaction, and document presentation;
the precise approval and document-transfer contract remains to be defined.

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

The public API routes remain drafts, but the schema-version-1 MoM `document` is
now a validated portal contract. Keep its numeric version marker and avoid
inventing clinical, financial, administrative, or operational fields. The
accepted audio result is schema-version-1 transcription JSON; `transcript.text` is
derived into plain text only for the MoM service. The accepted MoM envelope is
schema-version-1 MoM JSON, and compact portal metadata is schema-version-1 review context.
Rich word-level recommendations, content-logging policy, deployment containers,
the local mail adapter contract, and recipient-directory source remain
unresolved.
