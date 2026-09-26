import type { RunOptions } from './schema';

// Context for the user's hospital recordings. Research and limits: docs/benchmark.md.
export const HOSPITAL_CONTEXT_PROMPT = 'Hospital conversation in Moldova. Mixed Romanian, Russian and occasional English, including switches within a sentence and regional Romanian expressions. Medical terms, medication names, procedures and clinical abbreviations. Verbatim in the spoken language: Romanian diacritics, Russian Cyrillic, English. Preserve abbreviations, negations, numbers, doses and units. No translation, summaries, expanded abbreviations or guessed words.';

export function buildWhisperPrompt(options: Pick<RunOptions, 'contextPrompt' | 'vocabulary'>) {
  const vocabulary = options.vocabulary.trim();
  // A complete phrase avoids leaving Whisper to continue an unfinished term list.
  const hint = vocabulary ? `Vocabulary: ${vocabulary}${/[.!?]$/.test(vocabulary) ? '' : '.'}` : '';
  return [options.contextPrompt.trim(), hint].filter(Boolean).join('\n\n');
}
