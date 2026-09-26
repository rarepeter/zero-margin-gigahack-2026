# Pipeline architecture

Status: accepted direction with explicitly open contracts  
Last updated: 26 September 2026

## System shape

```text
Frontend
   |
   | local HTTP: create job and poll status
   v
Pipeline control API
   |
   | atomically writes queued job state
   v
Local job filesystem <------------------------------+
   ^                                                |
   | claims job and writes checkpoints              | persists artifacts
   |                                                |
Pipeline worker                                     |
   |                                                |
   | adapter A: submit and poll                      |
   +----------> Audio-processing ML service --------+
   |                                                |
   | adapter B: submit and poll                      |
   +----------> Text-processing ML service ---------+
```

All components run on the same physical MacBook. The ML services are started
outside the pipeline and configured by local endpoint URL and port. Neither ML
service calls the other.

## Process responsibilities

### Control API

- validate and persist an uploaded audio file;
- create a server-generated job ID and initial state;
- return immediately after the job is safely queued;
- expose job state and completed artifacts as JSON or plain text as appropriate;
- expose health/readiness information; and
- avoid executing long-running ML work in an API request.

### Worker

- claim one queued job atomically;
- resume from the latest valid persisted checkpoint;
- invoke each ML service through its dedicated adapter;
- poll each service until it completes, fails, or times out;
- validate outputs before accepting a checkpoint;
- persist transcript and MoM artifacts atomically;
- record stage, timing, and safe error information; and
- process no more than one job at a time.

### ML adapters

The external contracts may differ. Each adapter presents a small common
interface to the worker while translating to its service's actual endpoints and
payloads.

Conceptual adapter operations:

```text
health()
submit(pipeline_job_id, local_input_path) -> model_job_id
get_status(model_job_id) -> pending | running | completed | failed
get_result(model_job_id) -> local path or response payload
```

These are internal concepts, not a mandatory REST contract for ML owners.

The current implementation stops after a mock audio adapter acknowledges a
readable absolute local path. It returns a generated `mock-audio-...` job ID and
does not read or process the recording. This keeps the orchestration boundary
executable without presenting the discovery-only audio OpenAPI document as an
agreed service contract.

Both services must behave asynchronously: submission acknowledges work without
holding the request open for the full inference duration, and completion is
observed through polling.

## Artifact movement

The pipeline owns the canonical job directory. ML requests refer to local files
on the shared MacBook rather than uploading artifacts through HTTP.

```text
recording file path -> audio service
transcript file path -> text service
```

The exact request and result shapes belong to their adapters. Each service must
have operating-system permission to read its input path. If containerization is
adopted later, shared-volume mounting and path translation must be designed and
documented before it replaces this assumption.

## State and recovery

The API creates a job only after the audio upload has been validated and safely
persisted. The accepted external states are:

```text
QUEUED
TRANSCRIBING
GENERATING_MOM
AWAITING_REVIEW
COMPLETED
FAILED
```

For the current pipeline boundary, `AWAITING_REVIEW` means the draft MoM JSON is
available to the frontend. `COMPLETED` is reserved for future alignment with the
frontend review/export workflow and may not be emitted by the initial pipeline.
This distinction must be resolved when the public API is finalized.

State updates use a temporary file followed by an atomic rename. Artifacts are
validated and atomically installed before the state advances. A process restart
must inspect persisted state and artifacts rather than starting a job again from
the beginning without cause.

Initial job creation uses a stronger publication boundary: the API writes the
audio, state, and initial events under the storage root's staging directory and
atomically renames the complete directory into `jobs/`. The worker scans only
published job directories.

## Retry behavior

- Retry a transient connection failure once automatically.
- Do not automatically retry a structurally invalid ML result.
- Enforce configurable stage timeouts and polling intervals.
- Preserve inputs, valid checkpoints, and safe failure information.
- A manual retry should continue from the last valid checkpoint rather than
  recomputing accepted work.

The exact error taxonomy and retry endpoint remain part of the draft API work.

## Runtime and dependency direction

The initial target is direct execution on macOS using Python 3.12. FastAPI,
Pydantic, Uvicorn, `uv`, and pytest are open-source and accepted for the MVP.
Source dependencies must be declared in a manifest and locked. All packages and
model assets needed for the demonstration must be installed before the machine
is taken offline.

Docker is neither required nor rejected permanently. It is deferred until the
team knows whether direct execution is sufficient on the presentation MacBook.
