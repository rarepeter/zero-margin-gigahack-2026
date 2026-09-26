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

The pipeline is in specification and repository-preparation stage. No runtime
implementation exists here yet. The API and MoM schema are intentionally marked
as drafts until the frontend and ML integration contracts are confirmed.

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

All source dependencies must be declared and installable before the offline
demo. Model installation and operation remain the responsibility of the ML
components.

