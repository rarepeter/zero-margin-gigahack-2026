import { afterEach, describe, expect, test } from 'bun:test';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createApp } from '../server/app';
import type { Judge } from '../server/judge';
import { normalizeWords, scoreAsr, wordErrorRate, type AsrBenchmark, type AsrJudgement } from '../shared/asr-benchmark';
import type { Recording } from '../shared/schema';

describe('reference normalization for WER', () => {
  test('drops speaker labels, uncertainty marks, clarifications, punctuation, and case', () => {
    expect(normalizeWords('A: Pacientul patu\' (patul) opt. B: Nor (?) zero zero unu (0.01)!')).toEqual(['pacientul', 'patu', 'opt', 'nor', 'zero', 'zero', 'unu']);
    expect(normalizeWords('Şi ţesut')).toEqual(normalizeWords('și țesut'));
  });
  test('counts word substitutions, deletions, and insertions against the reference length', () => {
    expect(wordErrorRate('unu doi trei patru', 'Unu, doi trei patru.')).toBe(0);
    expect(wordErrorRate('unu doi trei patru', 'unu doi cinci')).toBe(50);
    expect(wordErrorRate('', 'ceva')).toBeNull();
  });
});

const perfect: AsrJudgement = { errors: [], criteria: { completeness: 100, accuracy: 100, terminology: 100, language: 100, hallucination: 100 }, summary: 'Flawless.' };
test('the score is the weighted mean of the content criteria', () => {
  expect(scoreAsr(perfect)).toBe(100);
  expect(scoreAsr({ ...perfect, criteria: { completeness: 50, accuracy: 100, terminology: 100, language: 100, hallucination: 100 } })).toBe(85);
});

const roots: string[] = [];
const apps: ReturnType<typeof createApp>[] = [];
afterEach(async () => {
  for (const app of apps.splice(0)) await app.close();
  for (const root of roots.splice(0)) await rm(root, { recursive: true, force: true });
});

async function fixture(judge: Judge, transcribe: (model: string) => Response) {
  const root = await mkdtemp(join(tmpdir(), 'asr-bench-test-'));
  roots.push(root);
  const fetcher: typeof fetch = Object.assign(async (input: string | URL | Request, init?: RequestInit) => {
    const body = await new Request(input, init).json() as { model: string };
    return transcribe(body.model);
  }, { preconnect: fetch.preconnect });
  const app = createApp({ root, apiKey: () => 'test-secret', fetcher, loadCatalog: false, judge });
  apps.push(app);
  return { app, root };
}
const post = (path: string, body?: unknown) => new Request(`http://127.0.0.1:3001${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
async function upload(app: ReturnType<typeof createApp>, root: string, seconds: number) {
  const path = join(root, 'speech.m4a');
  const ffmpeg = Bun.spawn(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', `sine=frequency=440:duration=${seconds}`, '-c:a', 'aac', path], { stdout: 'pipe', stderr: 'pipe' });
  expect(await ffmpeg.exited).toBe(0);
  const form = new FormData();
  form.set('audio', new File([await Bun.file(path).arrayBuffer()], 'speech.m4a', { type: 'audio/mp4' }));
  const response = await app.fetch(new Request('http://127.0.0.1:3001/api/recordings', { method: 'POST', body: form }));
  expect(response.status).toBe(201);
  return (await response.json() as Recording).id;
}
async function settled(app: ReturnType<typeof createApp>, id: string) {
  for (let i = 0; i < 300; i++) {
    const benchmark = app.asr.benchmark(id)!;
    if (!benchmark.cells.some(c => c.status === 'transcribing' || c.status === 'judging')) return benchmark;
    await Bun.sleep(10);
  }
  throw new Error('Benchmark did not finish.');
}
const reference = { name: 'manual.md', text: 'A: Pacientul din patul opt are infarct. B: Da, trivascular.' };

describe('ASR accuracy benchmark', () => {
  test('every model × chunk size is transcribed and graded blind against the reference', async () => {
    const graded: string[] = [];
    const judge: Judge = {
      status: () => ({ available: true, error: null }),
      write: async () => { throw new Error('unused'); },
      grade: async (_system, user) => { graded.push(user); return { value: perfect, latencyMs: 3, cost: null, raw: {} }; },
    };
    const { app, root } = await fixture(judge, () => Response.json({ text: 'pacientul din patul opt are infarct da trivascular' }));
    const audioId = await upload(app, root, 25);
    const response = await app.fetch(post('/api/asr-benchmarks', { audioId, models: ['openai/whisper-large-v3', 'qwen/qwen3-asr-1.7b'], chunkSeconds: [45, 10], reference }));
    expect(response.status).toBe(201);
    const created = await response.json() as AsrBenchmark;
    expect(created.chunkSeconds).toEqual([10, 45]);
    const done = await settled(app, created.id);
    expect(done.cells).toHaveLength(4);
    for (const cell of done.cells) {
      expect(cell.status).toBe('completed');
      expect(cell.score).toBe(100);
      // The mock returns the whole sentence for every chunk, so smaller chunks repeat it.
      expect(cell.wer).toBe(cell.chunkSeconds === 45 ? 0 : 200);
    }
    // Ten-second chunks split the 25-second recording, so that run has more requests.
    const chunks = (size: number) => done.cells.find(c => c.chunkSeconds === size)!.transcription.totalChunks;
    expect(chunks(10)).toBeGreaterThan(chunks(45));
    expect(graded).toHaveLength(4);
    for (const input of graded) {
      expect(input).toContain('Pacientul din patul opt');
      expect(input).not.toMatch(/whisper|qwen/i);
    }
  });

  test('retry grades finished transcripts again without transcribing them again', async () => {
    let fail = true;
    let transcriptions = 0;
    const judge: Judge = {
      status: () => ({ available: true, error: null }),
      write: async () => { throw new Error('unused'); },
      grade: async () => { if (fail) throw new Error('Claude CLI failed: overloaded'); return { value: perfect, latencyMs: 1, cost: null, raw: {} }; },
    };
    const { app, root } = await fixture(judge, () => { transcriptions++; return Response.json({ text: 'pacientul' }); });
    const audioId = await upload(app, root, 5);
    const created = await (await app.fetch(post('/api/asr-benchmarks', { audioId, models: ['openai/whisper-large-v3'], chunkSeconds: [45], reference }))).json() as AsrBenchmark;
    const failed = await settled(app, created.id);
    expect(failed.cells[0].status).toBe('failed');
    expect(failed.cells[0].error).toContain('overloaded');
    fail = false;
    expect((await app.fetch(post(`/api/asr-benchmarks/${created.id}/retry`))).status).toBe(200);
    const retried = await settled(app, created.id);
    expect(retried.cells[0].status).toBe('completed');
    expect(transcriptions).toBe(1);
  });

  test('a failed transcription is marked failed and rerun on retry', async () => {
    let ok = false;
    const judge: Judge = {
      status: () => ({ available: true, error: null }),
      write: async () => { throw new Error('unused'); },
      grade: async () => ({ value: perfect, latencyMs: 1, cost: null, raw: {} }),
    };
    const { app, root } = await fixture(judge, () => ok ? Response.json({ text: 'pacientul' }) : Response.json({ error: { message: 'Provider returned error' } }, { status: 429 }));
    const audioId = await upload(app, root, 5);
    const created = await (await app.fetch(post('/api/asr-benchmarks', { audioId, models: ['openai/whisper-large-v3'], chunkSeconds: [45], reference }))).json() as AsrBenchmark;
    const failed = await settled(app, created.id);
    expect(failed.cells[0].error).toContain('429');
    ok = true;
    await app.fetch(post(`/api/asr-benchmarks/${created.id}/retry`));
    const retried = await settled(app, created.id);
    expect(retried.cells[0].status).toBe('completed');
    expect(retried.cells[0].runId).not.toBe(failed.cells[0].runId);
  });
});
