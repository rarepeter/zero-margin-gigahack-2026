# MoM benchmark design

The **Minutes of Meeting** tab compares open-weight text models on one task: turning a raw, multilingual hospital meeting transcript into structured Romanian minutes. The goal is to choose the model the Secure MoM pipeline runs locally. Results appear as a matrix of scores, with models as rows and transcripts as columns.

## Pipeline

For each selected transcript:

1. The judge, Claude Opus 5.5 via the local Claude Code CLI, writes its own reference minutes. It uses the same system prompt and user message as every model and does not see the answer key.
2. Each selected model receives the same prompt and the raw transcript through OpenRouter's chat completions endpoint. Models never see the judge's minutes or the answer key.
3. After a model's minutes and the reference are both ready, the judge grades that model's minutes in a separate call. The grading call includes the transcript, the hidden answer key, the reference minutes, and the candidate's minutes without the model name. Each candidate is graded alone, so candidates do not affect each other's grades.
4. The server calculates a score from 0 to 100 using the judge's structured verdicts.

Up to four OpenRouter requests and three judge calls run at the same time. Set `MOM_JUDGE_CONCURRENCY` to change the judge limit. Failed cells stay failed until you select **Retry failed**, which repeats only the failed step. Existing minutes are not regenerated.

The judge command is `claude -p --model claude-opus-5-5 --effort high --tools "" --strict-mcp-config --setting-sources "" --no-session-persistence`. The command runs from the system temporary directory. It has no tools, MCP servers, settings files, or CLAUDE.md memory. Only the benchmark prompts reach the model. Grades use `--json-schema` and are validated with zod.

## Scoring

The judge assigns verdicts. The server calculates the score in `scoreJudgement` in `shared/mom.ts`, so all transcripts use the same arithmetic.

| Part | Weight | Measures |
| --- | --- | --- |
| Coverage | 50% | Answer key items: correct 1, partial 0.5, missing 0, wrong −0.5. Weights: decisions and actions 3, findings 2, risks and open questions 1.5. Critical items count twice. The part cannot fall below 0. |
| Attribution | 15% | Action owners and deadlines: correct 1, missing or wrong 0, invented −1. An owner or deadline that the recording never stated must appear as `Nestabilit`. |
| Traps | 20% | Share of known pitfalls avoided, such as a rejected proposal presented as a decision or a pre-correction figure. |
| Quality | 15% | Structure, concision, Romanian, terminology, and uncertainty handling, each rated from 1 to 5. |
| Hallucinations | penalty | Each unsupported major claim subtracts 6 points. Each unsupported minor claim subtracts 2 points. |

Items the judge does not grade count as missing. A distortion loses more than an omission, and an invented owner or deadline loses more than a missing one. This follows the project principle that missing information remains missing.

These choices reduce judge bias:

- **An answer key, not the judge's taste.** The hidden key lists what correct minutes contain. The reference minutes are a reading aid. The prompt tells the judge not to reward similarity to its own wording.
- **Blind grading.** Model names never enter the grading prompt. A test checks this.
- **Strict tie-breaking.** When unsure, the judge chooses the lower verdict.
- **Frozen inputs.** Each run stores its transcripts, answer keys, and prompts. Later dataset edits do not change old results. The run records the MoM prompt's SHA-256.

One Opus judge still introduces a single-judge bias. Opus may also recognize and favor output that resembles its own. The answer key limits how much this affects the score. The reference minutes are not graded.

## Model selection

The models listed in `shared/mom.ts` meet these criteria:

- The model has open weights on Hugging Face and a license that permits commercial on-premise use. The allowed licenses are Apache-2.0, MIT, and OpenMDW-1.1. Licenses were checked through the Hugging Face API on 2026-09-26.
- The weights fit the team's 48 GB M4 Pro at 4-bit to 8-bit precision next to the local Whisper model. Memory estimates cover weights only. A 60-minute transcript also needs KV cache. On macOS, the GPU can use about 75% of unified memory by default.
- The model is available on OpenRouter.

| Model | Size | License | AA Intelligence Index |
| --- | --- | --- | --- |
| [Qwen3.8 27B](https://huggingface.co/Qwen/Qwen3.8-27B) | 27.8B dense | Apache-2.0 | 34 xhigh, 28 medium |
| [Qwen3.6 35B-A3B](https://huggingface.co/Qwen/Qwen3.6-35B-A3B) | 36B MoE, 3B active | Apache-2.0 | 18 |
| [Gemma 4 31B](https://huggingface.co/google/gemma-4-31B-it) | 31.3B dense | Apache-2.0 | 19 |
| [Gemma 4 26B-A4B](https://huggingface.co/google/gemma-4-26B-A4B-it) | 25.8B MoE, 3.8B active | Apache-2.0 | 17 |
| [Muse Glimmer 30B](https://huggingface.co/meta-models/Muse-Glimmer-30B) | 29.8B dense | Apache-2.0 | 17 |
| [Nemotron 3.5 Lightning](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16) | 31.6B MoE, 3B active | OpenMDW-1.1 | not listed |
| [GLM-4.7-Flash](https://huggingface.co/zai-org/GLM-4.7-Flash) | 31.2B MoE, 3B active | MIT | not listed |
| [gpt-oss-20b](https://huggingface.co/openai/gpt-oss-20b) | 20.9B MoE, 3.6B active | Apache-2.0 | not listed |
| [Mistral Small 3.2 24B](https://huggingface.co/mistralai/Mistral-Small-3.2-24B-Instruct-2506) | 24B dense | Apache-2.0 | not listed |

The index values come from [Artificial Analysis's small open-model leaderboard](https://artificialanalysis.ai/models/open-source/small) on 2026-09-26. Its [multilingual benchmark](https://artificialanalysis.ai/models/multilingual) excludes Romanian and Russian, so no public benchmark covers this task. That gap is why this benchmark exists.

Some models were excluded because they do not fit in memory: Qwen3.8-Flash-Next (180B, also under the Qwen community license), GLM-5.3-Flash (321B), MiMo-V2.6-Flash (311B), gpt-oss-120b, Nemotron 3 Super 120B, and Mistral Small 4 (119B). Coding-focused and safety-classifier models were also excluded.

## Local models

Two quantized builds of Muse Glimmer 30B run on the Mac through [llama.cpp](https://github.com/ggml-org/llama.cpp) (`brew install llama.cpp`, tested with 0.5.0). The UI marks them **Local**.

| Variant | File | Source | Size | SHA-256 |
| --- | --- | --- | --- | --- |
| Q4_K_M | `Muse-Glimmer-30B-KQuant-17GB-Q4_K_M.gguf` | [meta-models/Muse-Glimmer-30B-GGUF](https://huggingface.co/meta-models/Muse-Glimmer-30B-GGUF), the official Meta release | 16.8 GB | `4cc57c0f…f183f60e` |
| Q8_0 | `Muse-Glimmer-30B-Q8_0.gguf` | [unsloth/Muse-Glimmer-30B-GGUF](https://huggingface.co/unsloth/Muse-Glimmer-30B-GGUF). Meta publishes no 8-bit GGUF | 29.6 GB | `f2c087d6…299b0e86` |

The checksums match the Hugging Face LFS hashes, checked on 2026-09-27. GGUF was chosen over MLX because the MLX 4-bit and 8-bit builds need 52.8 GB together, which did not fit the free disk space. Both variants use the same runtime, so the comparison isolates quantization.

To download the files and configure the app:

```sh
hf download meta-models/Muse-Glimmer-30B-GGUF Muse-Glimmer-30B-KQuant-17GB-Q4_K_M.gguf --local-dir ~/Models/meta-models/Muse-Glimmer-30B-GGUF
hf download unsloth/Muse-Glimmer-30B-GGUF Muse-Glimmer-30B-Q8_0.gguf --local-dir ~/Models/unsloth/Muse-Glimmer-30B-GGUF
```

```dotenv
MUSE_GLIMMER_Q4_GGUF=/Users/you/Models/meta-models/Muse-Glimmer-30B-GGUF/Muse-Glimmer-30B-KQuant-17GB-Q4_K_M.gguf
MUSE_GLIMMER_Q8_GGUF=/Users/you/Models/unsloth/Muse-Glimmer-30B-GGUF/Muse-Glimmer-30B-Q8_0.gguf
```

Set `LLAMA_SERVER_BIN` if `llama-server` is not on `PATH`. Restart the server after editing `.env`.

Only one local model occupies memory at a time. The server starts `llama-server` for the first local job. It runs every waiting job for that model before stopping it and loading the next one, and it stops the last model when no local work remains. Hosted models and the judge keep running in parallel, because they use little local memory. The model runs with a 32,768-token context, full GPU offload, and flash attention. Only 13 of its 52 layers use full attention, so the context adds about 0.5 GB of KV cache to the weights.

Local requests use the same prompt, a 32,000-token limit, and the model's published sampling defaults: temperature 1.0, top-p 0.95, top-k 64. These match what OpenRouter serves. They request `reasoning_strength: medium` through the chat template, which is the template's name for the hosted `reasoning.effort`. llama.cpp separates reasoning from the minutes. Each local cell records load time, prompt and generation speed in tokens per second, and reasoning tokens counted with the model's tokenizer. Local time excludes model loading. Model requests turn off Bun's built-in `fetch` timeout, which otherwise stops any response that has no first byte after about 5 minutes. A local run returns the whole response at once, so every generation longer than 5 minutes failed. The limits that apply are 90 minutes per local request and 15 minutes per OpenRouter request.

On the M4 Pro, the Q4_K_M build loaded in 22 seconds. With the download still running, it processed a 1,200-word transcript at 116 prompt tokens/s and generated at 12.9 tokens/s. That run took 4.8 minutes and produced 3,413 tokens, 1,768 of them reasoning.

## Request settings

Every model receives the same request: `reasoning.effort = "medium"`, `max_tokens = 32000`, and the model's default temperature. Several reasoning models repeat themselves at temperature 0. Non-reasoning models ignore the effort setting. Each cell records the serving provider, finish reason, prompt, completion, reasoning tokens, OpenRouter time, and reported cost. A finish reason other than `stop` is shown because truncated minutes are a real failure. A leading `<think>` block is removed before grading. A model that returns no minutes, for example because its reasoning consumed every token, scores 0 without a judge call. Averages include that 0. Rate limits, network errors, and judge errors leave the cell failed so it can be retried.

## Limits

- **Precision.** OpenRouter providers serve these models at BF16 or FP8. Locally, the team would run a 4-bit to 8-bit quantization, which can reduce Romanian quality. Rerun the top models locally with the same prompt before choosing one.
- **Speed.** OpenRouter time is not local inference time. Use the completion and reasoning token counts with a measured local generation speed to estimate the 60-minute-recording budget.
- **Data.** The transcripts are fictional and written by Claude. They imitate raw ASR output and Moldovan code-switching, but they are cleaner than real recordings and share Claude's style. Add real, consented transcripts when available.
- **Privacy.** The benchmark sends transcripts to OpenRouter and Anthropic. Use only fictional data. Real meeting data must stay on premises.
- **Language.** The minutes are Romanian for now. The transcripts are Romanian-based with Russian and English switches.

## Dataset

See [the transcript format and authoring guide](../mom/README.md). Thirteen transcripts cover all six meeting types, two per type, plus one long management meeting of about 6,000 words to test long-context behavior.
