# Speechbench

Upload a recording and compare full transcripts from open-weight speech models through OpenRouter. Runs, request settings, raw responses, and transcripts persist locally in SQLite.

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

Open [Speechbench](http://127.0.0.1:5173). You can upload audio and browse saved results before adding a key. Starting a run requires a key with OpenRouter credits.

For a single server serving the production build:

```sh
bun run build
bun start
```

Open [the production app](http://127.0.0.1:3001). Both servers bind to your local machine.

## Compare recordings

1. Upload an M4A file, or select a saved recording. MP3, WAV, FLAC, OGG, WebM, and AAC also work. The limits are 250 MB and two hours.
2. Select models. **Core five** selects Whisper large-v3, Whisper Turbo, Parakeet v3, and both Qwen3-ASR sizes. **Select all** also includes the two exploratory Voxtral models.
3. Keep **Automatic** language detection for Romanian, Russian, and English in the same recording. Add spellings of relevant names or terms in **Names & vocabulary** if needed.
4. Set **Target chunk size (seconds)** from 10 to 600. The default is 45. Splits prefer pauses and may extend up to 10 seconds beyond the target; the UI shows the maximum. Every model in a comparison receives the same chunks.
5. Select **Run models**. Each run makes paid OpenRouter requests. At most two models run concurrently.
6. Read the complete transcripts as chunks finish. Each transcript shows its chunk target. Use **Copy transcript**, **Download text**, or **Export JSON** to save results elsewhere.
7. Select **Run again** to copy a previous run's settings into a new comparison. You can change chunk size without uploading again. Existing results remain intact, and each run's chunk size is saved in history and JSON exports.

To test timestamps, enable **Request word and segment timestamps**. To test provider-specific features, use **Advanced options** and consult [OpenRouter's provider option documentation](https://openrouter.ai/docs/guides/overview/multimodal/stt#provider-specific-options). Unsupported timestamp requests can fail. The app saves that failure and does not silently switch to another configuration.

## Verify changes

```sh
bun run check
```

The tests use a mock transcription provider and real FFmpeg conversion. They make no paid requests. They cover M4A upload, configurable chunks, older saved runs, all allowlisted model requests, mixed-script text preservation, SQLite persistence, interrupted runs, partial failures, and request validation.

See [the benchmark design](docs/benchmark.md) for parameter choices, model sources, storage, and known limits. See [company billing setup](docs/billing.md) before buying credits.
