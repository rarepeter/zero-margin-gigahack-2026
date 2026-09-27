import { z } from 'zod';
import { modelIds } from './models';
import { DEFAULT_CHUNK_SECONDS, MIN_CHUNK_SECONDS, MAX_CHUNK_SECONDS } from './chunking';

export const runOptionsSchema = z.object({
  chunkSeconds: z.number().int().min(MIN_CHUNK_SECONDS).max(MAX_CHUNK_SECONDS).default(DEFAULT_CHUNK_SECONDS),
  language: z.enum(['auto', 'ro', 'ru', 'en']).default('auto'),
  temperature: z.number().min(0).max(1).default(0),
  timestamps: z.boolean().default(false),
  contextPrompt: z.string().max(1500).default(''),
  vocabulary: z.string().max(1500).default(''),
  providerOptions: z.record(z.string(), z.record(z.string(), z.json())).default({}),
}).strict();
export type RunOptions = z.infer<typeof runOptionsSchema>;
export const createRunSchema = z.object({
  audioId: z.string().uuid(),
  models: z.array(z.enum(modelIds)).min(1).max(modelIds.length).transform(ids => [...new Set(ids)]),
  options: runOptionsSchema,
}).strict();
export type CreateRun = z.infer<typeof createRunSchema>;
export type RunStatus = 'queued' | 'running' | 'completed' | 'failed' | 'interrupted';
export type Recording = {
  id: string; name: string; bytes: number; duration: number; createdAt: string;
  chunkCount: number; sha256: string;
};
export type Run = {
  id: string; audioId: string; createdAt: string; options: RunOptions;
  models: string[]; recording: Recording; chunkCount: number; results: ModelResult[];
};
export type ChunkResult = {
  index: number; start: number; end: number; status: 'completed' | 'failed';
  text: string; latencyMs: number; cost: number | null; error: string | null;
  request: Record<string, unknown>; response: unknown; generationId: string | null;
};
export type ModelResult = {
  id: string; runId: string; modelId: string; status: RunStatus;
  transcript: string; completedChunks: number; totalChunks: number;
  latencyMs: number; cost: number | null; error: string | null;
  chunks: ChunkResult[];
};
export type TranscriptionOutput = Pick<ChunkResult, 'text' | 'latencyMs' | 'cost' | 'response' | 'generationId'>;
export type LocalModelStatus = {
  available: boolean;
  state: 'unavailable' | 'idle' | 'loading' | 'ready' | 'running' | 'error';
  device: string | null;
  error: string | null;
};
export type Config = {
  localWhisper: LocalModelStatus;
  keyConfigured: boolean; ffmpegAvailable: boolean; maxUploadMB: number;
  catalog: { checkedAt: string | null; ids: string[] | null; error: string | null };
};
