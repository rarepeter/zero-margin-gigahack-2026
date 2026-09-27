import { z } from 'zod';
import { modelIds } from './models';
import { MIN_CHUNK_SECONDS, MAX_CHUNK_SECONDS } from './chunking';
import type { Recording, RunStatus } from './schema';

// An accuracy benchmark: one recording, a human reference transcript, and every selected model
// transcribed once per chunk size. Each transcript is graded against the reference by the judge.
export const MAX_REFERENCE_CHARS = 500_000;
export const createAsrBenchmarkSchema = z.object({
  audioId: z.string().uuid(),
  models: z.array(z.enum(modelIds)).min(1).transform(ids => [...new Set(ids)]),
  chunkSeconds: z.array(z.number().int().min(MIN_CHUNK_SECONDS).max(MAX_CHUNK_SECONDS)).min(1).max(8)
    .transform(sizes => [...new Set(sizes)].sort((a, b) => a - b)),
  reference: z.object({
    name: z.string().min(1).max(200).regex(/\.(md|markdown|txt)$/i, 'The reference transcript must be a .md or .txt file.'),
    text: z.string().max(MAX_REFERENCE_CHARS).refine(text => text.trim().length > 0, 'The reference transcript is empty.'),
  }),
  useContext: z.boolean().default(true),
}).strict();
export type CreateAsrBenchmark = z.input<typeof createAsrBenchmarkSchema>;

// Content criteria only: formatting, punctuation, capitalization, and script are ignored by design.
const percent = z.number().int().min(0).max(100);
const criteriaSchema = z.object({ completeness: percent, accuracy: percent, terminology: percent, language: percent, hallucination: percent });
type Criterion = keyof z.infer<typeof criteriaSchema>;
export const ASR_CRITERIA = {
  completeness: { weight: 0.3, label: 'Completeness', help: 'Share of the spoken content present' },
  accuracy: { weight: 0.3, label: 'Meaning', help: 'Meaning preserved in what was transcribed' },
  terminology: { weight: 0.2, label: 'Terms & numbers', help: 'Medical terms, drugs, doses, numbers, names' },
  language: { weight: 0.1, label: 'Language', help: 'Romanian, Russian, and English kept as spoken' },
  hallucination: { weight: 0.1, label: 'No invention', help: '100 means no invented or looping text' },
} as const satisfies Record<Criterion, { weight: number; label: string; help: string }>;
const criterionNames = Object.keys(ASR_CRITERIA) as Criterion[];

export const asrJudgementSchema = z.object({
  errors: z.array(z.object({
    category: z.enum(['omission', 'substitution', 'insertion', 'terminology', 'number', 'negation', 'language', 'repetition']),
    severity: z.enum(['critical', 'major', 'minor']),
    reference: z.string(), hypothesis: z.string(), note: z.string(),
  })),
  criteria: criteriaSchema,
  summary: z.string(),
});
export type AsrJudgement = z.infer<typeof asrJudgementSchema>;
// The Claude CLI validates structured output with a draft-07 validator.
export const asrJudgementJsonSchema = z.toJSONSchema(asrJudgementSchema, { target: 'draft-7' });

// Weighted mean of the judge's criteria, 0–100 with one decimal.
export function scoreAsr(judgement: AsrJudgement) {
  const total = criterionNames.reduce((sum, name) => sum + ASR_CRITERIA[name].weight * judgement.criteria[name], 0);
  return Math.round(total * 10) / 10;
}

// Word error rate after removing what the score also ignores: formatting, punctuation, case,
// speaker labels, timestamps, "(?)" uncertainty marks, and parenthetical standard forms.
// Russian in Cyrillic versus Latin transliteration still counts as different words here.
export function normalizeWords(text: string) {
  return text.normalize('NFC')
    .replace(/[şŞţŢ]/g, c => ({ ş: 'ș', Ş: 'Ș', ţ: 'ț', Ţ: 'Ț' })[c]!)
    .replace(/\([^()]*\)/g, ' ')
    .replace(/\[[^\]]*\]/g, ' ')
    .replace(/(^|\s)\p{Lu}{1,2}\d?:(?=\s|$)/gmu, ' ')
    .toLowerCase()
    .replace(/[\p{P}\p{S}]+/gu, ' ')
    .split(/\s+/u)
    .filter(Boolean);
}

export function wordErrorRate(reference: string, hypothesis: string) {
  const ref = normalizeWords(reference);
  const hyp = normalizeWords(hypothesis);
  if (!ref.length) return null;
  // Two-row Levenshtein distance over words.
  let previous = Uint32Array.from({ length: hyp.length + 1 }, (_, i) => i);
  let current = new Uint32Array(hyp.length + 1);
  for (let i = 1; i <= ref.length; i++) {
    current[0] = i;
    for (let j = 1; j <= hyp.length; j++) {
      current[j] = Math.min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ref[i - 1] === hyp[j - 1] ? 0 : 1));
    }
    [previous, current] = [current, previous];
  }
  return Math.round((previous[hyp.length] / ref.length) * 1000) / 10;
}

export type AsrCellStatus = 'transcribing' | 'judging' | 'completed' | 'failed' | 'interrupted';
// One model × chunk size. Transcription progress comes from the linked ASR run result.
export type AsrCell = {
  id: string; benchmarkId: string; modelId: string; chunkSeconds: number; runId: string; resultId: string;
  status: AsrCellStatus; transcription: { status: RunStatus; completedChunks: number; totalChunks: number; latencyMs: number; cost: number | null };
  judgement: AsrJudgement | null; score: number | null; wer: number | null; judgeLatencyMs: number | null; error: string | null;
};
export type AsrBenchmark = {
  id: string; createdAt: string; recording: Recording; models: string[]; chunkSeconds: number[];
  reference: { name: string; words: number; sha256: string };
  settings: { judgeModel: string; judgeEffort: string; contextPrompt: string };
  cells: AsrCell[];
};
