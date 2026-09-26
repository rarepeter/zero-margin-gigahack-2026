import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { existsSync } from 'node:fs';
import { homedir } from 'node:os';
import { join, resolve } from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import { z } from 'zod';
import { LOCAL_WHISPER_MODEL } from '../shared/models';
import type { LocalModelStatus, RunOptions, TranscriptionOutput } from '../shared/schema';
import { buildWhisperPrompt } from '../shared/prompt';

export interface LocalTranscriber {
  status(): LocalModelStatus;
  transcribe(audioPath: string, options: RunOptions, signal?: AbortSignal): Promise<TranscriptionOutput>;
  close(): Promise<void>;
}

export const localUnavailable: LocalModelStatus = {
  available: false, state: 'unavailable', device: null,
  error: 'Set LOCAL_WHISPER_MODEL_PATH and install local/requirements.txt to enable local Whisper.',
};

export function buildLocalRequest(options: RunOptions) {
  return {
    model: LOCAL_WHISPER_MODEL.id, provider: 'local', engine: 'transformers', task: 'transcribe',
    language: options.language, temperature: options.temperature,
    timestamps: options.timestamps, contextPrompt: options.contextPrompt, vocabulary: options.vocabulary,
    prompt: buildWhisperPrompt(options),
  };
}

const workerMessage = z.discriminatedUnion('type', [
  z.object({ type: z.literal('ready'), device: z.string() }),
  z.object({ type: z.literal('result'), id: z.string(), response: z.object({ text: z.string() }).passthrough() }),
  z.object({ type: z.literal('error'), id: z.string(), message: z.string() }),
]);

type Pending = {
  id: string;
  finish: (error: Error | null, response?: z.infer<typeof workerMessage> & { type: 'result' }) => void;
};

// The queue supplies one local job at a time. The process stays warm between chunks.
export class LocalWhisper implements LocalTranscriber {
  private child?: ChildProcessWithoutNullStreams;
  private processes = new Map<ChildProcessWithoutNullStreams, Promise<void>>();
  private pending?: Pending;
  private state: LocalModelStatus['state'] = 'idle';
  private error: string | null = null;
  private device: string | null = null;
  private closed = false;
  private readonly modelPath: string;
  private readonly python: string;
  private readonly workerPath: string;

  constructor(private readonly options: {
    modelPath: string; python?: string; device?: string; timeoutMs?: number; workerPath?: string;
  }) {
    this.modelPath = options.modelPath.startsWith('~/') ? join(homedir(), options.modelPath.slice(2)) : resolve(options.modelPath || '.');
    this.python = options.python || fileURLToPath(new URL('../.venv/bin/python', import.meta.url));
    this.workerPath = options.workerPath || fileURLToPath(new URL('../local/whisper_worker.py', import.meta.url));
  }

  status(): LocalModelStatus {
    if (!this.options.modelPath.trim()) return { ...localUnavailable };
    if (!Bun.which(this.python)) return { ...localUnavailable, error: 'Local Python is missing. Install local/requirements.txt in .venv, or set LOCAL_WHISPER_PYTHON.' };
    for (const file of ['model.safetensors', 'config.json', 'generation_config.json', 'tokenizer.json', 'tokenizer_config.json', 'preprocessor_config.json']) {
      if (!existsSync(join(this.modelPath, file))) return { ...localUnavailable, error: `Local model is missing ${file}. Check LOCAL_WHISPER_MODEL_PATH.` };
    }
    return { available: true, state: this.state, device: this.device, error: this.error };
  }

  private start() {
    this.state = 'loading'; this.error = null;
    const child = spawn(this.python, ['-u', this.workerPath, '--model-path', this.modelPath, '--device', this.options.device || 'auto'], {
      stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env, HF_HUB_OFFLINE: '1', HF_HUB_DISABLE_TELEMETRY: '1', TOKENIZERS_PARALLELISM: 'false' },
    });
    this.child = child;
    let stderr = '';
    child.stderr.on('data', (data: Buffer) => { stderr = (stderr + data.toString()).slice(-4000); });
    const lines = createInterface({ input: child.stdout });
    lines.on('line', line => {
      if (this.child !== child) return;
      try {
        const message = workerMessage.parse(JSON.parse(line));
        if (message.type === 'ready') {
          this.device = message.device; this.state = this.pending ? 'running' : 'ready';
        } else if (!this.pending || message.id !== this.pending.id) {
          this.fail(child, new Error('Local worker returned an unexpected request ID.'));
        } else if (message.type === 'error') {
          this.pending.finish(new Error(message.message));
        } else {
          this.pending.finish(null, message);
        }
      } catch { this.fail(child, new Error('Local worker returned invalid JSON or an invalid response.')); }
    });
    child.stdin.on('error', error => this.fail(child, error));
    child.on('error', error => this.fail(child, error));
    this.processes.set(child, new Promise(resolveExit => {
      child.once('close', code => {
        lines.close(); this.processes.delete(child);
        if (this.child === child) this.fail(child, new Error(`Local Whisper stopped (exit ${code}). ${stderr.trim() || 'Check local/requirements.txt and the model path.'}`));
        resolveExit();
      });
    }));
    return child;
  }

  private fail(child: ChildProcessWithoutNullStreams, error: Error) {
    if (this.child !== child) return;
    this.child = undefined;
    this.state = 'error'; this.error = error.message;
    this.pending?.finish(error);
    child.kill('SIGKILL');
  }

  async transcribe(audioPath: string, options: RunOptions, signal?: AbortSignal): Promise<TranscriptionOutput> {
    if (this.closed) throw new Error('Local Whisper has been closed.');
    signal?.throwIfAborted();
    const status = this.status();
    if (!status.available) throw new Error(status.error || 'Local Whisper is unavailable.');
    if (this.pending) throw new Error('Local Whisper is already processing a chunk.');
    const started = performance.now();
    const child = this.child || this.start();
    if (this.state !== 'loading') this.state = 'running';
    this.error = null;
    return new Promise((resolveOutput, reject) => {
      const id = crypto.randomUUID();
      const abort = () => this.fail(child, new Error('Local transcription was interrupted.'));
      const timer = setTimeout(() => this.fail(child, new Error('Local transcription exceeded its 30-minute time limit.')), this.options.timeoutMs ?? 30 * 60_000);
      this.pending = { id, finish: (error, message) => {
        clearTimeout(timer); signal?.removeEventListener('abort', abort); this.pending = undefined;
        if (error) { this.state = 'error'; this.error = error.message; reject(error); }
        else if (message) {
          this.state = 'ready'; this.error = null;
          resolveOutput({ text: message.response.text, response: message.response, latencyMs: Math.round(performance.now() - started), cost: null, generationId: null });
        }
      } };
      signal?.addEventListener('abort', abort, { once: true });
      // Cloud provider options never enter the local worker.
      child.stdin.write(`${JSON.stringify({ id, audioPath: resolve(audioPath), options: {
        language: options.language, temperature: options.temperature, timestamps: options.timestamps, prompt: buildWhisperPrompt(options),
      } })}\n`);
    });
  }

  async close() {
    this.closed = true;
    if (this.child) this.fail(this.child, new Error('Local Whisper stopped with the server.'));
    await Promise.all(this.processes.values());
  }
}
