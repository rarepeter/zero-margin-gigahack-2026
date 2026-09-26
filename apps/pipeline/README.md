# Secure MOM pipeline

This directory contains the backend control API and worker that coordinate the
local Secure MOM processing flow.

The pipeline accepts one meeting recording, stores a filesystem-backed job,
invokes two independently operated local ML services, and finishes when a
review-ready draft MoM has been persisted as JSON.

```text
audio upload
    -> local audio-processing service
    -> pushed transcription JSON (`schemaVersion: 1`)
    -> derived UTF-8 transcript.txt
    -> text-processing service
    -> pushed MoM JSON (`schemaVersion: 1`)
    -> review-ready MoM and compact context artifacts
```

This is a 48-hour hackathon MVP, not a production hospital system. Runtime must
work on a MacBook without internet access after dependencies and models have
been installed locally.

## Current status

The pipeline is functional from audio upload through a persisted draft MoM.
The API atomically publishes the uploaded recording, and a separate worker
passes its path to the replaceable mock audio adapter. The audio-to-text service
then pushes a structured transcription to a correlated integration endpoint.
The pipeline validates and preserves `transcript/source.json`, extracts its
complete transcript text into `transcript/transcript.txt`, and uploads that file
to the configured text/MoM service. The service pushes its versioned result to a
second correlated integration endpoint; the pipeline validates and atomically
stores `mom/draft.json` plus `review/context.json`, then advances to
`AWAITING_REVIEW / review_ready`.

In the runnable development flow, the mock audio adapter schedules that callback
five seconds after accepting a recording and sends a deterministic
schema-version-1 transcription mock result. If the worker restarts while a mock job is
still waiting, it re-schedules the callback from the persisted checkpoint. By
default, the mock routes the request through the real FastAPI callback handler
in-process, so development does not depend on loopback networking. The delay
and callback base URL are configurable with
`PIPELINE_MOCK_AUDIO_CALLBACK_DELAY_SECONDS` and
`PIPELINE_MOCK_AUDIO_CALLBACK_BASE_URL`.

The runtime text/MoM mock similarly accepts `transcript.txt`, waits five seconds,
and pushes a MoM object with `schemaVersion: 1`, `quality`, and
`document`. Its delay and callback base URL are independently configurable. The
persisted draft, structured transcript, and compact review context are available
through separate read endpoints.

Set `PIPELINE_MOCK_CALLBACK_TRANSPORT=http` to make both mocks use actual HTTP
callbacks instead. This mode is useful for testing process networking and
deployment wiring, and requires the worker to reach the configured pipeline API
callback base URLs. Real independently started ML services always use the HTTP
callback endpoints; the in-process option applies only to development mocks.

Manual retry and readiness remain mock or unimplemented.

## Documentation

- [Project brief](docs/project-brief.md)
- [Pipeline scope](docs/scope.md)
- [Architecture](docs/architecture.md)
- [Technical decisions](docs/technical-decisions.md)
- [Draft API specification](docs/api-spec.md)
- [Artifact specifications](docs/artifact-schemas.md)

The decision log is the source of truth for whether a choice is accepted,
provisional, deferred, or still open.

## Implementation direction

- Python 3.12, FastAPI, Pydantic, Uvicorn, `uv`, and pytest
- separate API and worker processes
- filesystem-backed state and artifacts; no application database
- one local checkpoint mutation at a time; jobs waiting on ML services do not
  block other jobs
- asynchronous public API and asynchronous ML integrations
- pushed completion callbacks from both development ML mocks
- one adapter per ML service; real-service HTTP adapter contracts remain
  isolated from the worker
- externally started ML services configured by local endpoint URL and port
- direct MacBook execution first; Docker is not currently required

These points describe the accepted target architecture. The current pipeline
stops after persisting a review-ready draft MoM JSON artifact.

## Local setup

The project targets Python 3.12. From this directory:

```bash
uv sync
cp .env.example .env
```

The application reads the environment variables shown in `.env.example`.
Loading a `.env` file automatically is not implemented; export the variables in
the shell or use a local environment runner.

Start the API and worker in separate shells:

```bash
uv run pipeline-api
uv run pipeline-worker
```

The API defaults to `127.0.0.1:8000`. This bind address and port are provisional
and marked for discovery in the source.

Attempt one queued job and exit with:

```bash
uv run pipeline-worker --once
```

## Create and inspect a job

The upload endpoint accepts `.mp3`, `.wav`, `.m4a`, `.aac`, `.flac`, `.ogg`,
`.opus`, `.webm`, and `.mp4` files up to 300 MiB. MIME type is advisory; the
pipeline preserves the bytes and does not decode or transcode them.

```bash
curl -F 'audio=@meeting.mp3' http://127.0.0.1:8000/api/v1/jobs
curl http://127.0.0.1:8000/api/v1/jobs/<job-id>
uv run pipeline-worker --once
curl --data-binary @transcription.json \
  -H 'Content-Type: application/json' \
  -H 'X-Audio-Model-Job-Id: <audio-model-job-id>' \
  http://127.0.0.1:8000/api/v1/integrations/audio/jobs/<job-id>/transcription
```

Authentication and SSO are outside this MVP. The pipeline uses the fixed local
demo submitter configured by `PIPELINE_DEMO_SUBMITTER_*`; the upload endpoint
does not accept or validate identity fields.

Jobs are stored below `PIPELINE_STORAGE_ROOT/jobs/<job-id>/`. Each contains
`state.json`, a server-named audio artifact under `input/`, source and `.txt`
transcription checkpoints under `transcript/`, and an append-only
`operations.ndjson` history. Review-ready jobs also contain `mom/draft.json` and
`review/context.json`. State and artifact installation are atomic.

## Filesystem services

`BinaryFileService` reads and writes unmodified bytes, including audio bytes.
`TextFileService` reads and writes UTF-8 text. Callers provide a root directory
and a relative file name; the services do not know or impose a job/artifact
layout. Paths escaping the supplied root are rejected.

## OpenAPI documents

- `docs/openapi/pipeline.openapi.json` is generated from the FastAPI app.
- `docs/openapi/audio-processing.openapi.json` defines the agreed structured
  transcription result and provisional service transport.
- `docs/openapi/text-processing.openapi.json` defines the agreed MoM envelope
  and the validated schema-version-1 review-document shape.

Regenerate the pipeline document after changing the API:

```bash
uv run pipeline-export-openapi docs/openapi/pipeline.openapi.json
```

The schema-version-1 MoM `document` object is a current validated portal contract.
Remaining ML-service transport details stay open.

## Verification

Run the automated suite with:

```bash
uv run pytest
```

The tests cover upload validation and persistence, callback correlation and
idempotency, structured-transcript extraction, multipart `.txt` upload, both
delayed mock callbacks, versioned JSON validation, confidence propagation,
review-context projection, atomic checkpoints,
restart recovery, status reads, event ordering, concurrent locking,
non-blocking scheduling, transient retry, and safe failures.

All source dependencies must be declared and installable before the offline
demo. Model installation and operation remain the responsibility of the ML
components.
