# Speechbench

Two benchmarks for the Secure MoM pipeline, in two tabs:

- **Speech to text** compares full transcripts of an uploaded recording from OpenRouter models and a local Moldovan Romanian Whisper model.
- **Minutes of Meeting** scores open-weight text models on turning raw multilingual transcripts into structured Romanian minutes. Claude Opus grades each result against a hidden answer key. See [Compare MoM models](#compare-mom-models).

Runs, request settings, raw responses, and results persist locally in SQLite.

## Start the app

You need Bun and FFmpeg. FFmpeg decodes M4A and prepares identical audio for every model.

```sh
brew install bun ffmpeg
bun install
cp .env.example .env
```

Set your key in `.env`:

```dotenv
OPENROUTER_API_KEY=your-openrouter-key
```

Keep the key on the server. Do not prefix it with `VITE_` or put it in provider options. Restart the app after changing `.env`.

```sh
bun run dev
```

Open [Speechbench](http://127.0.0.1:5173). Hosted models require a key with OpenRouter credits. Uploads, saved results, and local-only runs work without a key.

For a single server serving the production build:

```sh
bun run build
bun start
```

Open [the production app](http://127.0.0.1:3001). Both servers bind to your local machine.

## Enable local Whisper

Use Python 3.12 or newer. The downloaded model stays outside the repository. From the project directory, install the local runtime:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r local/requirements.txt
```

Set the model folder in `.env`. On Peter's Mac, the downloaded model is here:

```dotenv
LOCAL_WHISPER_MODEL_PATH=/Users/peter/Models/FraPiz/whisper-large-v3-turbo-moldovan-romanian
LOCAL_WHISPER_DEVICE=auto
```

Restart `bun run dev`. Select **Moldovan Romanian Whisper**, marked **Local**, alongside your OpenRouter models. **Select all** includes it when configured. **Core five** selects only the five hosted baselines.

The worker loads the model on its first request and keeps it in memory until the server stops. `auto` uses the Mac GPU when available, otherwise CUDA or CPU. Set `LOCAL_WHISPER_DEVICE=cpu` to choose CPU execution. Set `LOCAL_WHISPER_PYTHON` only if your Python environment is somewhere other than `.venv/bin/python`.

Local inference reads the downloaded files offline. No audio goes to an external service for the local result. Selecting OpenRouter models still sends the same audio to those services. Local time includes model loading on the first chunk, and each raw response records inference time, device, and library versions.

## Compare recordings

1. Upload an M4A file, or select a saved recording. MP3, WAV, FLAC, OGG, WebM, and AAC also work. The limits are 250 MB and two hours.
2. Select models. **Core five** selects Whisper large-v3, Whisper Turbo, Parakeet v3, and both Qwen3-ASR sizes. **Select all** also includes the exploratory Voxtral and Nemotron models and local Whisper when configured.
3. Edit **Transcription context** or select **Use hospital preset**. The preset describes hospital speech in Moldova with Romanian, Russian, and occasional English. Keep **Automatic** language detection. Add a few exact spellings in **Names & vocabulary** if needed. The UI identifies models that receive no context hint.
4. Set **Target chunk size (seconds)** from 10 to 600. The default is 45. Splits prefer pauses and may extend up to 10 seconds beyond the target; the UI shows the maximum. Every model in a comparison receives the same chunks.
5. Select **Run models**. Up to two hosted models and one local model run concurrently in separate queues. Hosted requests use OpenRouter credits. Local transcription has no API charge.
6. Read the complete transcripts as chunks finish. Each transcript shows its chunk target. Use **Copy transcript**, **Download text**, or **Export JSON** to save results elsewhere.
7. Select **Run again** to copy a previous run's settings into a new comparison. You can change chunk size without uploading again. Existing results remain intact, and each run's chunk size is saved in history and JSON exports.

To test timestamps, enable **Request timestamps**. Local Whisper returns clickable word timestamps. Hosted models receive requests for word and segment timestamps. To test hosted provider features, use **Advanced options** and consult [OpenRouter's provider option documentation](https://openrouter.ai/docs/guides/overview/multimodal/stt#provider-specific-options). Unsupported timestamp requests can fail. The app saves that failure and does not silently switch to another configuration.

Context and vocabulary apply to local Whisper and hosted Whisper when Groq serves the request. These are short recognition hints, not chat system prompts. Keep them concise. Local Whisper reports an error if they exceed its 223-text-token budget. Clear both fields to compare against a run without hints. A custom Groq prompt in **Advanced options** overrides both fields for hosted Whisper.

The prompt is saved with each run, appears under **Settings used for this run**, and is included in JSON exports. **Run again** copies the saved prompt. Older runs retain an empty context; select **Use hospital preset** when rerunning them to add it. See [the context research and model limits](docs/benchmark.md#hospital-context-prompt).

## Compare MoM models

The judge runs through the [Claude Code CLI](https://docs.claude.com/en/docs/claude-code), which must be installed and signed in. The server finds `claude` on `PATH`. Set `CLAUDE_BIN` in `.env` if the command is elsewhere. Model calls use `OPENROUTER_API_KEY`.

1. Open **Minutes of Meeting** in the sidebar.
2. Select transcripts and models. By default, all 13 fictional transcripts and all nine models are selected. Select **View** to read a transcript and its hidden answer key.
3. Select **Run benchmark**. For each transcript, the judge writes reference minutes. Every model writes its own minutes from the same prompt, and the judge grades each result blind.
4. Read the matrix as cells finish. Select a cell to see the graded answer key, hallucinations, quality ratings, the model's minutes, and the judge's reference.
5. Select **Retry failed** to repeat only the failed steps. Select **Export JSON** to save the full run, including its frozen transcripts, prompts, and raw responses.

The **Local** models, Muse Glimmer 30B at 4-bit and 8-bit, run on this Mac through llama.cpp, one model in memory at a time. Each local generation takes several minutes. They are not selected by default. See [Local models](docs/mom-benchmark.md#local-models) for downloads and `.env` paths.

A full run makes 117 OpenRouter calls and 130 judge calls. With three concurrent judge calls, it takes about 30–60 minutes. OpenRouter charges are a few dollars at most. Judge calls use your Claude plan. Use fictional data only, because both services receive the transcripts. See [the MoM benchmark design](docs/mom-benchmark.md) for scoring, model selection, and limits. See [the transcript guide](mom/README.md) to add meetings.

## Verify changes

```sh
bun run check
```

The tests use mock transcription providers and real FFmpeg conversion. They make no paid requests. They cover M4A upload, configurable chunks, older saved runs, hosted requests, Unicode preservation, persistence, failures, and concurrent local and hosted jobs. The worker protocol tests use a small Python fixture and skip when `python3` is unavailable. They do not load model weights.

With local dependencies installed, run `.venv/bin/python -m unittest discover -s local -p 'test_*.py'` to check real Transformers preprocessing for short, 30-second, and longer chunks. This catches the `num_frames` failure in Transformers 5.0.0 without loading model weights.

See [the benchmark design](docs/benchmark.md) for parameter choices, model sources, storage, and known limits. See [company billing setup](docs/billing.md) before buying credits.
