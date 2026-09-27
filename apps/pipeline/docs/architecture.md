# Pipeline architecture

Status: accepted direction with explicitly open contracts  
Last updated: 27 September 2026

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
   | adapter A: submit                               |
   +----------> Audio-processing ML service --------+
   |             | transcription JSON (schema 1)      |
   |<------------+                                   |
   |                                                |
   | adapter B: multipart .txt submit                |
   +----------> Text-processing ML service ---------+
   |             | completed draft MoM JSON          |
   |<------------+                                   |
```

All components run on the same physical MacBook. The ML services are started
outside the pipeline and configured by local endpoint URL and port. Neither ML
service calls the other.

After the draft becomes review-ready, the portal lets the reviewer edit and
approve the draft and optionally select recipients from its local demo
directory. One approval request carries the edited document and current
recipient list. The backend softly skips malformed or non-allowlisted
addresses. With no accepted recipients it persists the approval and performs no
mail operation. With at least one accepted recipient it composes the final
message from the approved MoM and supported meeting information and hands it to
the local SMTP adapter using the stored, authorized submitter identity. The
portal, mail adapter, and all message data remain within the local environment.

## Process responsibilities

### Control API

- validate and persist an uploaded audio file;
- create a server-generated job ID and initial state;
- return immediately after the job is safely queued;
- expose job state and completed artifacts as versioned JSON;
- expose health/readiness information; and
- avoid executing long-running ML work in an API request.

### Worker

- claim one queued job atomically;
- resume from the latest valid persisted checkpoint;
- invoke each ML service through its dedicated adapter;
- receive the audio service's completed transcription callback;
- submit the resulting `.txt` file to the text service and receive its completed
  draft MoM callback;
- validate outputs before accepting a checkpoint;
- persist transcript and MoM artifacts atomically;
- record stage, timing, and safe error information; and
- advance one immediately actionable checkpoint at a time without letting jobs
  waiting on an ML service block other jobs.

### ML adapters

The external contracts may differ. Each adapter presents a small common
interface to the worker while translating to its service's actual endpoints and
payloads.

Conceptual audio adapter operations:

```text
health()
submit(pipeline_job_id, local_input_path) -> model_job_id
get_status(model_job_id) -> pending | running | completed | failed
get_result(model_job_id) -> local path or response payload
```

The implemented audio completion boundary is a pipeline callback that accepts a
validated schema-version-1 transcription JSON body correlated by pipeline and audio
model job IDs. The text adapter accepts the derived UTF-8 `.txt` path internally
and translates it into a multipart upload.

These are internal concepts, not a mandatory REST contract for ML owners.

The current audio submission uses a mock adapter that acknowledges a readable
absolute local path, returns a generated `mock-audio-...` job ID, and sends a
deterministic structured transcription to the real pipeline callback after a
configurable five-second delay. A restarted worker re-schedules the callback for
a persisted mock job still at `audio_processing`. After the callback, the worker
persists `transcript/source.json`, extracts its complete `transcript.text` into
`transcript/transcript.txt`, and uploads that file to the text/MoM service.

The development text/MoM mock returns a generated `mock-text-...` job ID and
sends a deterministic schema-version-1 MoM JSON document with `momConfidence` to the
pipeline callback after a configurable five-second delay. Worker recovery
re-schedules this callback for persisted jobs still at `text_processing`.

Both services behave asynchronously: submission acknowledges work without
holding the request open for inference, and each service pushes completion to a
correlated pipeline callback.

For reliable local development, the embedded mocks route their delayed requests
through the same FastAPI callback handlers using an in-process ASGI transport by
default. This exercises request validation, correlation, persistence, and state
transitions without requiring a TCP connection between the worker and API
process. An optional HTTP mock transport exercises real loopback networking.
This development transport choice does not change the real-service boundary:
independently started ML services deliver their results to the documented HTTP
callback endpoints.

## Artifact movement

The pipeline owns the canonical job directory. The audio service reads the
recording from the shared local filesystem. Intermediate transcription data is
transferred over local HTTP.

```text
recording file path -> audio service
transcription JSON (schema 1) -> pipeline callback
transcript.txt multipart upload -> text service
MoM JSON (schema 1) -> pipeline callback
```

At the review-ready checkpoint, the pipeline also persists compact
`review/context.json` metadata. The public review-context endpoint omits the
submitter email and links to the separately loaded structured transcript and
draft MoM resources. This data contract does not add a new workflow state.

The exact request and result shapes belong to their adapters. The audio service
must have operating-system permission to read its recording input path. The
text service does not need access to the pipeline's filesystem.

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

`AWAITING_REVIEW` means the draft MoM JSON is available to the frontend. The
approval request may briefly use `AWAITING_REVIEW / delivery_sending` while a
local SMTP transaction is in progress. `COMPLETED / approved` means the MoM was
approved with no accepted recipients, so no email was attempted.
`COMPLETED / delivered` means the same approved snapshot was accepted by local
SMTP for at least one recipient. An SMTP failure preserves the approved
artifact and moves the job to `FAILED / delivery_failed`; the identical
approval request is the delivery retry boundary.

State updates use a temporary file followed by an atomic rename. Artifacts are
validated and atomically installed before the state advances. A process restart
must inspect persisted state and artifacts rather than starting a job again from
the beginning without cause.

Initial job creation uses a stronger publication boundary: the API writes the
audio, state, and initial events under the storage root's staging directory and
atomically renames the complete directory into `jobs/`. The worker scans only
published job directories.

The worker may have multiple jobs in externally active states. On each pass it
re-schedules any required mock callbacks, advances the oldest actionable
transcription or text-dispatch checkpoint, or claims the oldest queued job.
Per-job locks serialize API and worker mutations; an unrelated job waiting in
`audio_processing` or `GENERATING_MOM` does not occupy a global processing slot.

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
