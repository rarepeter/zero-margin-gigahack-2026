import { z } from 'zod';
import { OPENROUTER_MODELS, type OpenRouterModelId } from '../shared/models';
import type { RunOptions, Config } from '../shared/schema';
import { buildWhisperPrompt } from '../shared/prompt';
import type { MomModelId } from '../shared/mom';
import { MOM_SYSTEM_PROMPT, buildMomUserMessage } from '../shared/mom-prompt';

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

function upstreamError(response: Response, body: unknown) {
  const detail = z.object({ error: z.union([z.string(), z.object({ message: z.string() }).passthrough()]).optional(), message: z.string().optional() }).safeParse(body);
  const error = detail.success ? detail.data.error : undefined;
  const message = typeof error === 'string' ? error : error?.message ?? (detail.success ? detail.data.message : undefined);
  return `OpenRouter ${response.status}: ${message || response.statusText || 'Request failed'}`;
}

// A failed OpenRouter request, carrying the saved response for the run log.
export class UpstreamError extends Error {
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
  if (!response.ok) throw new UpstreamError(upstreamError(response, body), body, generationId, latencyMs);
  const parsed = responseSchema.safeParse(body);
  if (!parsed.success) throw new UpstreamError('OpenRouter returned no transcript text. The raw response was saved.', body, generationId, latencyMs);
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

export const OPENROUTER_CHAT_URL = 'https://openrouter.ai/api/v1/chat/completions';
export const MOM_REASONING_EFFORT = 'medium';

// One request shape for every MoM model. Models without reasoning ignore the effort;
// temperature stays at each model's default because several reasoning models loop at zero.
export function buildMomRequest(modelId: MomModelId, transcript: string) {
  return {
    model: modelId,
    messages: [{ role: 'system', content: MOM_SYSTEM_PROMPT }, { role: 'user', content: buildMomUserMessage(transcript) }],
    reasoning: { effort: MOM_REASONING_EFFORT },
    max_tokens: 32000,
    usage: { include: true },
  };
}

const chatSchema = z.object({
  provider: z.string().optional(),
  choices: z.array(z.object({
    finish_reason: z.string().nullable().optional(),
    message: z.object({ content: z.string().nullable() }).passthrough(),
  }).passthrough()).min(1),
  usage: z.object({
    prompt_tokens: z.number().optional(), completion_tokens: z.number().optional(), cost: z.number().optional(),
    completion_tokens_details: z.object({ reasoning_tokens: z.number().nullable().optional() }).passthrough().nullable().optional(),
  }).passthrough().optional(),
}).passthrough();

export async function generateMom(modelId: MomModelId, transcript: string, apiKey: string, fetcher: typeof fetch = fetch, signal?: AbortSignal) {
  const started = performance.now();
  const timeout = AbortSignal.timeout(15 * 60_000);
  const response = await fetcher(OPENROUTER_CHAT_URL, {
    method: 'POST',
    headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json', 'X-OpenRouter-Title': 'Speechbench MoM' },
    body: JSON.stringify(buildMomRequest(modelId, transcript)),
    signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
    // Disable Bun's ~5-minute first-byte timeout so the 15-minute limit above applies to slow reasoning models.
    timeout: false,
  });
  const generationId = response.headers.get('x-generation-id');
  const raw = await response.text();
  let body: unknown;
  try { body = JSON.parse(raw); } catch { body = { message: raw.slice(0, 10000) }; }
  body = redact(body, apiKey);
  const latencyMs = Math.round(performance.now() - started);
  if (!response.ok) throw new UpstreamError(upstreamError(response, body), body, generationId, latencyMs);
  const parsed = chatSchema.safeParse(body);
  if (!parsed.success) throw new UpstreamError('OpenRouter returned no completion. The raw response was saved.', body, generationId, latencyMs);
  const [choice] = parsed.data.choices;
  // Some providers inline the reasoning; the minutes start after it.
  const text = (choice.message.content ?? '').replace(/^\s*<think>[\s\S]*?<\/think>/, '').trim();
  const usage = parsed.data.usage;
  return {
    text, latencyMs, generationId, response: body,
    cost: usage?.cost ?? null, provider: parsed.data.provider ?? null, finishReason: choice.finish_reason ?? null,
    usage: { promptTokens: usage?.prompt_tokens ?? null, completionTokens: usage?.completion_tokens ?? null, reasoningTokens: usage?.completion_tokens_details?.reasoning_tokens ?? null },
  };
}
