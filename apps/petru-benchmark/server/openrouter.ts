import { z } from 'zod';
import { OPENROUTER_MODELS, type OpenRouterModelId } from '../shared/models';
import type { RunOptions, Config } from '../shared/schema';
import { buildWhisperPrompt } from '../shared/prompt';

export const OPENROUTER_URL = 'https://openrouter.ai/api/v1/audio/transcriptions';

export function buildRequest(modelId: OpenRouterModelId, options: RunOptions) {
  const model = OPENROUTER_MODELS.find(m => m.id === modelId)!;
  const providerOptions = structuredClone(options.providerOptions);
  const prompt = buildWhisperPrompt(options);
  if (model.family === 'whisper' && prompt) {
    // OpenRouter documents this exact passthrough. It applies only if Groq
    // serves the request; the STT endpoint cannot pin providers.
    providerOptions.groq = {
      prompt,
      ...providerOptions.groq,
    };
  }
  return {
    model: modelId,
    temperature: options.temperature,
    response_format: options.timestamps ? 'verbose_json' : 'json',
    ...(options.language !== 'auto' ? { language: options.language } : {}),
    ...(options.timestamps ? { timestamp_granularities: ['segment', 'word'] } : {}),
    ...(Object.keys(providerOptions).length ? { provider: { options: providerOptions } } : {}),
  };
}

// Strip credential fields even from custom provider options and upstream errors.
export function redact(value: unknown, secret = ''): unknown {
  if (typeof value === 'string') return secret ? value.replaceAll(secret, '[redacted]') : value;
  if (Array.isArray(value)) return value.map(item => redact(item, secret));
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, /^(authorization|api[-_]?key|token|access_token)$/i.test(key) ? '[redacted]' : redact(item, secret)]));
  return value;
}

const responseSchema = z.object({
  text: z.string(),
  usage: z.object({ cost: z.number().finite().nonnegative().optional() }).passthrough().optional(),
}).passthrough();

export class TranscriptionError extends Error {
  constructor(message: string, readonly body: unknown, readonly generationId: string | null, readonly latencyMs: number) { super(message); }
}

export async function transcribe(
  modelId: OpenRouterModelId, options: RunOptions, audio: Uint8Array, apiKey: string,
  fetcher: typeof fetch = fetch, signal?: AbortSignal,
) {
  const started = performance.now();
  const controller = AbortSignal.timeout(90_000);
  const response = await fetcher(OPENROUTER_URL, {
    method: 'POST',
    headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json', 'X-OpenRouter-Title': 'Speechbench' },
    body: JSON.stringify({ ...buildRequest(modelId, options), input_audio: { format: 'wav', data: Buffer.from(audio).toString('base64') } }),
    signal: signal ? AbortSignal.any([signal, controller]) : controller,
  });
  const generationId = response.headers.get('x-generation-id');
  const raw = await response.text();
  let body: unknown;
  try { body = JSON.parse(raw); } catch { body = { message: raw.slice(0, 10000) }; }
  body = redact(body, apiKey);
  const latencyMs = Math.round(performance.now() - started);
  if (!response.ok) {
    const detail = z.object({ error: z.union([z.string(), z.object({ message: z.string() }).passthrough()]).optional(), message: z.string().optional() }).safeParse(body);
    const error = detail.success ? detail.data.error : undefined;
    const message = typeof error === 'string' ? error : error?.message ?? (detail.success ? detail.data.message : undefined);
    throw new TranscriptionError(`OpenRouter ${response.status}: ${message || response.statusText || 'Request failed'}`, body, generationId, latencyMs);
  }
  const parsed = responseSchema.safeParse(body);
  if (!parsed.success) throw new TranscriptionError('OpenRouter returned no transcript text. The raw response was saved.', body, generationId, latencyMs);
  return { text: parsed.data.text, cost: parsed.data.usage?.cost ?? null, response: body, generationId, latencyMs };
}

export async function fetchCatalog(fetcher: typeof fetch = fetch): Promise<Config['catalog']> {
  try {
    const response = await fetcher('https://openrouter.ai/api/v1/models?output_modalities=transcription', { signal: AbortSignal.timeout(10000) });
    if (!response.ok) throw new Error(`Catalog returned ${response.status}.`);
    const data = z.object({ data: z.array(z.object({ id: z.string() })) }).parse(await response.json());
    return { checkedAt: new Date().toISOString(), ids: data.data.map(m => m.id), error: null };
  } catch {
    return { checkedAt: null, ids: null, error: 'Live availability could not be checked. The verified model list remains available.' };
  }
}
