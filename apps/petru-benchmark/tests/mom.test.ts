import { afterEach, describe, expect, test } from 'bun:test';
import { mkdtemp, mkdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createApp } from '../server/app';
import type { Judge } from '../server/judge';
import type { LocalMom } from '../server/llama';
import { scoreJudgement, REFERENCE_ID, type Judgement, type MomRun, type MomTranscript } from '../shared/mom';
import { MOM_SYSTEM_PROMPT } from '../shared/mom-prompt';

const key: MomTranscript['answerKey'] = {
  items: [
    { id: 'D1', kind: 'decision', text: 'Patient goes to CABG, not PCI.', critical: true },
    { id: 'A1', kind: 'action', text: 'Stop metformin 48 hours before contrast.', owner: 'Dr. Rusu', deadline: null, critical: false },
    { id: 'F1', kind: 'finding', text: 'eGFR is 38 mL/min/1.73m².', critical: false },
  ],
  traps: [{ id: 'T1', text: 'Lists PCI as the decision.' }],
};
const perfect: Judgement = {
  items: [
    { id: 'D1', verdict: 'correct', owner: 'na', deadline: 'na', note: '' },
    { id: 'A1', verdict: 'correct', owner: 'correct', deadline: 'correct', note: '' },
    { id: 'F1', verdict: 'correct', owner: 'na', deadline: 'na', note: '' },
  ],
  traps: [{ id: 'T1', verdict: 'avoided', note: '' }],
  hallucinations: [],
  quality: { structure: 5, concision: 5, language: 5, terminology: 5, uncertainty: 5 },
  summary: '',
};

describe('MoM scoring', () => {
  test('a flawless grade scores 100', () => {
    expect(scoreJudgement(key, perfect).total).toBe(100);
  });
  test('distortions, invented owners, traps, and hallucinations cost more than omissions', () => {
    const missing = scoreJudgement(key, { ...perfect, items: perfect.items.map(i => i.id === 'D1' ? { ...i, verdict: 'missing' } : i) });
    const wrong = scoreJudgement(key, { ...perfect, items: perfect.items.map(i => i.id === 'D1' ? { ...i, verdict: 'wrong' } : i) });
    expect(wrong.total).toBeLessThan(missing.total);
    const invented = scoreJudgement(key, { ...perfect, items: perfect.items.map(i => i.id === 'A1' ? { ...i, deadline: 'invented' } : i) });
    expect(invented.attribution).toBe(0);
    expect(scoreJudgement(key, { ...perfect, traps: [{ id: 'T1', verdict: 'fell', note: '' }] }).total).toBe(80);
    expect(scoreJudgement(key, { ...perfect, hallucinations: [{ claim: 'x', severity: 'major', note: '' }] }).total).toBe(94);
  });
  test('items the judge skipped count as missing', () => {
    expect(scoreJudgement(key, { ...perfect, items: [], traps: [] }).coverage).toBe(0);
  });
});

const roots: string[] = [];
const apps: ReturnType<typeof createApp>[] = [];
afterEach(async () => {
  for (const app of apps.splice(0)) await app.close();
  for (const root of roots.splice(0)) await rm(root, { recursive: true, force: true });
});

async function fixture(judge: Judge, upstream: (body: { model: string; messages: { role: string; content: string }[] }) => Response, localMom?: LocalMom, apiKey = 'test-secret') {
  const root = await mkdtemp(join(tmpdir(), 'mom-test-'));
  roots.push(root);
  const dataDir = join(root, 'transcripts');
  await mkdir(dataDir);
  const transcript: MomTranscript = {
    id: 'clinical-01', meetingType: 'clinical', title: 'Case conference', scenario: 'A fictional cardiology case conference.',
    transcript: 'deci, colegi, pacientul are șaizeci și șapte de ani. '.repeat(60), answerKey: key,
  };
  await Bun.write(join(dataDir, 'clinical-01.json'), JSON.stringify(transcript));
  const fetcher: typeof fetch = Object.assign(async (input: string | URL | Request, init?: RequestInit) => upstream(await new Request(input, init).json()), { preconnect: fetch.preconnect });
  const app = createApp({ root, apiKey: () => apiKey, fetcher, loadCatalog: false, judge, localMom, momDataDir: dataDir });
  apps.push(app);
  return app;
}
const post = (path: string, body?: unknown) => new Request(`http://127.0.0.1:3001${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
async function settled(app: ReturnType<typeof createApp>, id: string) {
  for (let i = 0; i < 200; i++) {
    const run = app.mom.run(id)!;
    if (!run.cells.some(c => ['queued', 'generating', 'judging'].includes(c.status))) return run;
    await new Promise(resolve => setTimeout(resolve, 10));
  }
  throw new Error('Run did not finish.');
}
const completion = (content: string) => Response.json({ provider: 'TestHost', choices: [{ finish_reason: 'stop', message: { content } }], usage: { prompt_tokens: 900, completion_tokens: 300, cost: 0.001, completion_tokens_details: { reasoning_tokens: 120 } } });

describe('MoM benchmark runs', () => {
  test('models get the shared prompt without the reference, and the judge grades each candidate blind', async () => {
    const gradeInputs: string[] = [];
    const judge: Judge = {
      status: () => ({ available: true, error: null }),
      write: async (system) => ({ value: `# Minuta ședinței: referință\n${system === MOM_SYSTEM_PROMPT}`, latencyMs: 5, cost: null, raw: {} }),
      grade: async (_system, user) => { gradeInputs.push(user); return { value: perfect, latencyMs: 5, cost: 0.2, raw: {} }; },
    };
    const requests: { model: string; messages: { role: string; content: string }[] }[] = [];
    const app = await fixture(judge, body => { requests.push(body); return completion(`<think>plan</think>\n# Minuta ${body.model.length}`); });
    const response = await app.fetch(post('/api/mom/runs', { models: ['qwen/qwen3.8-27b', 'openai/gpt-oss-20b'], transcripts: ['clinical-01'] }));
    expect(response.status).toBe(201);
    const run = await settled(app, (await response.json() as MomRun).id);
    expect(run.cells.map(c => c.status)).toEqual(['completed', 'completed', 'completed']);
    expect(run.cells.find(c => c.modelId === REFERENCE_ID)!.output).toContain('true');
    const qwen = run.cells.find(c => c.modelId === 'qwen/qwen3.8-27b')!;
    expect(qwen.output).toBe(`# Minuta ${qwen.modelId.length}`);
    expect(qwen.score?.total).toBe(100);
    expect(qwen.usage).toEqual({ promptTokens: 900, completionTokens: 300, reasoningTokens: 120 });
    for (const body of requests) {
      expect(body.messages[0]).toEqual({ role: 'system', content: MOM_SYSTEM_PROMPT });
      expect(JSON.stringify(body)).not.toContain('referință');
    }
    expect(gradeInputs).toHaveLength(2);
    for (const input of gradeInputs) {
      expect(input).toContain('# Minuta ședinței: referință');
      expect(input).not.toMatch(/qwen|gpt-oss/i);
    }
  });

  test('a retry repeats only the failed step', async () => {
    let failGrade = true;
    let generations = 0;
    const judge: Judge = {
      status: () => ({ available: true, error: null }),
      write: async () => ({ value: '# Referință', latencyMs: 1, cost: null, raw: {} }),
      grade: async () => { if (failGrade) throw new Error('Claude CLI failed: overloaded'); return { value: perfect, latencyMs: 1, cost: null, raw: {} }; },
    };
    const app = await fixture(judge, () => { generations++; return completion('# Minuta'); });
    const created = await (await app.fetch(post('/api/mom/runs', { models: ['openai/gpt-oss-20b'], transcripts: ['clinical-01'] }))).json() as MomRun;
    const failed = await settled(app, created.id);
    const cell = failed.cells.find(c => c.modelId !== REFERENCE_ID)!;
    expect(cell.status).toBe('failed');
    expect(cell.error).toContain('overloaded');
    failGrade = false;
    expect((await app.fetch(post(`/api/mom/runs/${created.id}/retry`))).status).toBe(200);
    const retried = await settled(app, created.id);
    expect(retried.cells.every(c => c.status === 'completed')).toBe(true);
    expect(generations).toBe(1);
  });

  test('a model that returns no minutes scores 0 without a judge call', async () => {
    let grades = 0;
    const judge: Judge = {
      status: () => ({ available: true, error: null }),
      write: async () => ({ value: '# Referință', latencyMs: 1, cost: null, raw: {} }),
      grade: async () => { grades++; return { value: perfect, latencyMs: 1, cost: null, raw: {} }; },
    };
    const app = await fixture(judge, () => Response.json({ choices: [{ finish_reason: 'length', message: { content: '<think>endless</think>' } }] }));
    const created = await (await app.fetch(post('/api/mom/runs', { models: ['openai/gpt-oss-20b'], transcripts: ['clinical-01'] }))).json() as MomRun;
    const cell = (await settled(app, created.id)).cells.find(c => c.modelId !== REFERENCE_ID)!;
    expect(cell.status).toBe('completed');
    expect(cell.score?.total).toBe(0);
    expect(cell.error).toContain('finish reason: length');
    expect(grades).toBe(0);
  });

  test('local models run without an OpenRouter key and record on-device speed', async () => {
    const judge: Judge = {
      status: () => ({ available: true, error: null }),
      write: async () => ({ value: '# Referință', latencyMs: 1, cost: null, raw: {} }),
      grade: async () => ({ value: perfect, latencyMs: 1, cost: null, raw: {} }),
    };
    const local: LocalMom = {
      status: () => ({ available: true, path: '/models/q4.gguf', error: null }),
      generate: async () => ({
        text: '# Minuta locală', latencyMs: 60_000, finishReason: 'stop', response: {},
        usage: { promptTokens: 3000, completionTokens: 2500, reasoningTokens: 1500 },
        local: { loadMs: 9000, promptTokensPerSecond: 420, generationTokensPerSecond: 14.5 },
      }),
      close: async () => {},
    };
    const app = await fixture(judge, () => { throw new Error('No hosted call expected.'); }, local, '');
    const response = await app.fetch(post('/api/mom/runs', { models: ['local/muse-glimmer-30b-q4_k_m'], transcripts: ['clinical-01'] }));
    expect(response.status).toBe(201);
    const cell = (await settled(app, (await response.json() as MomRun).id)).cells.find(c => c.modelId !== REFERENCE_ID)!;
    expect(cell.score?.total).toBe(100);
    expect(cell.cost).toBeNull();
    expect(cell.local?.generationTokensPerSecond).toBe(14.5);
  });
});
