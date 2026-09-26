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

The repository contains a deliberately non-functional baseline: a dummy HTTP
API, a mock worker, basic byte/text filesystem services, local operational
logging, and provisional OpenAPI documents. The HTTP handlers only log that an
operation was triggered and return dummy content. They do not create jobs,
persist state, invoke ML services, or validate artifacts.

The API, worker behavior, paths, and ML contracts remain discovery items. See
[Discovery TODOs](docs/discovery-todos.md) before relying on any placeholder.

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
- one adapter per ML service; their external contracts may differ
- externally started ML services configured by local endpoint URL and port
- direct MacBook execution first; Docker is not currently required

These points describe the accepted target architecture. The current baseline
does not implement orchestration, model integration, persistence, or recovery.

## Local setup

The project targets Python 3.12. From this directory:

```bash
uv sync
cp .env.example .env
```

The application reads the environment variables shown in `.env.example`.
Loading a `.env` file automatically is not implemented; export the variables in
the shell or use a local environment runner.

Start the dummy API and mock worker in separate shells:

```bash
uv run pipeline-api
uv run pipeline-worker
```

The API defaults to `127.0.0.1:8000`. This bind address and port are provisional
and marked for discovery in the source.

Run one finite mock-worker cycle with:

```bash
uv run pipeline-worker --once
```

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

## Manual smoke check

Automated tests are intentionally out of scope for this baseline. The approved
smoke check verifies process startup, dummy endpoint responses and logging,
filesystem byte/text round trips, and JSON readability of all OpenAPI files.

All source dependencies must be declared and installable before the offline
demo. Model installation and operation remain the responsibility of the ML
components.
