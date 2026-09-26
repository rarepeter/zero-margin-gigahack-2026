# Benchmark design

Speechbench compares the text returned by hosted and local open-weight models. It does not assign an accuracy score without a human reference transcript. Hosted API time includes network and provider processing time. Local time measures this computer, including model loading on the first request.

## Model selection

The server accepts an explicit allowlist from `shared/models.ts`. It rejects other model IDs, including closed transcription models. Hosted availability is checked against [OpenRouter's transcription catalog](https://openrouter.ai/api/v1/models?output_modalities=transcription). A catalog error leaves the hosted allowlist usable and displays a warning. Local availability checks the configured model files and Python executable independently of OpenRouter. The first local run verifies that Python can load and run the model.

| Model | Weight source | License | Language scope |
| --- | --- | --- | --- |
| Whisper large-v3 | [OpenAI](https://huggingface.co/openai/whisper-large-v3) | Apache-2.0 | Romanian, Russian, English |
| Whisper large-v3 Turbo | [OpenAI](https://huggingface.co/openai/whisper-large-v3-turbo) | MIT | Romanian, Russian, English |
| Parakeet TDT 0.6B v3 | [NVIDIA](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) | CC-BY-4.0 | Romanian, Russian, English |
| Qwen3-ASR 1.7B | [Qwen](https://huggingface.co/Qwen/Qwen3-ASR-1.7B) | Apache-2.0 | Romanian, Russian, English |
| Qwen3-ASR 0.6B | [Qwen](https://huggingface.co/Qwen/Qwen3-ASR-0.6B) | Apache-2.0 | Romanian, Russian, English |
| Voxtral Mini 3B 2507 | [Mistral](https://huggingface.co/mistralai/Voxtral-Mini-3B-2507) | Apache-2.0 | Exploratory; Romanian and Russian are absent from its supported-language list |
| Voxtral Small 24B 2507 | [Mistral](https://huggingface.co/mistralai/Voxtral-Small-24B-2507) | Apache-2.0 | Exploratory; Romanian and Russian are absent from its supported-language list |
| Nemotron 3.5 ASR Streaming 0.6B | [NVIDIA](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b) | OpenMDW-1.1 | Exploratory; Russian and English are transcription-ready, Romanian is in the lower broad-coverage tier |
| Moldovan Romanian Whisper, local | [FraPiz](https://huggingface.co/FraPiz/whisper-large-v3-turbo-moldovan-romanian) | Apache-2.0 | Fine-tuned on Moldovan Romanian educational speech. Mixed-language accuracy needs evaluation. |

The sources were checked on 2026-09-25, and Nemotron on 2026-09-26. OpenRouter lists Nemotron's weights as `nvidia/Nemotron-3.5-ASR-Streaming-Multilingual-0.6b`, which does not resolve; the public checkpoint is `nvidia/nemotron-3.5-asr-streaming-0.6b`. An open-weight license does not guarantee that a hosted service exposes every model feature. VibeVoice-ASR and Canary-1B-v2 are shown as unavailable because their exact models were absent from OpenRouter. Other catalog entries are excluded until their downloadable weights and license are verified. `whisper-1` is excluded because the benchmark uses explicit large-v3 variants.

## Mixed-language settings

The default hosted request omits `language`. Local inference clears the checkpoint's saved Romanian language setting when **Automatic** is selected. Forcing Romanian can suppress Russian or English switches. Temperature is zero, and both routes perform transcription. The app never translates, transliterates, normalizes Romanian diacritics, or rewrites returned text.

No setting guarantees accurate Moldovan regionalisms. Dialect words, code switches, names, numbers, negations, and English terminology need manual review against the audio. The defaults are a reproducible starting point, not a proven optimum for a recording that has not been evaluated.

Whisper context and vocabulary hints use `provider.options.groq.prompt`. The app joins the context and vocabulary with a blank line, omitting empty fields. Vocabulary gets a `Vocabulary:` prefix and a final period if it lacks sentence-ending punctuation. This avoids leaving an unfinished term list in the prompt. [Groq documents context and spelling hints](https://console.groq.com/docs/speech-to-text). The app sends no invented vocabulary and no unverified Qwen, Parakeet, Voxtral, or Nemotron hint parameters. Advanced JSON options can add documented provider-specific settings. An explicit Groq prompt overrides the generated prompt, and the UI shows that override.

OpenRouter applies options only to the hosting provider it selects. Its transcription endpoint does not honor per-request provider pinning through `only` or `order`. Some integrations silently drop unsupported options. The UI records requested settings, not a claim that every upstream provider honored them. [OpenRouter documents these limits](https://openrouter.ai/docs/guides/overview/multimodal/stt).

Local Whisper receives the same combined context and vocabulary as prompt tokens. The worker rejects more than 223 text tokens, reserving one token for the context marker, rather than silently truncating the hint. Local inference does not receive OpenRouter provider options. Its raw responses record the engine, model revision when download metadata is present, device, precision, library versions, language selection, prompt token count, and timing.

## Hospital context prompt

The UI prefills new sessions with the hospital preset in `shared/prompt.ts`. `contextPrompt` defaults to an empty string in the stored schema, so reading older runs never adds a prompt they did not use. Context, vocabulary, and the effective provider request are saved for each run. **Run again** copies the saved settings.

The preset describes the user's recordings as hospital discussions in Moldova. It anticipates regional Romanian, Russian, and occasional English, including changes within a sentence. It requests the spoken language and script, medical terminology, abbreviations, negations, numbers, doses, and units. It discourages translation, summarization, expanding abbreviations, and guessing unheard content. The vocabulary field remains empty until the user supplies terms that occur in the audio.

The preset is written in English and uses 86 text tokens with the downloaded tokenizer. A Romanian-heavy draft caused repetition on a known English test clip. The English preset preserved that clip's words. This narrow check informed the preset choice; it does not establish medical or mixed-language accuracy.

Research checked on 2026-09-26 informed these choices:

- [Malysheva's study of Romanian–Russian code-switching](https://philology-journal.ru/en/article/phil20240673/fulltext) describes Russian lexical and syntactic influence in Romanian speech in Moldova. This supports allowing language switches and borrowed words instead of correcting all speech into one language.
- [Galben and Molea's study of professional communication](https://repository.utm.md/handle/5014/35588) examines Romanian structures combined with English technical terminology. [Galben's doctoral thesis](https://msuir.usm.md/items/5928601c-dde5-40c6-89da-cfd58d27a98e) documents Romanian, Russian, and English mixing in workplace digital conversations. These findings concern those studied settings, not every Moldovan speaker or hospital. The hospital context comes from the user's description.
- [Groq's prompting guidance](https://console.groq.com/docs/speech-to-text) describes a maximum of 224 tokens and guidance for context, spelling, and style. Whisper is not a chat instruction model. The requested behavior is a hint, not an enforced rule or evidence of improved accuracy.

The hint accompanies every prepared audio chunk. For local chunks longer than 30 seconds, Transformers applies the prompt to the first internal segment by default. Language detection stays automatic unless the user changes it. The UI flags a forced language when context is present.

Only local Whisper and Groq-hosted Whisper have verified prompt wiring here. OpenRouter chooses the hosted route, so a saved Groq prompt does not prove that Groq served the request. Qwen, Parakeet, Voxtral, and Nemotron run without the context field through this integration. This is an integration limit, not a claim about all deployments of those models. Compare prompted and unprompted runs against a human reference to measure whether the hint helps.

## Audio preparation

The original recording remains available for playback. FFmpeg converts its first audio track to mono, 16 kHz, signed 16-bit PCM WAV. All models receive the same prepared chunks. There is no denoising or speech removal.

Each run has a target chunk size of 10–600 whole seconds, defaulting to 45. The splitter searches for a pause from `target - min(15, floor(target / 3))` to `target + min(10, floor(target / 3))` seconds after the previous boundary. It uses the pause closest to the target, or the target itself when no pause exists. Audio remaining within the maximum stays in one final chunk. At the default, the search window is 30–55 seconds, preserving the original behavior. Boundaries do not overlap, and the app preserves all audio between boundaries.

Larger chunks retain more context, but may exceed a provider's audio limits or take longer than OpenRouter's approximately 60-second upstream processing timeout. Processing time and audio duration are different limits; even a short chunk can time out. The UI shows both the chosen target and maximum beside every transcript.

Upload prepares the default 45-second chunks. A run with another target prepares a separate set from the saved normalized audio before sending any requests. All models in that run share its chunk plan. Rerunning the same recording does not alter earlier runs. Runs saved before configurable chunking retain their original chunks and display the 45-second default.

Local Whisper receives those same chunk files. Transformers processes chunks longer than 30 seconds with Whisper's sequential long-form decoding and internal timestamp tokens. It does not truncate the file to the first 30 seconds. When timestamps are requested, the response includes word spans for playback. Words with missing boundaries remain in the raw output without invented times.

Chunking can reduce context or split a word when no pause exists. It also prevents a test of a model's full long-context capability. The original text from each successful chunk is joined with two newlines. The app does not heuristically remove repeated words at boundaries. Word and segment timestamps remain unchanged in raw responses. The UI adds chunk offsets to clickable segment times. Speaker IDs are local to a chunk and may change across chunks.

## Stored data

`DATA_DIR` defaults to `.data`. It contains:

- `benchmarks.sqlite`, plus SQLite WAL files while running.
- `audio/<recording-id>/original`, the uploaded audio.
- `audio/<recording-id>/normalized.wav` and `chunk-<index>.wav`, the prepared audio.
- `audio/<recording-id>/variants/<variant-id>/chunk-<index>.wav`, prepared chunks for runs with a different target.

SQLite stores the original filename, duration, SHA-256, per-run chunk target and boundaries, model IDs, settings, full transcripts, statuses, request durations, reported costs, raw responses, errors, and generation IDs. The `run_audio` table links each new run to its prepared chunk files. Audio base64 and authorization headers are omitted from request logs. Credential-shaped fields and the configured key are redacted before persistence.

Run history and JSON exports include all model results. A failed model stops at its first failed chunk, preserves previous chunks, and does not stop other models. Failed requests are not automatically retried. A restart marks unfinished models as interrupted. **Run again** creates a separate run and can incur new charges.

The interface displays summed request time, excluding queue time. Local time includes process startup and model loading on the first chunk. The raw response separates model loading and inference time. Hosted cost is summed only where the provider returns a cost. Missing cost is not treated as zero; partial failures can make the displayed total incomplete. Local cost stays null in storage, and the interface shows **No API charge**. Electricity and hardware costs are not measured.

The server binds to `127.0.0.1`, checks local origins, and has no remote authentication. It is intended for a local workstation. `.data`, `.env`, and build artifacts are gitignored. To back up recordings and results consistently, stop the server and copy the entire data directory.

## Integration

The frontend uses React, Vite, and Tailwind. The backend uses Bun and `bun:sqlite`. Hosted transcription uses the native OpenRouter JSON endpoint through `fetch`. Local transcription uses `server/local-whisper.ts` to manage a persistent Python process, `local/whisper_worker.py`, over newline-delimited JSON. The model loads from `LOCAL_WHISPER_MODEL_PATH` with network access disabled in Transformers.

The queue has two hosted slots and one local slot. A waiting hosted job cannot block local work, and local failures do not stop hosted jobs. Each local chunk has a 30-minute limit including startup. Timeout or shutdown kills the worker and settles the pending request. A later run can start a new worker after failure. Setup is documented in [Enable local Whisper](../README.md#enable-local-whisper).

The API key is read only by the backend. The browser receives a `keyConfigured` boolean. No live paid transcription has been verified until a real OpenRouter key is supplied and a run completes.
