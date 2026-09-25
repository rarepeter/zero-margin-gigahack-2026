import { readFile } from 'node:fs/promises';
import { buildRequest, redact, transcribe, TranscriptionError } from './openrouter';
import type { Store } from './store';
import type { ModelId } from '../shared/models';
import type { ModelResult, Run } from '../shared/schema';

export class Queue {
  private jobs: { run: Run; result: ModelResult }[] = [];
  private active = 0;
  private stopped = false;
  private abort = new AbortController();
  private pending = new Set<Promise<void>>();
  constructor(private store: Store, private apiKey: () => string, private fetcher: typeof fetch = fetch) {}
  enqueue(run: Run) {
    this.jobs.push(...run.results.map(result => ({ run, result })));
    this.drain();
  }
  private drain() {
    while (!this.stopped && this.active < 2 && this.jobs.length) {
      const job = this.jobs.shift()!;
      this.active++;
      const promise = this.execute(job.run, job.result).finally(() => {
        this.active--;
        this.pending.delete(promise);
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
        const modelId = result.modelId as ModelId;
        const request = { ...buildRequest(modelId, run.options), input_audio: { format: 'wav', data: '[stored locally; omitted from log]' }, audioChunk: { index: chunk.index, start: chunk.start, end: chunk.end, targetSeconds: run.options.chunkSeconds } };
        try {
          const output = await transcribe(modelId, run.options, await readFile(chunk.path), this.apiKey(), this.fetcher, this.abort.signal);
          this.store.saveChunk(result.id, { ...output, index: chunk.index, start: chunk.start, end: chunk.end, request, status: 'completed', error: null });
        } catch (error) {
          if (this.stopped) return;
          const message = String(redact(error instanceof Error ? error.message : 'Transcription failed.', this.apiKey()));
          this.store.saveChunk(result.id, {
            index: chunk.index, start: chunk.start, end: chunk.end, request, status: 'failed', text: '', error: message,
            response: error instanceof TranscriptionError ? error.body : null,
            generationId: error instanceof TranscriptionError ? error.generationId : null,
            latencyMs: error instanceof TranscriptionError ? error.latencyMs : Math.round(performance.now() - started),
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
    await Promise.allSettled(this.pending);
    this.store.recover();
  }
}
