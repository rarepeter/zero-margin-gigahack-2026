import { afterEach, describe, expect, test } from 'bun:test';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createApp } from '../server/app';
import { chunkBoundaries } from '../server/audio';
import { buildRequest, redact } from '../server/openrouter';
import { runOptionsSchema, type Recording, type Run } from '../shared/schema';
import { MODELS } from '../shared/models';

const roots: string[] = [];
const apps: ReturnType<typeof createApp>[] = [];
afterEach(async () => {
  for (const app of apps.splice(0)) await app.close();
  for (const root of roots.splice(0)) await rm(root, { recursive: true, force: true });
});

async function fixture(handler?: (request: Request) => Response | Promise<Response>, key = 'test-secret') {
  const root = await mkdtemp(join(tmpdir(), 'speechbench-test-'));
  roots.push(root);
  // Dependency injection keeps all paid requests off the network.
  const fetcher: typeof fetch = Object.assign(async (input: string | URL | Request, init?: RequestInit) => {
    if (!handler) throw new Error('Unexpected upstream request');
    return handler(new Request(input, init));
  }, { preconnect: fetch.preconnect });
  const app = createApp({ root, apiKey: () => key, fetcher, loadCatalog: false });
  apps.push(app);
  return { app, root };
}
function request(path: string, init?: RequestInit) { return new Request(`http://127.0.0.1:3001${path}`, init); }
async function waitForRun(app: ReturnType<typeof createApp>, id: string) {
  for (let i = 0; i < 150; i++) {
    const run = app.store.run(id)!;
    if (!run.results.some(r => ['queued', 'running'].includes(r.status))) return run;
    await new Promise(resolve => setTimeout(resolve, 20));
  }
  throw new Error('Run did not finish.');
}
async function seed(app: ReturnType<typeof createApp>, root: string, count = 1) {
  const id = crypto.randomUUID();
  const path = join(root, 'audio.wav');
  const wav = Buffer.alloc(44); wav.write('RIFF', 0); wav.write('WAVE', 8);
  await Bun.write(path, wav);
  const recording: Recording = { id, name: 'mixed.m4a', bytes: 44, duration: count * 10, createdAt: new Date().toISOString(), chunkCount: count, sha256: 'test' };
  app.store.addRecording(recording, Array.from({ length: count }, (_, i) => ({ index: i, start: i * 10, end: (i + 1) * 10, path })), path);
  return id;
}

describe('multilingual request contract', () => {
  test('automatic language and original transcript mode across the open-weight allowlist', () => {
    for (const model of MODELS) {
      const body = buildRequest(model.id, runOptionsSchema.parse({}));
      expect(body).not.toHaveProperty('language');
      expect(body.temperature).toBe(0);
      expect(body.response_format).toBe('json');
      expect(body).not.toHaveProperty('prompt');
      expect(body).not.toHaveProperty('task');
    }
  });
  test('vocabulary uses documented passthrough and does not erase custom settings', () => {
    const body = buildRequest('openai/whisper-large-v3', runOptionsSchema.parse({ vocabulary: 'Chișinău, щас, deadline', timestamps: true, providerOptions: { groq: { custom: 1 } } }));
    expect(body.provider?.options.groq).toEqual({ prompt: 'Română, русский, English. Chișinău, щас, deadline', custom: 1 });
    expect(body.timestamp_granularities).toEqual(['segment', 'word']);
    expect(buildRequest('qwen/qwen3-asr-1.7b', runOptionsSchema.parse({ vocabulary: 'test' }))).not.toHaveProperty('provider');
  });
  test('chunking prefers pauses and covers all audio without gaps or overlap', () => {
    expect(chunkBoundaries(120, [43, 94])).toEqual([0, 43, 94, 120]);
    expect(chunkBoundaries(68, [18, 39], 20)).toEqual([0, 18, 39, 59, 68]);
    expect(chunkBoundaries(68, [48], 50)).toEqual([0, 48, 68]);
    expect(chunkBoundaries(55, [])).toEqual([0, 55]);
    const boundaries = chunkBoundaries(361, []);
    expect(boundaries[0]).toBe(0); expect(boundaries.at(-1)).toBe(361);
    expect(boundaries.slice(1).every((end, i) => end > boundaries[i] && end - boundaries[i] <= 55)).toBe(true);
  });
});

test('custom chunk sizes change the audio sent to every model and persist independently', async () => {
  const seen: { model: string; bytes: number }[] = [];
  const transcript = 'Mâine. Завтра. Tomorrow.';
  const { app, root } = await fixture(async req => {
    const body = await req.json() as { model: string; input_audio: { data: string } };
    expect(body).not.toHaveProperty('chunkSeconds');
    seen.push({ model: body.model, bytes: Buffer.from(body.input_audio.data, 'base64').length });
    return Response.json({ text: transcript });
  });
  const audioPath = join(root, 'long.m4a');
  const conversion = Bun.spawn(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=68', '-c:a', 'aac', audioPath], { stdout: 'pipe', stderr: 'pipe' });
  expect(await conversion.exited).toBe(0);
  const form = new FormData(); form.set('audio', new File([await Bun.file(audioPath).arrayBuffer()], 'long.m4a'));
  const uploaded = await app.fetch(request('/api/recordings', { method: 'POST', body: form }));
  expect(uploaded.status).toBe(201);
  const recording = await uploaded.json() as Recording;
  const originalChunks = app.store.recording(recording.id)!.chunks;
  const models = ['openai/whisper-large-v3', 'qwen/qwen3-asr-1.7b'];
  const runs: Run[] = [];
  for (const chunkSeconds of [20, 50]) {
    const created = await app.fetch(request('/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ audioId: recording.id, models, options: { chunkSeconds } }) }));
    expect(created.status).toBe(201);
    const run = await waitForRun(app, (await created.json() as Run).id);
    runs.push(run);
    const count = chunkSeconds === 20 ? 4 : 2;
    expect(run.options.chunkSeconds).toBe(chunkSeconds);
    expect(run.chunkCount).toBe(count);
    const audio = app.store.runChunks(run.id);
    expect([audio[0].start, ...audio.map(c => c.end)]).toEqual(chunkBoundaries(recording.duration, [], chunkSeconds));
    const probe = Bun.spawn(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', audio[0].path], { stdout: 'pipe', stderr: 'pipe' });
    const probed = await new Response(probe.stdout).json() as { format: { duration: string } };
    expect(await probe.exited).toBe(0);
    expect(Number(probed.format.duration)).toBeCloseTo(chunkSeconds, 2);
    for (const result of run.results) {
      expect(result.status).toBe('completed');
      expect(result.totalChunks).toBe(count);
      expect(result.transcript).toBe(Array(count).fill(transcript).join('\n\n'));
      expect(result.chunks[0].request).toHaveProperty('audioChunk.targetSeconds', chunkSeconds);
      expect(result.chunks.map(c => [c.start, c.end])).toEqual(audio.map(c => [c.start, c.end]));
    }
  }
  for (const model of models) {
    expect(seen.filter(c => c.model === model)).toHaveLength(6);
    expect(seen.filter(c => c.model === model)[4].bytes).toBeGreaterThan(seen.filter(c => c.model === model)[0].bytes * 2);
  }
  const [small, large] = runs;
  const savedSmallChunks = app.store.runChunks(small.id);
  expect(savedSmallChunks[0].path).not.toBe(app.store.runChunks(large.id)[0].path);
  expect(app.store.recording(recording.id)!.chunks).toEqual(originalChunks);
  expect(app.store.run(small.id)).toEqual(small);
  const exported = await app.fetch(request(`/api/runs/${small.id}/export`));
  expect(await exported.json()).toEqual(small);
  await app.close(); apps.splice(apps.indexOf(app), 1);
  const reopened = createApp({ root, apiKey: () => '', loadCatalog: false }); apps.push(reopened);
  expect(reopened.store.runChunks(small.id)).toEqual(savedSmallChunks);
  for (const run of runs) expect(reopened.store.run(run.id)).toEqual(run);
}, 20000);

test('invalid chunk sizes are rejected before audio preparation or provider calls', async () => {
  const { app, root } = await fixture();
  const audioId = await seed(app, root);
  for (const chunkSeconds of [0, -5, 9, 20.5, 601, '45', null]) {
    const response = await app.fetch(request('/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ audioId, models: ['openai/whisper-large-v3'], options: { chunkSeconds } }) }));
    expect(response.status).toBe(400);
  }
  expect(app.store.runs()).toHaveLength(0);
});

test('runs saved before configurable chunking retain their original audio and use the 45 second default', async () => {
  const { app, root } = await fixture();
  const audioId = await seed(app, root, 2);
  const run = app.store.createRun(audioId, ['openai/whisper-large-v3'], runOptionsSchema.parse({}));
  app.store.saveChunk(run.results[0].id, { index: 0, start: 0, end: 10, status: 'completed', text: 'Text salvat. Сохранено.', latencyMs: 50, cost: null, error: null, request: {}, response: {}, generationId: null });
  app.store.status(run.results[0].id, 'completed');
  const { chunkSeconds: _, ...legacyOptions } = run.options;
  app.store.db.run('UPDATE runs SET options = ? WHERE id = ?', [JSON.stringify(legacyOptions), run.id]);
  // Simulate the schema used before run-specific chunk plans existed.
  app.store.db.exec('DROP TABLE run_audio');
  await app.close(); apps.splice(apps.indexOf(app), 1);
  const reopened = createApp({ root, apiKey: () => '', loadCatalog: false }); apps.push(reopened);
  const saved = reopened.store.run(run.id)!;
  expect(saved.options.chunkSeconds).toBe(45);
  expect(saved.chunkCount).toBe(2);
  expect(saved.results[0].transcript).toBe('Text salvat. Сохранено.');
  expect(reopened.store.runChunks(run.id)).toEqual(reopened.store.recording(audioId)!.chunks);
});

test('real M4A upload → all models → full Unicode text persisted across restart', async () => {
  const transcript = 'Mâine mergem la Chișinău. Давайте проверим deadline-ul. Îi clar, da?';
  const seen: string[] = [];
  const { app, root } = await fixture(async req => {
    expect(req.url).toBe('https://openrouter.ai/api/v1/audio/transcriptions');
    expect(req.headers.get('authorization')).toBe('Bearer test-secret');
    const body = await req.json() as { model: string; input_audio: { data: string; format: string }; language?: string };
    expect(body.language).toBeUndefined();
    expect(body.input_audio.format).toBe('wav');
    expect(Buffer.from(body.input_audio.data, 'base64').subarray(0, 4).toString()).toBe('RIFF');
    seen.push(body.model);
    return Response.json({ text: transcript, usage: { cost: 0.001 }, segments: [{ start: 0, end: 1, text: transcript }], custom: { preserved: true } }, { headers: { 'x-generation-id': 'gen-test' } });
  });
  const audioPath = join(root, 'input.m4a');
  const process = Bun.spawn(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1', '-c:a', 'aac', audioPath], { stdout: 'pipe', stderr: 'pipe' });
  expect(await process.exited).toBe(0);
  const form = new FormData(); form.set('audio', new File([await Bun.file(audioPath).arrayBuffer()], 'sample.m4a', { type: 'audio/mp4' }));
  const upload = await app.fetch(request('/api/recordings', { method: 'POST', body: form }));
  expect(upload.status).toBe(201);
  const recording = await upload.json() as Recording;
  expect(recording.chunkCount).toBe(1);
  const created = await app.fetch(request('/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ audioId: recording.id, models: MODELS.map(m => m.id), options: {} }) }));
  expect(created.status).toBe(201);
  const run = await waitForRun(app, (await created.json() as Run).id);
  expect(seen.sort()).toEqual(MODELS.map(m => m.id).sort());
  for (const result of run.results) {
    expect(result.status).toBe('completed'); expect(result.transcript).toBe(transcript);
    expect(result.chunks[0].generationId).toBe('gen-test'); expect(result.cost).toBe(0.001);
    expect(result.chunks[0].response).toHaveProperty('custom.preserved', true);
  }
  expect(JSON.stringify(run)).not.toContain('test-secret');
  const exported = await app.fetch(request(`/api/runs/${run.id}/export`));
  expect(exported.headers.get('content-disposition')).toContain('attachment');
  await app.close(); apps.splice(apps.indexOf(app), 1);
  const reopened = createApp({ root, apiKey: () => '', loadCatalog: false }); apps.push(reopened);
  expect(reopened.store.run(run.id)?.results.map(r => r.transcript)).toEqual(MODELS.map(() => transcript));
  expect(reopened.store.recordings()[0].name).toBe('sample.m4a');
}, 20000);

test('a later chunk failure preserves text, raw error, and never silently retries', async () => {
  let calls = 0;
  const { app, root } = await fixture(() => {
    calls++;
    return calls === 1 ? Response.json({ text: 'Prima parte. Первая часть.' }) : Response.json({ error: { message: 'rate limit test-secret' } }, { status: 429 });
  });
  const id = await seed(app, root, 3);
  const response = await app.fetch(request('/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ audioId: id, models: ['openai/whisper-large-v3'], options: {} }) }));
  const run = await waitForRun(app, (await response.json() as Run).id);
  expect(calls).toBe(2);
  expect(run.results[0].status).toBe('failed');
  expect(run.results[0].transcript).toBe('Prima parte. Первая часть.');
  expect(run.results[0].completedChunks).toBe(1);
  expect(run.results[0].chunks[1].response).toEqual({ error: { message: 'rate limit [redacted]' } });
});

test('rejects closed models, missing keys, and cross-origin spending requests', async () => {
  const { app, root } = await fixture();
  const audioId = await seed(app, root);
  const body = JSON.stringify({ audioId, models: ['openai/gpt-4o-transcribe'], options: {} });
  expect((await app.fetch(request('/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body }))).status).toBe(400);
  expect((await app.fetch(request('/api/runs', { method: 'POST', headers: { Origin: 'https://example.com' }, body }))).status).toBe(403);
  const noKey = await fixture(undefined, '');
  expect((await noKey.app.fetch(request('/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body }))).status).toBe(503);
  expect(redact({ nested: { api_key: 'oops', message: 'secret-value' } }, 'secret-value')).toEqual({ nested: { api_key: '[redacted]', message: '[redacted]' } });
});

test('server recovery marks unfinished runs as interrupted and keeps completed chunks', async () => {
  const { app, root } = await fixture();
  const audioId = await seed(app, root, 2);
  const run = app.store.createRun(audioId, ['openai/whisper-large-v3'], runOptionsSchema.parse({}));
  app.store.status(run.results[0].id, 'running');
  app.store.saveChunk(run.results[0].id, { index: 0, start: 0, end: 10, status: 'completed', text: 'Păstrează asta.', latencyMs: 50, cost: null, error: null, request: {}, response: { text: 'Păstrează asta.' }, generationId: null });
  app.store.recover();
  const saved = app.store.run(run.id)!;
  expect(saved.results[0].status).toBe('interrupted');
  expect(saved.results[0].transcript).toBe('Păstrează asta.');
});
