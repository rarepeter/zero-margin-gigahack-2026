import { existsSync } from 'node:fs';
import type { Subprocess } from 'bun';
import { z } from 'zod';
import { LOCAL_MOM_MODELS, type LocalMomModelId, type LocalMomStatus, type LocalStats, type MomUsage } from '../shared/mom';
import { MOM_SYSTEM_PROMPT, buildMomUserMessage } from '../shared/mom-prompt';
import { MOM_REASONING_EFFORT } from './openrouter';

export type LocalMomOutput = {
  text: string; latencyMs: number; finishReason: string | null; usage: MomUsage; local: LocalStats; response: unknown;
};
// What the MoM runner needs from a local backend. Tests inject a fake.
export type LocalMom = {
  status(modelId: LocalMomModelId): LocalMomStatus;
  generate(modelId: LocalMomModelId, transcript: string, signal: AbortSignal): Promise<LocalMomOutput>;
  close(): Promise<void>;
};

// One slot. When it frees, a waiter for the model already in memory goes first, so a run
// finishes every job for one model before paying to load the next.
export class AffinityQueue {
  private busy = false;
  private waiting: { key: string; start: () => void }[] = [];
  constructor(private current: () => string | null) {}
  async acquire(key: string) {
    if (!this.busy) { this.busy = true; return; }
    await new Promise<void>(start => this.waiting.push({ key, start }));
  }
  // Returns true when nothing is waiting, so the caller can free memory.
  release() {
    const index = this.waiting.findIndex(waiter => waiter.key === this.current());
    const [next] = this.waiting.splice(index >= 0 ? index : 0, 1);
    if (next) { next.start(); return false; }
    this.busy = false;
    return true;
  }
}

// Model defaults from meta-models/Muse-Glimmer-30B generation_config.json, the same values OpenRouter serves.
// reasoning_strength is the chat template's name for reasoning effort.
export function buildLocalMomRequest(transcript: string) {
  return {
    messages: [{ role: 'system', content: MOM_SYSTEM_PROMPT }, { role: 'user', content: buildMomUserMessage(transcript) }],
    max_tokens: 32000, temperature: 1.0, top_p: 0.95, top_k: 64,
    chat_template_kwargs: { reasoning_strength: MOM_REASONING_EFFORT },
  };
}

const completionSchema = z.object({
  choices: z.array(z.object({
    finish_reason: z.string().nullable().optional(),
    message: z.object({ content: z.string().nullable().optional(), reasoning_content: z.string().nullable().optional() }).passthrough(),
  }).passthrough()).min(1),
  usage: z.object({ prompt_tokens: z.number().optional(), completion_tokens: z.number().optional() }).passthrough().optional(),
  timings: z.object({ prompt_per_second: z.number().optional(), predicted_per_second: z.number().optional() }).passthrough().optional(),
}).passthrough();

// Runs llama.cpp's llama-server with one GGUF at a time and stops it when no local work is waiting,
// so at most one model occupies unified memory.
export class LlamaServer implements LocalMom {
  private child: Subprocess | null = null;
  private loaded: LocalMomModelId | null = null;
  private port = 0;
  private queue = new AffinityQueue(() => this.loaded);
  constructor(private options: { bin: string; paths: Partial<Record<LocalMomModelId, string>>; contextTokens: number }) {}

  status(modelId: LocalMomModelId): LocalMomStatus {
    const model = LOCAL_MOM_MODELS.find(m => m.id === modelId)!;
    const path = this.options.paths[modelId] || null;
    if (!this.options.bin) return { available: false, path, error: 'llama-server not found. Install it with brew install llama.cpp, or set LLAMA_SERVER_BIN.' };
    if (!path) return { available: false, path, error: `Set ${model.env} in .env to the downloaded GGUF file.` };
    if (!existsSync(path)) return { available: false, path, error: `${model.env} points to a missing file.` };
    return { available: true, path, error: null };
  }

  async generate(modelId: LocalMomModelId, transcript: string, signal: AbortSignal): Promise<LocalMomOutput> {
    await this.queue.acquire(modelId);
    try {
      signal.throwIfAborted();
      const loadMs = await this.load(modelId, signal);
      const started = performance.now();
      const response = await fetch(`http://127.0.0.1:${this.port}/v1/chat/completions`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildLocalMomRequest(transcript)),
        signal: AbortSignal.any([signal, AbortSignal.timeout(90 * 60_000)]),
        // Bun's fetch otherwise aborts after ~5 minutes without a first byte; minutes arrive in one response.
        timeout: false,
      });
      const body: unknown = await response.json().catch(() => null);
      const latencyMs = Math.round(performance.now() - started);
      if (!response.ok) throw new Error(`llama-server ${response.status}: ${JSON.stringify(body).slice(0, 400)}`);
      const parsed = completionSchema.parse(body);
      const [choice] = parsed.choices;
      const reasoning = choice.message.reasoning_content ?? '';
      return {
        text: (choice.message.content ?? '').replace(/^\s*<think>[\s\S]*?<\/think>/, '').trim(), latencyMs, response: body,
        finishReason: choice.finish_reason ?? null,
        usage: {
          promptTokens: parsed.usage?.prompt_tokens ?? null, completionTokens: parsed.usage?.completion_tokens ?? null,
          reasoningTokens: reasoning ? await this.countTokens(reasoning) : 0,
        },
        local: {
          loadMs,
          promptTokensPerSecond: parsed.timings?.prompt_per_second ?? null, generationTokensPerSecond: parsed.timings?.predicted_per_second ?? null,
        },
      };
    } finally {
      if (this.queue.release()) await this.stop();
    }
  }

  // Starts llama-server for the model unless it is already loaded. Returns load time, or null when reused.
  private async load(modelId: LocalMomModelId, signal: AbortSignal) {
    if (this.loaded === modelId && this.child && this.child.exitCode === null) return null;
    await this.stop();
    const status = this.status(modelId);
    if (!status.available) throw new Error(status.error!);
    const started = performance.now();
    this.port = await freePort();
    const child = Bun.spawn([
      this.options.bin, '-m', status.path!, '--host', '127.0.0.1', '--port', String(this.port),
      '-c', String(this.options.contextTokens), '-np', '1', '-ngl', '999', '-fa', 'on', '--jinja', '--no-webui',
      '--reasoning-format', 'deepseek',
    ], { stdout: 'ignore', stderr: 'pipe' });
    this.child = child;
    this.loaded = modelId;
    // Drain the log so a full pipe never blocks the server; the tail explains load failures.
    const stderr = new Response(child.stderr).text();
    const deadline = Date.now() + 10 * 60_000;
    while (Date.now() < deadline) {
      signal.throwIfAborted();
      if (child.exitCode !== null) {
        const log = (await stderr).trim().split('\n').slice(-5).join(' ');
        this.child = null; this.loaded = null;
        throw new Error(`llama-server exited while loading the model: ${log.slice(0, 500)}`);
      }
      const healthy = await fetch(`http://127.0.0.1:${this.port}/health`).then(r => r.ok, () => false);
      if (healthy) return Math.round(performance.now() - started);
      await Bun.sleep(500);
    }
    await this.stop();
    throw new Error('llama-server did not become ready within 10 minutes.');
  }

  private async countTokens(content: string) {
    const response = await fetch(`http://127.0.0.1:${this.port}/tokenize`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content }) });
    const parsed = z.object({ tokens: z.array(z.unknown()) }).safeParse(await response.json().catch(() => null));
    return parsed.success ? parsed.data.tokens.length : null;
  }

  private async stop() {
    const child = this.child;
    this.child = null; this.loaded = null;
    if (!child || child.exitCode !== null) return;
    child.kill('SIGTERM');
    const exited = await Promise.race([child.exited.then(() => true), Bun.sleep(15_000).then(() => false)]);
    if (!exited) { child.kill('SIGKILL'); await child.exited; }
  }

  async close() { await this.stop(); }
}

async function freePort() {
  const server = Bun.listen({ hostname: '127.0.0.1', port: 0, socket: { data() {} } });
  const port = server.port;
  server.stop(true);
  return port;
}
