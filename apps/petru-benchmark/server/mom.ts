import type { Database } from 'bun:sqlite';
import { createHash } from 'node:crypto';
import { HttpError, json } from './http';
import { Semaphore } from './semaphore';
import { generateMom, MOM_REASONING_EFFORT, buildMomRequest, redact, UpstreamError } from './openrouter';
import { loadTranscripts, summarize } from './mom-data';
import { JUDGE_EFFORT, type Judge } from './judge';
import type { LocalMom } from './llama';
import {
  createMomRunSchema, judgementJsonSchema, judgementSchema, scoreJudgement, isLocalMomModel, JUDGE_MODEL, LOCAL_MOM_MODELS, REFERENCE_ID,
  type LocalMomModelId, type MomCell, type MomCellStatus, type MomConfig, type MomModelId, type MomRun, type MomTranscript,
} from '../shared/mom';
import { JUDGE_SYSTEM_PROMPT, MOM_SYSTEM_PROMPT, buildJudgeUserMessage, buildMomUserMessage } from '../shared/mom-prompt';

// Everything needed to reproduce a run, frozen when it starts: transcripts, answer keys, and prompts.
type Snapshot = { transcripts: MomTranscript[]; momPrompt: string; judgePrompt: string };
type CellData = Omit<MomCell, 'id' | 'runId' | 'transcriptId' | 'modelId' | 'status'>;
type CellRow = { id: string; run_id: string; transcript_id: string; model_id: string; status: MomCellStatus; data: string };
type RunRow = { id: string; created_at: string; models: string; settings: string; snapshot: string };

const EMPTY_SCORE = { coverage: 0, attribution: 0, traps: 0, quality: 0, penalty: 0, total: 0 };
const emptyCell: CellData = {
  generated: false, output: '', latencyMs: null, cost: null, usage: null, provider: null, finishReason: null, local: null,
  judgement: null, score: null, judgeLatencyMs: null, judgeCost: null, error: null,
};

export class MomStore {
  constructor(private db: Database) {
    db.exec(`CREATE TABLE IF NOT EXISTS mom_runs (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, models TEXT NOT NULL, settings TEXT NOT NULL, snapshot TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS mom_cells (id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES mom_runs(id), transcript_id TEXT NOT NULL, model_id TEXT NOT NULL, status TEXT NOT NULL, data TEXT NOT NULL, raw TEXT NOT NULL DEFAULT '{}');
      CREATE INDEX IF NOT EXISTS mom_cells_run ON mom_cells(run_id);`);
  }
  recover() {
    this.db.run("UPDATE mom_cells SET status = 'interrupted' WHERE status IN ('queued', 'generating', 'judging')");
  }
  createRun(models: MomModelId[], transcripts: MomTranscript[]) {
    const id = crypto.randomUUID();
    const snapshot: Snapshot = { transcripts, momPrompt: MOM_SYSTEM_PROMPT, judgePrompt: JUDGE_SYSTEM_PROMPT };
    const settings: MomRun['settings'] = {
      judgeModel: JUDGE_MODEL, judgeEffort: JUDGE_EFFORT, reasoningEffort: MOM_REASONING_EFFORT,
      maxTokens: buildMomRequest(models[0], '').max_tokens,
      promptSha256: createHash('sha256').update(MOM_SYSTEM_PROMPT).digest('hex'),
    };
    this.db.transaction(() => {
      this.db.run('INSERT INTO mom_runs VALUES (?, ?, ?, ?, ?)', [id, new Date().toISOString(), JSON.stringify(models), JSON.stringify(settings), JSON.stringify(snapshot)]);
      for (const transcript of transcripts) {
        for (const modelId of [REFERENCE_ID, ...models]) {
          this.db.run('INSERT INTO mom_cells (id, run_id, transcript_id, model_id, status, data) VALUES (?, ?, ?, ?, ?, ?)', [crypto.randomUUID(), id, transcript.id, modelId, 'queued', JSON.stringify(emptyCell)]);
        }
      }
    })();
    return this.run(id)!;
  }
  snapshot(runId: string) {
    const row = this.db.query<{ snapshot: string }, [string]>('SELECT snapshot FROM mom_runs WHERE id = ?').get(runId);
    return row ? JSON.parse(row.snapshot) as Snapshot : null;
  }
  cells(runId: string): MomCell[] {
    return this.db.query<CellRow, [string]>('SELECT id, run_id, transcript_id, model_id, status, data FROM mom_cells WHERE run_id = ? ORDER BY rowid').all(runId).map(row => ({
      ...emptyCell, ...JSON.parse(row.data) as Partial<CellData>,
      id: row.id, runId: row.run_id, transcriptId: row.transcript_id, modelId: row.model_id, status: row.status,
    }));
  }
  run(id: string, light = false): MomRun | null {
    const row = this.db.query<RunRow, [string]>('SELECT * FROM mom_runs WHERE id = ?').get(id);
    if (!row) return null;
    const snapshot = JSON.parse(row.snapshot) as Snapshot;
    const cells = this.cells(id);
    return {
      id: row.id, createdAt: row.created_at, models: JSON.parse(row.models) as string[],
      settings: JSON.parse(row.settings) as MomRun['settings'], transcripts: snapshot.transcripts.map(summarize),
      // The run list only needs statuses and scores; full text is loaded per run.
      cells: light ? cells.map(cell => ({ ...cell, output: '', judgement: null })) : cells,
    };
  }
  runs() {
    return this.db.query<{ id: string }, []>('SELECT id FROM mom_runs ORDER BY rowid DESC').all().map(({ id }) => this.run(id, true)!);
  }
  update(id: string, status: MomCellStatus, patch: Partial<CellData> = {}) {
    this.db.transaction(() => {
      const row = this.db.query<{ data: string }, [string]>('SELECT data FROM mom_cells WHERE id = ?').get(id)!;
      this.db.run('UPDATE mom_cells SET status = ?, data = ? WHERE id = ?', [status, JSON.stringify({ ...JSON.parse(row.data), ...patch }), id]);
    })();
  }
  // Raw provider and judge responses are kept for export only.
  saveRaw(id: string, key: 'generation' | 'judge', value: unknown) {
    this.db.transaction(() => {
      const row = this.db.query<{ raw: string }, [string]>('SELECT raw FROM mom_cells WHERE id = ?').get(id)!;
      this.db.run('UPDATE mom_cells SET raw = ? WHERE id = ?', [JSON.stringify({ ...JSON.parse(row.raw), [key]: value }), id]);
    })();
  }
  raw(runId: string) {
    return Object.fromEntries(this.db.query<{ id: string; raw: string }, [string]>('SELECT id, raw FROM mom_cells WHERE run_id = ?').all(runId).map(row => [row.id, JSON.parse(row.raw)]));
  }
  // Marks failed and interrupted cells for another attempt. Completed minutes and grades are kept.
  resetFailed(runId: string) {
    return this.db.run("UPDATE mom_cells SET status = 'queued' WHERE run_id = ? AND status IN ('failed', 'interrupted')", [runId]).changes;
  }
}

// Per transcript: the judge writes reference minutes while every model writes its own; each candidate is graded once both exist.
export class MomRunner {
  private hosted = new Semaphore(4);
  private judging: Semaphore;
  private abort = new AbortController();
  private pending = new Set<Promise<void>>();
  private stopped = false;
  constructor(private store: MomStore, private judge: Judge, private apiKey: () => string, private fetcher: typeof fetch = fetch, judgeConcurrency = 3, private local?: LocalMom) {
    this.judging = new Semaphore(judgeConcurrency);
  }
  start(runId: string) {
    const promise = this.execute(runId).finally(() => this.pending.delete(promise));
    this.pending.add(promise);
  }
  private async execute(runId: string) {
    const snapshot = this.store.snapshot(runId)!;
    const cells = this.store.cells(runId);
    await Promise.all(snapshot.transcripts.map(async transcript => {
      const own = cells.filter(cell => cell.transcriptId === transcript.id);
      const reference = this.reference(own.find(cell => cell.modelId === REFERENCE_ID)!, transcript);
      await Promise.all(own.filter(cell => cell.modelId !== REFERENCE_ID && cell.status !== 'completed').map(cell => this.candidate(cell, transcript, reference)));
    }));
  }
  private message(error: unknown) {
    return String(redact(error instanceof Error ? error.message : 'Unexpected error.', this.apiKey()));
  }
  private async reference(cell: MomCell, transcript: MomTranscript): Promise<string | null> {
    if (cell.status === 'completed') return cell.output;
    try {
      this.store.update(cell.id, 'generating', { error: null });
      const result = await this.judging.run(() => this.judge.write(MOM_SYSTEM_PROMPT, buildMomUserMessage(transcript.transcript), this.abort.signal));
      this.store.update(cell.id, 'completed', { generated: true, output: result.value, latencyMs: result.latencyMs, cost: result.cost });
      this.store.saveRaw(cell.id, 'generation', result.raw);
      return result.value;
    } catch (error) {
      if (!this.stopped) this.store.update(cell.id, 'failed', { error: this.message(error) });
      return null;
    }
  }
  private async candidate(cell: MomCell, transcript: MomTranscript, reference: Promise<string | null>) {
    let output = cell.output;
    try {
      if (!cell.generated) {
        this.store.update(cell.id, 'generating', { error: null });
        // Local models queue inside the backend, one model in memory at a time.
        const result = isLocalMomModel(cell.modelId)
          ? { ...await this.localBackend().generate(cell.modelId, transcript.transcript, this.abort.signal), cost: null, provider: 'llama.cpp on this Mac' }
          : { ...await this.hosted.run(() => generateMom(cell.modelId as MomModelId, transcript.transcript, this.apiKey(), this.fetcher, this.abort.signal)), local: null };
        output = result.text;
        this.store.update(cell.id, 'judging', {
          generated: true, output, latencyMs: result.latencyMs, cost: result.cost, usage: result.usage,
          provider: result.provider, finishReason: result.finishReason, local: result.local,
        });
        this.store.saveRaw(cell.id, 'generation', result.response);
        // Returning no minutes (e.g. reasoning ran out of tokens) is a model failure, not a retryable error: it scores 0.
        if (!output) {
          this.store.update(cell.id, 'completed', { score: EMPTY_SCORE, error: `The model returned no minutes (finish reason: ${result.finishReason ?? 'unknown'}). Scored 0 without grading.` });
          return;
        }
      } else this.store.update(cell.id, 'judging', { error: null });
      const referenceText = await reference;
      if (referenceText === null) throw new Error('The judge could not write reference minutes for this transcript, so grading was skipped.');
      const graded = await this.judging.run(() => this.judge.grade(JUDGE_SYSTEM_PROMPT, buildJudgeUserMessage({
        transcript: transcript.transcript, answerKey: transcript.answerKey, reference: referenceText, candidate: output,
      }), judgementJsonSchema, this.abort.signal));
      this.store.saveRaw(cell.id, 'judge', graded.raw);
      const judgement = judgementSchema.parse(graded.value);
      this.store.update(cell.id, 'completed', { judgement, score: scoreJudgement(transcript.answerKey, judgement), judgeLatencyMs: graded.latencyMs, judgeCost: graded.cost });
    } catch (error) {
      if (this.stopped) return;
      if (error instanceof UpstreamError) {
        this.store.saveRaw(cell.id, 'generation', error.body);
        this.store.update(cell.id, 'failed', { error: this.message(error), latencyMs: error.latencyMs });
      } else this.store.update(cell.id, 'failed', { error: this.message(error) });
    }
  }
  private localBackend() {
    if (!this.local) throw new Error('No local model backend is configured.');
    return this.local;
  }
  async close() {
    this.stopped = true;
    this.abort.abort();
    await Promise.allSettled(this.pending);
    await this.local?.close();
    this.store.recover();
  }
}

// Routes under /api/mom. Returns null for other paths.
export function createMomApi(options: { db: Database; judge: Judge; local?: LocalMom; apiKey: () => string; fetcher?: typeof fetch; judgeConcurrency?: number; dataDir?: string }) {
  const store = new MomStore(options.db);
  store.recover();
  const runner = new MomRunner(store, options.judge, options.apiKey, options.fetcher, options.judgeConcurrency, options.local);
  const localStatus = (id: LocalMomModelId) => options.local?.status(id) ?? { available: false, path: null, error: 'No local model backend is configured.' };
  function dataset() {
    try { return { transcripts: loadTranscripts(options.dataDir), error: null }; }
    catch (error) { return { transcripts: [], error: error instanceof Error ? error.message : 'Could not load transcripts.' }; }
  }
  async function handle(req: Request, path: string): Promise<Response | null> {
    if (path === '/api/mom/config' && req.method === 'GET') {
      const data = dataset();
      const local = Object.fromEntries(LOCAL_MOM_MODELS.map(m => [m.id, localStatus(m.id)])) as MomConfig['local'];
      return json({ keyConfigured: Boolean(options.apiKey()), local, judge: { ...options.judge.status(), model: JUDGE_MODEL }, transcripts: data.transcripts.map(summarize), datasetError: data.error } satisfies MomConfig);
    }
    const transcriptMatch = path.match(/^\/api\/mom\/transcripts\/([\w-]+)$/);
    if (transcriptMatch && req.method === 'GET') {
      const transcript = dataset().transcripts.find(t => t.id === transcriptMatch[1]);
      if (!transcript) throw new HttpError(404, 'Transcript not found.');
      return json(transcript);
    }
    if (path === '/api/mom/runs' && req.method === 'GET') return json(store.runs());
    if (path === '/api/mom/runs' && req.method === 'POST') {
      if (!req.headers.get('content-type')?.includes('application/json')) throw new HttpError(415, 'Send JSON.');
      const parsed = createMomRunSchema.safeParse(await req.json());
      if (!parsed.success) throw new HttpError(400, parsed.error.issues.map(i => i.message).join('; '));
      if (parsed.data.models.some(id => !isLocalMomModel(id)) && !options.apiKey()) throw new HttpError(503, 'Add OPENROUTER_API_KEY to .env and restart the server to use hosted models.');
      for (const id of parsed.data.models.filter(isLocalMomModel)) {
        const status = localStatus(id);
        if (!status.available) throw new HttpError(503, status.error || 'The local model is unavailable.');
      }
      const judge = options.judge.status();
      if (!judge.available) throw new HttpError(503, judge.error || 'The judge is unavailable.');
      const data = dataset();
      if (data.error) throw new HttpError(500, data.error);
      const transcripts = data.transcripts.filter(t => parsed.data.transcripts.includes(t.id));
      if (transcripts.length !== parsed.data.transcripts.length) throw new HttpError(400, 'A selected transcript no longer exists. Reload the page.');
      const run = store.createRun(parsed.data.models, transcripts);
      runner.start(run.id);
      return json(run, 201);
    }
    const runMatch = path.match(/^\/api\/mom\/runs\/([\w-]+)(?:\/(export|retry|transcripts\/([\w-]+)))?$/);
    if (!runMatch) return null;
    const [, id, action, transcriptId] = runMatch;
    const run = store.run(id);
    if (!run) throw new HttpError(404, 'Run not found.');
    if (!action && req.method === 'GET') return json(run);
    if (action === 'retry' && req.method === 'POST') {
      if (run.cells.some(cell => ['queued', 'generating', 'judging'].includes(cell.status))) throw new HttpError(409, 'Wait for the run to finish before retrying.');
      if (!store.resetFailed(id)) throw new HttpError(400, 'No failed cells to retry.');
      runner.start(id);
      return json(store.run(id));
    }
    if (transcriptId && req.method === 'GET') {
      const transcript = store.snapshot(id)!.transcripts.find(t => t.id === transcriptId);
      if (!transcript) throw new HttpError(404, 'Transcript not found in this run.');
      return json(transcript);
    }
    if (action === 'export' && req.method === 'GET') {
      return new Response(JSON.stringify({ ...run, snapshot: store.snapshot(id), raw: store.raw(id) }, null, 2), {
        headers: { 'Content-Type': 'application/json', 'Content-Disposition': `attachment; filename="mom-benchmark-${id}.json"`, 'Cache-Control': 'no-store' },
      });
    }
    return null;
  }
  return { store, handle, close: () => runner.close() };
}
