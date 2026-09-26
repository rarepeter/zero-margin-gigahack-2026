import { z } from 'zod';

// Open-weight text models that fit a 48 GB M4 Pro next to Whisper at 4–8 bit.
// Licenses and parameter counts were checked on Hugging Face on 2026-09-26.
// Memory is weights only (≈0.6 GB per billion parameters at Q4_K_M, ≈1.06 at Q8_0); add KV cache for long transcripts.
// aaIndex is the Artificial Analysis Intelligence Index for the listed setting, where published (2026-09-26).
const hostedMomModels = [
  { id: 'qwen/qwen3.8-27b', name: 'Qwen3.8 27B', maker: 'Qwen', size: '27.8B dense', license: 'Apache-2.0', weights: 'https://huggingface.co/Qwen/Qwen3.8-27B', memory: '≈17 GB Q4 · ≈30 GB Q8', aaIndex: '34 (xhigh) · 28 (medium)', note: 'Highest intelligence index among open models that fit. Dense, so slower locally.' },
  { id: 'qwen/qwen3.6-35b-a3b', name: 'Qwen3.6 35B-A3B', maker: 'Qwen', size: '36B MoE · 3B active', license: 'Apache-2.0', weights: 'https://huggingface.co/Qwen/Qwen3.6-35B-A3B', memory: '≈22 GB Q4 · ≈38 GB Q8', aaIndex: '18 (reasoning)', note: 'Fast MoE. Q8 needs a raised GPU memory limit next to Whisper.' },
  { id: 'google/gemma-4-31b-it', name: 'Gemma 4 31B', maker: 'Google', size: '31.3B dense', license: 'Apache-2.0', weights: 'https://huggingface.co/google/gemma-4-31B-it', memory: '≈19 GB Q4 · ≈33 GB Q8', aaIndex: '19 (reasoning)', note: 'Strong multilingual lineage. Dense, so slower locally.' },
  { id: 'google/gemma-4-26b-a4b-it', name: 'Gemma 4 26B-A4B', maker: 'Google', size: '25.8B MoE · 3.8B active', license: 'Apache-2.0', weights: 'https://huggingface.co/google/gemma-4-26B-A4B-it', memory: '≈16 GB Q4 · ≈27 GB Q8', aaIndex: '17 (reasoning)', note: 'Fast MoE sibling of Gemma 4 31B.' },
  { id: 'meta/muse-glimmer-30b', name: 'Muse Glimmer 30B', maker: 'Meta', size: '29.8B dense', license: 'Apache-2.0', weights: 'https://huggingface.co/meta-models/Muse-Glimmer-30B', memory: '≈18 GB Q4 · ≈32 GB Q8', aaIndex: '17 (high)', note: 'Recent dense model. Romanian quality unknown.' },
  { id: 'nvidia/nemotron-3.5-lightning', name: 'Nemotron 3.5 Lightning', maker: 'NVIDIA', size: '31.6B MoE · 3B active', license: 'OpenMDW-1.1', weights: 'https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16', memory: '≈19 GB Q4 · ≈34 GB Q8', aaIndex: null, note: 'Exploratory. Romanian and Russian are absent from its model card language list.' },
  { id: 'z-ai/glm-4.7-flash', name: 'GLM-4.7-Flash', maker: 'Z.ai', size: '31.2B MoE · 3B active', license: 'MIT', weights: 'https://huggingface.co/zai-org/GLM-4.7-Flash', memory: '≈19 GB Q4 · ≈33 GB Q8', aaIndex: null, note: 'Fast MoE. Model card lists English and Chinese.' },
  { id: 'openai/gpt-oss-20b', name: 'gpt-oss-20b', maker: 'OpenAI', size: '20.9B MoE · 3.6B active', license: 'Apache-2.0', weights: 'https://huggingface.co/openai/gpt-oss-20b', memory: '≈13 GB MXFP4 (native)', aaIndex: null, note: 'Smallest footprint. Native 4-bit weights match local behavior closely.' },
  { id: 'mistralai/mistral-small-3.2-24b-instruct', name: 'Mistral Small 3.2 24B', maker: 'Mistral', size: '24B dense', license: 'Apache-2.0', weights: 'https://huggingface.co/mistralai/Mistral-Small-3.2-24B-Instruct-2506', memory: '≈14 GB Q4 · ≈26 GB Q8', aaIndex: null, note: 'Non-reasoning baseline. Model card lists Russian.' },
] as const;

// Quantized GGUF builds of the hosted leader, served on this Mac by llama.cpp one at a time.
// Paths come from the named .env variables. Meta publishes only 4-bit GGUFs, so 8-bit comes from Unsloth.
export const LOCAL_MOM_MODELS = [
  { id: 'local/muse-glimmer-30b-q4_k_m', name: 'Muse Glimmer 30B · Q4_K_M', maker: 'Meta', size: '29.8B dense · 4-bit', license: 'Apache-2.0', weights: 'https://huggingface.co/meta-models/Muse-Glimmer-30B-GGUF', memory: '16.8 GB GGUF', aaIndex: null, env: 'MUSE_GLIMMER_Q4_GGUF', note: 'Runs on this Mac with llama.cpp. Official Meta 4-bit quantization.' },
  { id: 'local/muse-glimmer-30b-q8_0', name: 'Muse Glimmer 30B · Q8_0', maker: 'Meta', size: '29.8B dense · 8-bit', license: 'Apache-2.0', weights: 'https://huggingface.co/unsloth/Muse-Glimmer-30B-GGUF', memory: '29.6 GB GGUF', aaIndex: null, env: 'MUSE_GLIMMER_Q8_GGUF', note: 'Runs on this Mac with llama.cpp. 8-bit quantization by Unsloth; Meta publishes no 8-bit GGUF.' },
] as const;
export const MOM_MODELS = [
  ...hostedMomModels.map(model => ({ ...model, provider: 'openrouter' as const })),
  ...LOCAL_MOM_MODELS.map(model => ({ ...model, provider: 'local' as const })),
];
export type HostedMomModelId = (typeof hostedMomModels)[number]['id'];
export type LocalMomModelId = (typeof LOCAL_MOM_MODELS)[number]['id'];
export type MomModelId = HostedMomModelId | LocalMomModelId;
export const isLocalMomModel = (id: string): id is LocalMomModelId => LOCAL_MOM_MODELS.some(model => model.id === id);
export const momModelIds: [MomModelId, ...MomModelId[]] = [MOM_MODELS[0].id, ...MOM_MODELS.slice(1).map(m => m.id)];
// The judge writes its own minutes under this pseudo model ID before scoring.
export const REFERENCE_ID = 'judge/reference';
export const JUDGE_MODEL = 'claude-opus-5-5';

export const MEETING_TYPES = ['clinical', 'financial', 'administrative', 'executive', 'operational', 'crisis'] as const;
export const ITEM_KINDS = ['decision', 'action', 'finding', 'risk', 'open_question'] as const;

// A fictional transcript plus the hidden answer key the judge scores against.
// Models only ever receive `transcript`.
export const momTranscriptSchema = z.object({
  id: z.string().regex(/^[a-z]+-\d{2}$/),
  meetingType: z.enum(MEETING_TYPES),
  title: z.string().min(5),
  scenario: z.string().min(20),
  transcript: z.string().min(2000),
  answerKey: z.object({
    items: z.array(z.object({
      id: z.string().regex(/^[A-Z]\d+$/),
      kind: z.enum(ITEM_KINDS),
      text: z.string().min(10),
      // Actions only. null means the recording never states one, so the MoM must not invent it.
      owner: z.string().nullable().optional(),
      deadline: z.string().nullable().optional(),
      critical: z.boolean().default(false),
    }).refine(item => item.kind !== 'action' || (item.owner !== undefined && item.deadline !== undefined), 'Actions need owner and deadline (null when unstated).')).min(1),
    traps: z.array(z.object({ id: z.string().regex(/^T\d+$/), text: z.string().min(10) })),
  }),
}).strict();
export type MomTranscript = z.infer<typeof momTranscriptSchema>;
export type KeyItem = MomTranscript['answerKey']['items'][number];

// What the judge returns per candidate. The score is computed from it in code.
const quality = z.number().int().min(1).max(5);
const fieldVerdict = z.enum(['correct', 'missing', 'wrong', 'invented', 'na']);
export const judgementSchema = z.object({
  items: z.array(z.object({
    id: z.string(), verdict: z.enum(['correct', 'partial', 'missing', 'wrong']),
    owner: fieldVerdict, deadline: fieldVerdict, note: z.string(),
  })),
  traps: z.array(z.object({ id: z.string(), verdict: z.enum(['avoided', 'fell']), note: z.string() })),
  hallucinations: z.array(z.object({ claim: z.string(), severity: z.enum(['minor', 'major']), note: z.string() })),
  quality: z.object({ structure: quality, concision: quality, language: quality, terminology: quality, uncertainty: quality }),
  summary: z.string(),
});
export type Judgement = z.infer<typeof judgementSchema>;
// The Claude CLI validates structured output with a draft-07 validator.
export const judgementJsonSchema = z.toJSONSchema(judgementSchema, { target: 'draft-7' });

export const SCORE_WEIGHTS = { coverage: 0.5, attribution: 0.15, traps: 0.2, quality: 0.15 } as const;
export const HALLUCINATION_PENALTY = { major: 6, minor: 2 } as const;
const kindWeight: Record<KeyItem['kind'], number> = { decision: 3, action: 3, finding: 2, risk: 1.5, open_question: 1.5 };
const itemValue = { correct: 1, partial: 0.5, missing: 0, wrong: -0.5 } as const;
const fieldValue = { correct: 1, missing: 0, wrong: 0, invented: -1, na: 0 } as const;

export type ScoreBreakdown = { coverage: number; attribution: number; traps: number; quality: number; penalty: number; total: number };

// Deterministic 0–100 score. Unjudged key items count as missing, so a judge that skips items cannot inflate a score.
export function scoreJudgement(key: MomTranscript['answerKey'], judgement: Judgement): ScoreBreakdown {
  const verdicts = new Map(judgement.items.map(item => [item.id, item]));
  let earned = 0, possible = 0, fields = 0, fieldsPossible = 0;
  for (const item of key.items) {
    const weight = kindWeight[item.kind] * (item.critical ? 2 : 1);
    const verdict = verdicts.get(item.id);
    possible += weight;
    earned += weight * itemValue[verdict?.verdict ?? 'missing'];
    if (item.kind === 'action') {
      fieldsPossible += 2;
      fields += fieldValue[verdict?.owner ?? 'missing'] + fieldValue[verdict?.deadline ?? 'missing'];
    }
  }
  const trapVerdicts = new Map(judgement.traps.map(trap => [trap.id, trap.verdict]));
  const avoided = key.traps.filter(trap => trapVerdicts.get(trap.id) === 'avoided').length;
  const q = Object.values(judgement.quality);
  const parts = {
    coverage: Math.max(0, earned / possible),
    attribution: fieldsPossible ? Math.max(0, fields / fieldsPossible) : 1,
    traps: key.traps.length ? avoided / key.traps.length : 1,
    quality: q.reduce((sum, value) => sum + value - 1, 0) / (q.length * 4),
  };
  const penalty = judgement.hallucinations.reduce((sum, h) => sum + HALLUCINATION_PENALTY[h.severity], 0);
  const weighted = (Object.keys(SCORE_WEIGHTS) as (keyof typeof SCORE_WEIGHTS)[]).reduce((sum, part) => sum + SCORE_WEIGHTS[part] * parts[part], 0) * 100;
  const round = (value: number) => Math.round(value * 1000) / 10;
  return {
    coverage: round(parts.coverage), attribution: round(parts.attribution), traps: round(parts.traps), quality: round(parts.quality),
    penalty, total: Math.round(Math.min(100, Math.max(0, weighted - penalty)) * 10) / 10,
  };
}

export const createMomRunSchema = z.object({
  models: z.array(z.enum(momModelIds)).min(1).transform(ids => [...new Set(ids)]),
  transcripts: z.array(z.string()).min(1).transform(ids => [...new Set(ids)]),
}).strict();

export type MomCellStatus = 'queued' | 'generating' | 'judging' | 'completed' | 'failed' | 'interrupted';
export type MomUsage = { promptTokens: number | null; completionTokens: number | null; reasoningTokens: number | null };
// One model × transcript result. The judge's reference minutes use modelId REFERENCE_ID and are never graded.
// Measured by llama.cpp on this Mac. Null fields were not reported.
export type LocalStats = {
  loadMs: number | null; promptTokensPerSecond: number | null; generationTokensPerSecond: number | null;
};
export type MomCell = {
  id: string; runId: string; transcriptId: string; modelId: string; status: MomCellStatus;
  // True once the minutes exist, so a retry only repeats the failed step.
  generated: boolean; output: string;
  latencyMs: number | null; cost: number | null; usage: MomUsage | null; provider: string | null; finishReason: string | null; local: LocalStats | null;
  judgement: Judgement | null; score: ScoreBreakdown | null; judgeLatencyMs: number | null; judgeCost: number | null;
  error: string | null;
};
export type MomTranscriptSummary = Pick<MomTranscript, 'id' | 'meetingType' | 'title' | 'scenario'> & { words: number; items: number; traps: number };
export type MomRun = {
  id: string; createdAt: string; models: string[]; transcripts: MomTranscriptSummary[];
  settings: { judgeModel: string; judgeEffort: string; reasoningEffort: string; maxTokens: number; promptSha256: string };
  cells: MomCell[];
};
export type LocalMomStatus = { available: boolean; path: string | null; error: string | null };
export type MomConfig = {
  keyConfigured: boolean;
  local: Record<LocalMomModelId, LocalMomStatus>;
  judge: { available: boolean; model: string; error: string | null };
  transcripts: MomTranscriptSummary[];
  datasetError: string | null;
};
