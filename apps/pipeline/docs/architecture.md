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
   | adapter A: submit                               |
   +----------> Audio-processing ML service --------+
   |             | completed transcription bytes    |
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

The implemented audio completion boundary is instead a pipeline callback that
accepts the transcription as a small byte body correlated by pipeline and audio
model job IDs. The text adapter accepts the persisted UTF-8 `.txt` path
internally and translates it into a multipart upload.

These are internal concepts, not a mandatory REST contract for ML owners.

The current audio submission uses a mock adapter that acknowledges a readable
absolute local path, returns a generated `mock-audio-...` job ID, and sends a
deterministic transcription to the real pipeline callback after a configurable
five-second delay. A restarted worker re-schedules the callback for a persisted
mock job still at `audio_processing`. After the callback, the worker persists
the source bytes, strictly decodes UTF-8 without parsing JSON or CSV, writes
`transcript/transcript.txt`, and uploads that file to the text/MoM service.

The development text/MoM mock returns a generated `mock-text-...` job ID and
sends a deterministic two-field JSON document to the pipeline callback after a
configurable five-second delay. Worker recovery re-schedules this callback for
persisted jobs still at `text_processing`.

Both services behave asynchronously: submission acknowledges work without
holding the request open for inference, and each service pushes completion to a
correlated pipeline callback.

## Artifact movement

The pipeline owns the canonical job directory. The audio service reads the
recording from the shared local filesystem. Intermediate transcription data is
transferred over local HTTP.

```text
recording file path -> audio service
transcription byte body -> pipeline callback
transcript.txt multipart upload -> text service
draft MoM JSON body -> pipeline callback
```

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
