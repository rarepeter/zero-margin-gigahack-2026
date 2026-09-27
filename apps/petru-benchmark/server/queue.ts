import { readFile } from 'node:fs/promises';
import { buildRequest, redact, transcribe, UpstreamError } from './openrouter';
import type { Store } from './store';
import { MODELS } from '../shared/models';
import { buildLocalRequest, type LocalTranscriber } from './local-whisper';
import type { ModelResult, Run } from '../shared/schema';

export class Queue {
  private jobs: { run: Run; result: ModelResult }[] = [];
  private active = { openrouter: 0, local: 0 };
  private stopped = false;
  private abort = new AbortController();
  private pending = new Set<Promise<void>>();
  private listeners: ((resultId: string) => void)[] = [];
  constructor(private store: Store, private apiKey: () => string, private fetcher: typeof fetch = fetch, private local?: LocalTranscriber) {}
  // Called once per model result when it completes or fails. Not called on shutdown.
  onSettled(listener: (resultId: string) => void) { this.listeners.push(listener); }
  enqueue(run: Run) {
    this.jobs.push(...run.results.map(result => ({ run, result })));
    this.drain();
  }
  private drain() {
    while (!this.stopped) {
      // A busy hosted queue must never hold up a local job, or vice versa.
      const index = this.jobs.findIndex(job => {
        const provider = MODELS.find(model => model.id === job.result.modelId)?.provider ?? 'openrouter';
        return this.active[provider] < (provider === 'local' ? 1 : 2);
      });
      if (index < 0) return;
      const [job] = this.jobs.splice(index, 1);
      const provider = MODELS.find(model => model.id === job.result.modelId)?.provider ?? 'openrouter';
      this.active[provider]++;
      const promise = this.execute(job.run, job.result).finally(() => {
        this.active[provider]--;
        this.pending.delete(promise);
        if (!this.stopped) for (const listener of this.listeners) listener(job.result.id);
        this.drain();
      });
      this.pending.add(promise);
    }
  }
  private async execute(run: Run, result: ModelResult) {
    this.store.status(result.id, 'running');
    try {
      const chunks = this.store.runChunks(run.id);
      for (const chunk of chunks) {
        if (this.stopped) return;
        const started = performance.now();
        const model = MODELS.find(model => model.id === result.modelId);
        if (!model) throw new Error(`Unknown model: ${result.modelId}`);
        const request = { ...(model.provider === 'local' ? buildLocalRequest(run.options) : buildRequest(model.id, run.options)), input_audio: { format: 'wav', data: '[stored locally; omitted from log]' }, audioChunk: { index: chunk.index, start: chunk.start, end: chunk.end, targetSeconds: run.options.chunkSeconds } };
        try {
          if (model.provider === 'local' && !this.local) throw new Error('Local Whisper is not configured.');
          const output = model.provider === 'local'
            ? await this.local!.transcribe(chunk.path, run.options, this.abort.signal)
            : await transcribe(model.id, run.options, await readFile(chunk.path), this.apiKey(), this.fetcher, this.abort.signal);
          this.store.saveChunk(result.id, { ...output, index: chunk.index, start: chunk.start, end: chunk.end, request, status: 'completed', error: null });
        } catch (error) {
          if (this.stopped) return;
          const message = String(redact(error instanceof Error ? error.message : 'Transcription failed.', this.apiKey()));
          this.store.saveChunk(result.id, {
            index: chunk.index, start: chunk.start, end: chunk.end, request, status: 'failed', text: '', error: message,
            response: error instanceof UpstreamError ? error.body : null,
            generationId: error instanceof UpstreamError ? error.generationId : null,
            latencyMs: error instanceof UpstreamError ? error.latencyMs : Math.round(performance.now() - started),
            cost: null,
          });
          this.store.status(result.id, 'failed', `Chunk ${chunk.index + 1}/${chunks.length}: ${message}. No automatic retry was made. Earlier chunks remain saved.`);
          return;
        }
      }
      this.store.status(result.id, 'completed');
    } catch (error) {
      if (!this.stopped) this.store.status(result.id, 'failed', String(redact(error instanceof Error ? error.message : 'Run failed.', this.apiKey())));
    }
  }
  async close() {
    this.stopped = true;
    this.abort.abort();
    await this.local?.close();
    await Promise.allSettled(this.pending);
    this.store.recover();
  }
}
