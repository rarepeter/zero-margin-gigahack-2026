# ASR accuracy benchmark design

The **ASR accuracy** tab ranks transcription models against a human reference transcript. Every selected model transcribes the same recording once per chunk size. Claude Opus 5.5 grades each transcript against the reference without seeing the model name. The result is a matrix of content scores from 0 to 100, with models as rows and chunk sizes as columns.

## Inputs

- **Recording.** Upload a file or choose a saved recording, as in the Speech to text tab.
- **Reference transcript.** A `.md` or `.txt` file of up to 500,000 characters. It must cover the whole recording. Speech missing from the reference counts against every model as invented text. The UI warns when the reference has fewer than 80 words per minute of audio, which usually means it is partial. These conventions are understood:
  - Speaker labels such as `A:` and `B:`, including in the middle of a line, are not speech.
  - `(?)` after a word marks it as uncertain. The judge does not penalize a different but plausible rendering of that word.
  - Parentheses after a word give its standard form or a clarification, for example `patu' (patul)` or `zero zero unu (0.01)`. Either form is correct.
- **Chunk sizes.** One to eight whole-second targets from 10 to 600. Each size uses the Speech to text chunker, which splits near pauses with no overlap. Every model receives the same chunks for a given size. Sentence-based chunking is planned.
- **Models.** Any model from the Speech to text allowlist, including local Whisper when configured.
- **Hospital context.** On by default. Whisper models receive the hospital context prompt; other models receive no hint. See [the context research](benchmark.md#hospital-context-prompt).

## Pipeline

1. Each chunk size becomes a normal Speech to text run. Runs share its queue: two hosted models and one local model run at the same time. The runs also appear in the Speech to text history, with raw requests and responses. Runs are saved first and started only after every chunk variant is prepared, so a failed setup never leaves a half-started benchmark.
2. When a model's run completes, the server computes a normalized word error rate and sends the reference and transcript to the judge. Up to three judge calls run at once; `MOM_JUDGE_CONCURRENCY` sets this limit for both benchmarks.
3. A failed or interrupted transcription marks its cell as failed. **Retry failed** starts a new run for failed transcriptions and grades finished transcripts again when only grading failed.

The judge uses the same Claude Code CLI isolation as [the MoM benchmark](mom-benchmark.md#pipeline): no tools, settings, MCP servers, or CLAUDE.md, with structured output validated by zod.

## Scoring

The judge ignores formatting completely: punctuation, capitalization, paragraphs and chunk breaks, speaker labels, timestamps, diacritics that do not change the word, Russian in Cyrillic versus Latin transliteration, digits versus number words, and fillers or false starts that carry no content.

It aligns the two texts, lists up to 60 errors that matter by severity, and rates five content criteria from 0 to 100. The score is their weighted mean, computed in code (`scoreAsr` in `shared/asr-benchmark.ts`):

| Criterion | Weight | Measures |
| --- | --- | --- |
| Completeness | 30% | Share of the reference's meaningful content present |
| Meaning | 30% | Faithfulness of what was transcribed, including negations and who did what |
| Terms & numbers | 20% | Medical terms, drug names, doses, units, lab values, numbers, dates, names, abbreviations |
| Language | 10% | Each passage kept in the language spoken; translating Russian into Romanian is an error |
| No invention | 10% | 100 means no invented text, loops, text over silence, or duplicated passages |

Rows are ranked by their average score across chunk sizes. The table also shows each model's best chunk size and each column's average across models, which indicates the best chunk size overall.

### Word error rate

Each cell also shows a normalized WER as a deterministic cross-check. It is not part of the score. Before comparing words, the server lowercases the text and removes punctuation, speaker labels, bracketed timestamps, and parenthetical notes. It also normalizes cedilla forms of ș and ț. The metric cannot tell that Cyrillic and transliterated Russian are the same, and it counts every filler word. With code-switching it overstates errors, so rank models by the judge score.

## Limits

- Opus is the only judge. Its criteria are anchored ratings, not counts, so small score differences are within noise. Compare models over several recordings when possible.
- The reference is treated as truth. Mistakes in it count against every model equally.
- Hosted transcription sends the audio to OpenRouter providers, and grading sends both transcripts to Anthropic. Use recordings that are allowed to leave the machine. Local Whisper keeps the audio on this Mac, but grading still sends its transcript.

## Stored data

Benchmarks live in the same SQLite database as other runs. `asr_benchmarks` stores the reference text, its SHA-256, the models, the chunk sizes, and the run options. `asr_cells` links each model and chunk size to its Speech to text run and stores the judgement, score, and WER. **Export JSON** includes the reference, every transcript, every judgement, and the judge prompt.
