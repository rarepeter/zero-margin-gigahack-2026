# Benchmark design

Speechbench compares the text returned by hosted open-weight models. It does not assign an accuracy score without a human reference transcript. Hosted API time includes network and provider processing time, and does not predict performance on a Mac.

## Model selection

The server accepts an explicit allowlist from `shared/models.ts`. It rejects other model IDs, including closed transcription models. Availability is checked against [OpenRouter's transcription catalog](https://openrouter.ai/api/v1/models?output_modalities=transcription). A catalog error leaves the static allowlist usable and displays an availability warning.

| Model | Weight source | License | Language scope |
| --- | --- | --- | --- |
| Whisper large-v3 | [OpenAI](https://huggingface.co/openai/whisper-large-v3) | Apache-2.0 | Romanian, Russian, English |
| Whisper large-v3 Turbo | [OpenAI](https://huggingface.co/openai/whisper-large-v3-turbo) | MIT | Romanian, Russian, English |
| Parakeet TDT 0.6B v3 | [NVIDIA](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) | CC-BY-4.0 | Romanian, Russian, English |
| Qwen3-ASR 1.7B | [Qwen](https://huggingface.co/Qwen/Qwen3-ASR-1.7B) | Apache-2.0 | Romanian, Russian, English |
| Qwen3-ASR 0.6B | [Qwen](https://huggingface.co/Qwen/Qwen3-ASR-0.6B) | Apache-2.0 | Romanian, Russian, English |
| Voxtral Mini 3B 2507 | [Mistral](https://huggingface.co/mistralai/Voxtral-Mini-3B-2507) | Apache-2.0 | Exploratory; Romanian and Russian are absent from its supported-language list |
| Voxtral Small 24B 2507 | [Mistral](https://huggingface.co/mistralai/Voxtral-Small-24B-2507) | Apache-2.0 | Exploratory; Romanian and Russian are absent from its supported-language list |

The sources were checked on 2026-09-25. An open-weight license does not guarantee that a hosted service exposes every model feature. VibeVoice-ASR and Canary-1B-v2 are shown as unavailable because their exact models were absent from OpenRouter. Other catalog entries are excluded until their downloadable weights and license are verified. `whisper-1` is excluded because the benchmark uses explicit large-v3 variants.

## Mixed-language settings

The default request omits `language`. Forcing Romanian can suppress Russian or English switches. Temperature is zero, and requests use the transcription endpoint. The app never translates, transliterates, normalizes Romanian diacritics, or rewrites returned text.

No setting guarantees accurate Moldovan regionalisms. Dialect words, code switches, names, numbers, negations, and English terminology need manual review against the audio. The defaults are a reproducible starting point, not a proven optimum for a recording that has not been evaluated.

Whisper vocabulary hints use `provider.options.groq.prompt`. The prompt prefixes user-supplied terms with the three language names. [Groq documents spelling hints and temperature 0](https://console.groq.com/docs/speech-to-text). The app sends no invented vocabulary and no unverified Qwen or Parakeet hint parameters. Advanced JSON options can add documented provider-specific settings. Explicit options override the generated Groq prompt.

OpenRouter applies options only to the hosting provider it selects. Its transcription endpoint does not honor per-request provider pinning through `only` or `order`. Some integrations silently drop unsupported options. The UI records requested settings, not a claim that every upstream provider honored them. [OpenRouter documents these limits](https://openrouter.ai/docs/guides/overview/multimodal/stt).

## Audio preparation

The original recording remains available for playback. FFmpeg converts its first audio track to mono, 16 kHz, signed 16-bit PCM WAV. All models receive the same prepared chunks. There is no denoising or speech removal.

Each run has a target chunk size of 10–600 whole seconds, defaulting to 45. The splitter searches for a pause from `target - min(15, floor(target / 3))` to `target + min(10, floor(target / 3))` seconds after the previous boundary. It uses the pause closest to the target, or the target itself when no pause exists. Audio remaining within the maximum stays in one final chunk. At the default, the search window is 30–55 seconds, preserving the original behavior. Boundaries do not overlap, and the app preserves all audio between boundaries.

Larger chunks retain more context, but may exceed a provider's audio limits or take longer than OpenRouter's approximately 60-second upstream processing timeout. Processing time and audio duration are different limits; even a short chunk can time out. The UI shows both the chosen target and maximum beside every transcript.

Upload prepares the default 45-second chunks. A run with another target prepares a separate set from the saved normalized audio before sending any requests. All models in that run share its chunk plan. Rerunning the same recording does not alter earlier runs. Runs saved before configurable chunking retain their original chunks and display the 45-second default.

Chunking can reduce context or split a word when no pause exists. It also prevents a test of a model's full long-context capability. The original text from each successful chunk is joined with two newlines. The app does not heuristically remove repeated words at boundaries. Word and segment timestamps remain unchanged in raw responses. The UI adds chunk offsets to clickable segment times. Speaker IDs are local to a chunk and may change across chunks.

## Stored data

`DATA_DIR` defaults to `.data`. It contains:

- `benchmarks.sqlite`, plus SQLite WAL files while running.
- `audio/<recording-id>/original`, the uploaded audio.
- `audio/<recording-id>/normalized.wav` and `chunk-<index>.wav`, the prepared audio.
- `audio/<recording-id>/variants/<variant-id>/chunk-<index>.wav`, prepared chunks for runs with a different target.

SQLite stores the original filename, duration, SHA-256, per-run chunk target and boundaries, model IDs, settings, full transcripts, statuses, request durations, reported costs, raw responses, errors, and generation IDs. The `run_audio` table links each new run to its prepared chunk files. Audio base64 and authorization headers are omitted from request logs. Credential-shaped fields and the configured key are redacted before persistence.

Run history and JSON exports include all model results. A failed model stops at its first failed chunk, preserves previous chunks, and does not stop other models. Failed requests are not automatically retried. A restart marks unfinished models as interrupted. **Run again** creates a separate run and can incur new charges.

The interface displays summed request time, not queue time. Reported cost is summed only where the provider returns a cost. Missing cost is not treated as zero; partial failures can make the displayed total incomplete.

The server binds to `127.0.0.1`, checks local origins, and has no remote authentication. It is intended for a local workstation. `.data`, `.env`, and build artifacts are gitignored. To back up recordings and results consistently, stop the server and copy the entire data directory.

## Integration

The frontend uses React, Vite, and Tailwind. The backend uses Bun and `bun:sqlite`. Transcription uses the native OpenRouter JSON endpoint through `fetch`, preserving access to provider-specific options and raw responses. No speech model is downloaded locally.

The API key is read only by the backend. The browser receives a `keyConfigured` boolean. No live paid transcription has been verified until a real OpenRouter key is supplied and a run completes.
