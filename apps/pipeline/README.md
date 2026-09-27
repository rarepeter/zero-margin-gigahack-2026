# Secure MOM pipeline

This directory contains the backend control API and worker that coordinate the
local Secure MOM processing flow.

The pipeline accepts one meeting recording, stores a filesystem-backed job,
invokes two independently operated local ML services, and supports human
approval with optional local email delivery. This project also contains both
local ML services: speech-to-text (`src/secure_mom_asr`) and MoM generation
(`src/secure_mom_llm`).

```text
audio upload
    -> local speech-to-text service: FraPiz + Whisper large-v3 on whisper.cpp
    -> pushed transcription JSON (`schemaVersion: 1`)
    -> derived UTF-8 transcript.txt
    -> local MoM service: Muse Glimmer 30B Q4_K_M on llama.cpp
    -> pushed MoM JSON (`schemaVersion: 1`)
    -> review-ready MoM, compact context, and notification intent
    -> one restart-safe generic notification through local SMTP
```

This is a 48-hour hackathon MVP, not a production hospital system. Runtime must
work on a MacBook without internet access after dependencies and models have
been installed locally.

## Current status

The pipeline is functional from audio upload through a persisted draft MoM.
The API atomically publishes the uploaded recording, and a separate worker
passes its path to the local speech-to-text service. That service pushes a
structured transcription to a correlated integration endpoint, or a failure to
another.
The pipeline validates and preserves `transcript/source.json`, extracts its
complete transcript text into `transcript/transcript.txt`, and uploads that file
with the structured transcription to the local MoM service. The service pushes
its versioned result to a second correlated integration endpoint, or a failure
to a third; the pipeline validates and atomically
stores `mom/draft.json` plus `review/context.json`, then advances to
`AWAITING_REVIEW / review_ready`. Before publishing that state it also stores a
content-free `notification/intent.json`. The worker claims and submits that
intent through local SMTP without changing the review-ready workflow state.

Both ML stages are real and run on this machine. See
[The local speech-to-text service](#the-local-speech-to-text-service) and
[The local MoM service](#the-local-mom-service). The persisted draft,
structured transcript, and compact review context are available through
separate read endpoints.

After review, `POST /api/v1/jobs/{jobId}/approve` persists one immutable
approved snapshot. With no accepted recipients it completes without email. With
accepted recipients it sends through local SMTP and completes only after SMTP
acceptance; a delivery failure preserves the approval for an identical-request
retry. Manual ML retry and readiness remain mock or unimplemented.

## Stable local review link

The offline demo portal origin is configured separately from the API:

```text
PIPELINE_PORTAL_BASE_URL=http://127.0.0.1:3100
```

The pipeline validates this as an HTTP(S) loopback URL and normalizes its base
path. `build_review_url(...)` produces a content-free
`?review=<encoded-job-id>` link for the draft-ready notification. The
current router-free portal restores that job in a fresh session, opens Review
only at `AWAITING_REVIEW / review_ready`, waits honestly for earlier states,
and converts completed jobs to the existing approved-document view. The link
is navigation, not authorization; authentication remains outside the MVP.

## Local mail adapter

The pipeline uses a replaceable standard-library SMTP boundary for approved-MoM
delivery. It does not call Mailpit's HTTP API. The offline demo defaults are:

```text
PIPELINE_MAIL_HOST=127.0.0.1
PIPELINE_MAIL_PORT=1025
PIPELINE_MAIL_TIMEOUT_SECONDS=5.0
PIPELINE_MAIL_USE_STARTTLS=false
PIPELINE_MAIL_ALLOWED_RECIPIENT_DOMAINS=medpark.test
PIPELINE_NOTIFICATION_SENDER=secure-mom@medpark.test
PIPELINE_NOTIFICATION_MAX_ATTEMPTS=2
```

The timeout bounds socket connection and SMTP commands. `apps/mailpit` binds
the corresponding SMTP listener to loopback only; no cloud mail API, relay, or
forwarding behavior is added by this adapter. Malformed or non-allowlisted
recipients are reported as skipped and do not prevent approval. The sender is
read from the stored demo submitter and checked server-side; it is never taken
from the browser request.

Draft-ready mail uses the configured system notification sender and goes only
to the persisted submitting author. Its body contains the job ID and stable
local review URL, never transcript or MoM content. The worker persists a
`sending` claim before SMTP. A failure known to occur before submission can be
retried within the configured bound; an interrupted or acceptance-uncertain
attempt becomes terminal `unknown` and is not automatically resent.

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

Start the API, the worker, and both ML services in separate shells:

```bash
uv run pipeline-api
uv run pipeline-worker
ASR_FRAPIZ_MODEL_PATH=~/Models/whisper.cpp/ggml-frapiz-large-v3-turbo-moldovan-romanian.bin \
ASR_FALLBACK_MODEL_PATH=~/Models/whisper.cpp/ggml-large-v3.bin \
  uv run asr-service
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
`review/context.json`, plus `notification/intent.json` and, after the worker
acts, `notification/result.json`. Approved jobs also contain
`mom/approved.json`; delivery attempts add `delivery/result.json`. State and
artifact installation are atomic.

## The local speech-to-text service

`uv run asr-service` listens on `127.0.0.1:8101`, where the worker's
`PIPELINE_AUDIO_SERVICE_URL` points. It ports Module 04 of the MedSpeech
research pipeline (`medspeech_main.py`) to whisper.cpp, which runs on the Mac
GPU through Metal. Two `whisper-server` children and the pyannote pipeline
stay loaded between jobs; `GET /health` reports their state.

Install the runtime and models while online:

```bash
brew install whisper-cpp ffmpeg   # tested with whisper.cpp 1.9.4
mkdir -p ~/Models/whisper.cpp && cd ~/Models/whisper.cpp
curl -LO https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3.bin
# Gated: accept the terms on huggingface.co first, then log in with `hf auth login`.
hf download pyannote/speaker-diarization-community-1 \
  --local-dir ~/Models/pyannote/speaker-diarization-community-1
```

FraPiz ([FraPiz/whisper-large-v3-turbo-moldovan-romanian](https://huggingface.co/FraPiz/whisper-large-v3-turbo-moldovan-romanian))
must be converted to ggml once with whisper.cpp's
`models/convert-h5-to-ggml.py`, which also needs a clone of `openai/whisper`
for its mel filters. The script reads `vocab.json`, which FraPiz stores inside
`tokenizer.json` as `model.vocab`; write it to a folder that links the other
model files, then run the script with `torch`, `transformers`, and `numpy`.
The result is a 1.5 GB f16 file. Point `ASR_LEXICON_PATH` at
`Moldova_Medical_Speech_Lexicon.json` (MMSL v0.2).

For each job the service:

1. Accepts the recording's absolute path, the result and failure callback
   URLs, and an `Idempotency-Key`, persists the job under `ASR_STORAGE_ROOT`,
   and answers `202` at once.
2. Converts the recording to 16 kHz mono PCM16 WAV and cuts it into
   contiguous segments at the midpoints of pauses of at least 0.8 s below
   `ASR_SILENCE_DB`: the latest pause 6–20 s in, otherwise the one nearest
   20 s up to 30 s, otherwise at 20 s. Each segment is decoded with 0.4 s of
   padding and, after the first, 2 s of the previous segment's audio.
3. Starts speaker diarization in parallel.
4. Runs FraPiz with Romanian forced: greedy, no previous-text context, no
   timestamp tokens, and no prompt unless `ASR_LEXICON_MODE=assisted`.
   whisper.cpp retries at a higher temperature only when its entropy check
   detects a loop.
5. Applies the Repeat Guard (letters, units, words and phrases repeat at most
   twice) and MedSpeech's quality filter, which grades the raw output ACCEPT,
   REVIEW or REJECT, plus its text checks.
6. Only when FraPiz's result is rejected (silence, very low confidence,
   Cyrillic, implausible length), identifies the language with large-v3 and
   retries with large-v3 in Russian, English, or automatic detection. A
   Russian detection on Latin-script text with lexicon matches counts as
   Romanian, as in MedSpeech. The better-graded result wins.
7. Removes the words the overlap repeats from the previous segment, aligning
   the two texts word by word without case or diacritics.
8. Drops rejected segments, caps the confidence of flagged or REVIEW segments
   at 0.5, attributes each segment to the diarization speaker who overlaps it
   longest, and pushes the schema-version-1 transcription to the pipeline.

The job's `segments.json` keeps every attempt with its raw text, grade,
reasons, language probabilities, lexicon matches (spoken form, `standard_ro`,
action), and speaker overlaps. The text sent to the pipeline is never
rewritten by the lexicon.

### Differences from MedSpeech, and why

Measured on a 3-minute Medpark recording of Moldovan Romanian case discussion:

- **Language detection never replaces a usable FraPiz result.** Whisper
  large-v3 labelled 6 of 9 segments Russian, and ECAPA (VoxLingua107, which
  MedSpeech uses) labelled most of them Ukrainian, Belarusian or Lithuanian.
  Following those labels, large-v3 wrote Romanian phonetically in Cyrillic
  or kept two words of a 20 s segment. Comparing forced-Romanian and
  forced-Russian decode scores was no better, because large-v3 drops most of
  the audio when forced to Romanian.
- **Repetition marks a segment for review instead of rejecting it.** The
  MedSpeech filter rejected 2 of 9 segments of real speech for phrases said
  three times in 20 s; the Repeat Guard already removes actual loops.
- **The 2 s overlap is de-duplicated.** MedSpeech decodes it but keeps the
  repeated words. Exact matching missed every boundary, because the two
  decodes of the same audio differ ("da să vă" / "dă să vă"), so words are
  aligned; a run must reach the previous text's end and match at least half
  the removed words, so a number repeated by chance stays.
- **Fixed MedSpeech bugs:** the pre-routing text checks used `r"\\w+"`, which
  never matched, so their repetition and length checks never ran; adjacent
  lexicon matches were treated as overlapping.
- **whisper.cpp instead of transformers and Faster-Whisper**, with whisper.cpp's
  loop retry; greedy decoding alone looped 20 times on one segment.
- **Speaker attribution is per segment.** MedSpeech's optional re-transcription
  of every diarization turn would decode the audio a second time.

### Offline guarantee for pyannote

pyannote.audio 4 sends usage telemetry to `otel.pyannote.ai` by default, even
with `HF_HUB_OFFLINE=1`; a test run confirmed the connection attempt. The
service sets `PYANNOTE_METRICS_ENABLED=false`, `HF_HUB_OFFLINE=1`, and
`HF_HUB_DISABLE_TELEMETRY=1` before importing pyannote, and a diarization run
under a socket guard made no non-loopback connection.

### Performance

Measured on a MacBook Pro M4 Pro with 48 GB: FraPiz decodes a 20 s segment in
about 1 s. pyannote diarizes 3 minutes in 6 s on `mps` and 88 s on `cpu`. The
3-minute recording took 14 s through the service, diarization included (13×
realtime). A 60-minute meeting has not been measured yet.

Known limits:

- A Russian passage that FraPiz renders in Romanian stays in Romanian, and a
  Russian word inside a Romanian sentence stays in Latin script. Neither can
  be detected reliably on Medpark audio with the local detectors tried.
- Speaker attribution is per segment; a 20 s segment with two speakers goes
  to the one who spoke longer.
- The lexicon-assisted prompt is off by default, as MedSpeech recommends; its
  effect on accuracy has not been measured.

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
idempotency, structured-transcript extraction, the audio and text submissions,
both failure callbacks, versioned JSON validation, confidence
propagation, review-context projection, atomic checkpoints, restart recovery,
status reads, event ordering, concurrent locking, non-blocking scheduling,
transient retry, and safe failures. The MoM service tests run the full
pipeline round trip with a stand-in for the model, plus evidence checking,
failure reporting, and byte-identical resends after a restart. The
speech-to-text tests cover segmentation, the Repeat Guard, the quality
filter, overlap de-duplication on real Medpark boundaries, lexicon matching,
routing, speaker attribution, the pyannote telemetry switch, and a
schema-valid result from real FFmpeg audio with stand-in models. They do not
load the model.

All source dependencies must be declared and installable before the offline
demo, and the model file must be on disk.
