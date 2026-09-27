# Secure MOM pipeline

This directory contains the backend control API and worker that coordinate the
local Secure MOM processing flow.

The pipeline accepts one meeting recording, stores a filesystem-backed job,
invokes two independently operated local ML services, and supports human
approval with optional local email delivery. This project also contains the
local MoM service (`src/secure_mom_llm`), which runs the text stage.

```text
audio upload
    -> local audio-processing service (mock for now)
    -> pushed transcription JSON (`schemaVersion: 1`)
    -> derived UTF-8 transcript.txt
    -> local MoM service: Muse Glimmer 30B Q4_K_M on llama.cpp
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
with the structured transcription to the local MoM service. The service pushes
its versioned result to a second correlated integration endpoint, or a failure
to a third; the pipeline validates and atomically
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

The text stage is real: the local MoM service generates the draft with Muse
Glimmer 30B on this machine. See [The local MoM service](#the-local-mom-service).
The persisted draft, structured transcript, and compact review context are
available through separate read endpoints.

Set `PIPELINE_MOCK_CALLBACK_TRANSPORT=http` to make the audio mock use an actual
HTTP callback instead. This mode is useful for testing process networking and
requires the worker to reach the configured pipeline API callback base URL. The
MoM service always uses the HTTP callback endpoints.

After review, `POST /api/v1/jobs/{jobId}/approve` persists one immutable
approved snapshot. With no accepted recipients it completes without email. With
accepted recipients it sends through local SMTP and completes only after SMTP
acceptance; a delivery failure preserves the approval for an identical-request
retry. Manual ML retry and readiness remain mock or unimplemented.

## Local mail adapter

The pipeline uses a replaceable standard-library SMTP boundary for approved-MoM
delivery. It does not call Mailpit's HTTP API. The offline demo defaults are:

```text
PIPELINE_MAIL_HOST=127.0.0.1
PIPELINE_MAIL_PORT=1025
PIPELINE_MAIL_TIMEOUT_SECONDS=5.0
PIPELINE_MAIL_USE_STARTTLS=false
PIPELINE_MAIL_ALLOWED_RECIPIENT_DOMAINS=medpark.test
```

The timeout bounds socket connection and SMTP commands. `apps/mailpit` binds
the corresponding SMTP listener to loopback only; no cloud mail API, relay, or
forwarding behavior is added by this adapter. Malformed or non-allowlisted
recipients are reported as skipped and do not prevent approval. The sender is
read from the stored demo submitter and checked server-side; it is never taken
from the browser request.

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
- pushed completion callbacks from both ML stages
- one adapter per ML service; real-service HTTP adapter contracts remain
  isolated from the worker
- externally started ML services configured by local endpoint URL and port
- direct MacBook execution first; Docker is not currently required

These points describe the accepted target architecture. The current pipeline
continues from the review-ready draft through approval and optional local SMTP
delivery.

## Local setup

The project targets Python 3.12. From this directory:

```bash
uv sync
cp .env.example .env
```

The application reads the environment variables shown in `.env.example`.
Loading a `.env` file automatically is not implemented; export the variables in
the shell or use a local environment runner.

Start the API, the worker, and the MoM service in separate shells:

```bash
uv run pipeline-api
uv run pipeline-worker
MOM_LLM_MODEL_PATH=~/Models/meta-models/Muse-Glimmer-30B-GGUF/Muse-Glimmer-30B-KQuant-17GB-Q4_K_M.gguf \
  uv run mom-llm-service
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
`review/context.json`. Approved jobs also contain `mom/approved.json`; delivery
attempts add `delivery/result.json`. State and artifact installation are atomic.

## The local MoM service

`uv run mom-llm-service` listens on `127.0.0.1:8102`, where the worker's
`PIPELINE_TEXT_SERVICE_URL` points, and starts llama.cpp's `llama-server` with
the model at `MOM_LLM_MODEL_PATH`. The model stays loaded between jobs;
`GET /health` reports `loading`, `ready`, or `failed`. Stopping the service
stops `llama-server`.

Install the runtime and model while online:

```bash
brew install llama.cpp   # tested with 0.5.0
hf download meta-models/Muse-Glimmer-30B-GGUF Muse-Glimmer-30B-KQuant-17GB-Q4_K_M.gguf \
  --local-dir ~/Models/meta-models/Muse-Glimmer-30B-GGUF
```

For each job the service:

1. Accepts the pipeline's multipart submission (`transcript.txt`, the
   structured transcription, and `uploadedAt`), persists it under
   `MOM_LLM_STORAGE_ROOT`, and answers `202` at once.
2. Numbers the transcript segments and lets the model reason on its private
   channel, up to `MOM_LLM_REASONING_MAX_TOKENS`.
3. Has the model write the draft as JSON under a grammar compiled from
   `draft.py`, so the output always parses and cites existing segments.
4. Builds the MoM: segment IDs, timestamps, speakers, meeting date, duration,
   and language shares come from the transcription, never from the model. A
   quote the cited segment does not contain is replaced by that segment's
   text. An action with no owner, or with a spoken deadline the model did not
   flag, gets a non-blocking flag, so a date the model inferred is marked as
   needing confirmation.
5. Pushes the MoM to the pipeline's MoM callback. If generation fails, it
   pushes a safe error to the failure callback, and the job becomes `FAILED`.

Both phases stream from `llama-server` with no read timeout, so a long meeting
runs to completion; progress is logged every 30 seconds. Model loading also
waits as long as the process lives. Logs hold job IDs, token counts, and
timings, never meeting content. Every setting is listed in `.env.example`
under `MOM_LLM_`.

The MoM is written in Romanian (`MOM_LLM_OUTPUT_LANGUAGE=ro`); `ru` and `en`
are also available. There is no confidence calibration yet, so
`momConfidence` is `null`.

Measured on a MacBook Pro M4 Pro with 48 GB, llama.cpp 0.5.0: the model loads
in about 11 seconds from disk, prompts are processed at about 120 tokens per
second, and output is generated at about 14 tokens per second. MoM stage time
with the default `medium` reasoning, using fictional benchmark transcripts:

| Transcript | Words | Prompt tokens | Reasoning tokens | Answer tokens | MoM stage |
| --- | --- | --- | --- | --- | --- |
| Audio-mock demo, 6 segments | 110 | 1,876 | 3,080 | 1,376 | 5.5 min |
| `clinical-01`, about 9 minutes of speech | 1,348 | 4,259 | 3,170 | 4,029 | 9.2 min |
| `executive-03`, about 40 minutes of speech | 5,937 | 12,792 | 2,901 | 5,097 | 11.6 min |

Reasoning stays near 3,000 tokens at `medium`, while the answer grows with the
meeting. `MOM_LLM_REASONING_STRENGTH=low` cuts reasoning to under 1,000 tokens:
the demo took 2.3 minutes and `clinical-01` 7.8 minutes, with a differently
structured but still correct draft. The benchmark scored `medium`.

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
idempotency, structured-transcript extraction, the multipart text submission,
the delayed audio mock callback, versioned JSON validation, confidence
propagation, review-context projection, atomic checkpoints, restart recovery,
status reads, event ordering, concurrent locking, non-blocking scheduling,
transient retry, and safe failures. The MoM service tests run the full
pipeline round trip with a stand-in for the model, plus evidence checking,
failure reporting, and byte-identical resends after a restart. They do not
load the model.

All source dependencies must be declared and installable before the offline
demo, and the model file must be on disk.
