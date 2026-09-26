# Secure MOM pipeline

This directory contains the backend control API and worker that coordinate the
local Secure MOM processing flow.

The pipeline accepts one meeting recording, stores a filesystem-backed job,
invokes two independently operated local ML services, and finishes when a
review-ready draft MoM has been persisted as JSON.

```text
audio upload
    -> local audio-processing service
    -> transcript text
    -> local text-processing service
    -> draft MoM JSON
```

This is a 48-hour hackathon MVP, not a production hospital system. Runtime must
work on a MacBook without internet access after dependencies and models have
been installed locally.

## Current status

The job-creation path is functional through audio-service pickup. The API
streams an uploaded recording into an atomically published filesystem job and
returns `202 Accepted`. A separate worker discovers one queued job, passes its
local path to a replaceable mock audio-service adapter, and persists a
`TRANSCRIBING` checkpoint with a mock model job ID.

The transcript, MoM, retry, readiness, and real ML integration paths remain
mock or unimplemented. The audio-service contract is still a discovery item;
the current adapter acknowledges a readable local file without processing it.

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
- one active pipeline job at a time
- asynchronous public API and asynchronous ML integrations
- orchestration-side polling of both ML services
- one adapter per ML service; the audio adapter is currently a mock because its
  external contract is not agreed
- externally started ML services configured by local endpoint URL and port
- direct MacBook execution first; Docker is not currently required

These points describe the accepted target architecture. The current increment
implements persistence and mock audio pickup, not the later ML stages.

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
```

Jobs are stored below `PIPELINE_STORAGE_ROOT/jobs/<job-id>/`. Each contains
`state.json`, a server-named audio artifact under `input/`, and an append-only
`operations.ndjson` history. State and initial job publication are atomic.

## Filesystem services

`BinaryFileService` reads and writes unmodified bytes, including audio bytes.
`TextFileService` reads and writes UTF-8 text. Callers provide a root directory
and a relative file name; the services do not know or impose a job/artifact
layout. Paths escaping the supplied root are rejected.

## OpenAPI documents

- `docs/openapi/pipeline.openapi.json` is generated from the FastAPI app.
- `docs/openapi/audio-processing.openapi.json` is a discovery-only ML boundary.
- `docs/openapi/text-processing.openapi.json` is a discovery-only ML boundary.

Regenerate the pipeline document after changing the API:

```bash
uv run pipeline-export-openapi docs/openapi/pipeline.openapi.json
```

The ML documents intentionally use open objects and `TODO(discovery)` notices;
they are not contracts for the ML owners yet.

## Verification

Run the automated suite with:

```bash
uv run pytest
```

The tests cover upload validation and persistence, atomic job visibility,
status reads, event ordering, concurrent event appends, single-job worker
behavior, mock ML pickup, and safe dispatch failure.

All source dependencies must be declared and installable before the offline
demo. Model installation and operation remain the responsibility of the ML
components.
