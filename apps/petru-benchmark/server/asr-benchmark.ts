import { createHash } from 'node:crypto';
import { HttpError, json } from './http';
import { Semaphore } from './semaphore';
import { JUDGE_EFFORT, type Judge } from './judge';
import { redact } from './openrouter';
import type { Queue } from './queue';
import type { Store } from './store';
import {
  asrJudgementJsonSchema, asrJudgementSchema, createAsrBenchmarkSchema, normalizeWords, scoreAsr, wordErrorRate,
  type AsrBenchmark, type AsrCell, type AsrCellStatus,
} from '../shared/asr-benchmark';
import { ASR_JUDGE_SYSTEM_PROMPT, buildAsrJudgeMessage } from '../shared/asr-prompt';
import { JUDGE_MODEL } from '../shared/mom';
import { HOSPITAL_CONTEXT_PROMPT } from '../shared/prompt';
import { runOptionsSchema, type CreateRun, type Run, type RunOptions } from '../shared/schema';

type CellData = Pick<AsrCell, 'judgement' | 'score' | 'wer' | 'judgeLatencyMs' | 'error'>;
type CellRow = { id: string; benchmark_id: string; model_id: string; chunk_seconds: number; run_id: string; result_id: string; status: AsrCellStatus; data: string };
type BenchmarkRow = { id: string; created_at: string; audio_id: string; models: string; chunk_seconds: string; reference_name: string; reference_text: string; reference_sha: string; options: string };
type Summary = { status: AsrCell['transcription']['status']; total_chunks: number; done: number; latency: number; cost: number | null };
const emptyData: CellData = { judgement: null, score: null, wer: null, judgeLatencyMs: null, error: null };

// Orchestrates accuracy benchmarks on top of the normal transcription queue: one run per chunk size,
// then one blind judge call per finished transcript.
export function createAsrBenchmarkApi(options: {
  store: Store; queue: Queue; judge: Judge; apiKey: () => string; judgeConcurrency?: number;
  prepareRun: (input: CreateRun) => Promise<Run>;
}) {
  const { store, queue, judge } = options;
  const db = store.db;
  db.exec(`CREATE TABLE IF NOT EXISTS asr_benchmarks (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, audio_id TEXT NOT NULL REFERENCES recordings(id), models TEXT NOT NULL, chunk_seconds TEXT NOT NULL, reference_name TEXT NOT NULL, reference_text TEXT NOT NULL, reference_sha TEXT NOT NULL, options TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS asr_cells (id TEXT PRIMARY KEY, benchmark_id TEXT NOT NULL REFERENCES asr_benchmarks(id), model_id TEXT NOT NULL, chunk_seconds INTEGER NOT NULL, run_id TEXT NOT NULL, result_id TEXT NOT NULL, status TEXT NOT NULL, data TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS asr_cells_benchmark ON asr_cells(benchmark_id);
    CREATE INDEX IF NOT EXISTS asr_cells_result ON asr_cells(result_id);`);
  // Nothing runs after a restart: unfinished transcriptions and grades wait for Retry.
  db.run("UPDATE asr_cells SET status = 'interrupted' WHERE status IN ('transcribing', 'judging')");

  const judging = new Semaphore(options.judgeConcurrency ?? 3);
  const abort = new AbortController();
  const pending = new Set<Promise<void>>();
  let stopped = false;

  const benchmarkRow = (id: string) => db.query<BenchmarkRow, [string]>('SELECT * FROM asr_benchmarks WHERE id = ?').get(id);
  const cellRows = (benchmarkId: string) => db.query<CellRow, [string]>('SELECT * FROM asr_cells WHERE benchmark_id = ? ORDER BY rowid').all(benchmarkId);
  const cellRow = (id: string) => db.query<CellRow, [string]>('SELECT * FROM asr_cells WHERE id = ?').get(id);
  function update(id: string, status: AsrCellStatus, patch: Partial<CellData>) {
    db.transaction(() => {
      const row = cellRow(id)!;
      db.run('UPDATE asr_cells SET status = ?, data = ? WHERE id = ?', [status, JSON.stringify({ ...JSON.parse(row.data), ...patch }), id]);
    })();
  }
  // Progress without parsing every stored raw response in JavaScript.
  function summary(resultId: string) {
    return db.query<Summary, [string]>(`SELECT r.status, r.total_chunks,
      (SELECT count(*) FROM json_each(r.chunks) WHERE json_extract(value, '$.status') = 'completed') AS done,
      (SELECT coalesce(sum(json_extract(value, '$.latencyMs')), 0) FROM json_each(r.chunks)) AS latency,
      (SELECT sum(json_extract(value, '$.cost')) FROM json_each(r.chunks)) AS cost
      FROM results r WHERE r.id = ?`).get(resultId);
  }
  function toCell(row: CellRow, light: boolean): AsrCell {
    const data = { ...emptyData, ...JSON.parse(row.data) as Partial<CellData> };
    const s = summary(row.result_id);
    return {
      id: row.id, benchmarkId: row.benchmark_id, modelId: row.model_id, chunkSeconds: row.chunk_seconds, runId: row.run_id, resultId: row.result_id, status: row.status,
      transcription: { status: s?.status ?? 'interrupted', completedChunks: s?.done ?? 0, totalChunks: s?.total_chunks ?? 0, latencyMs: s?.latency ?? 0, cost: s?.cost ?? null },
      ...data, judgement: light ? null : data.judgement,
    };
  }
  function benchmark(id: string, light = false): AsrBenchmark | null {
    const row = benchmarkRow(id);
    if (!row) return null;
    const recording = store.recording(row.audio_id)!.recording;
    const runOptions = runOptionsSchema.parse(JSON.parse(row.options));
    return {
      id: row.id, createdAt: row.created_at, recording, models: JSON.parse(row.models) as string[], chunkSeconds: JSON.parse(row.chunk_seconds) as number[],
      reference: { name: row.reference_name, words: normalizeWords(row.reference_text).length, sha256: row.reference_sha },
      settings: { judgeModel: JUDGE_MODEL, judgeEffort: JUDGE_EFFORT, contextPrompt: runOptions.contextPrompt },
      cells: cellRows(id).map(cell => toCell(cell, light)),
    };
  }

  function track(promise: Promise<void>) {
    pending.add(promise);
    void promise.finally(() => pending.delete(promise));
  }
  // Grades one finished transcript. An empty transcript scores 0 without a judge call.
  async function grade(cellId: string) {
    const row = cellRow(cellId)!;
    const reference = benchmarkRow(row.benchmark_id)!.reference_text;
    const transcript = store.resultById(row.result_id)?.transcript ?? '';
    const wer = wordErrorRate(reference, transcript);
    if (!transcript.trim()) {
      update(cellId, 'completed', { score: 0, wer, error: 'The model returned an empty transcript. Scored 0 without grading.' });
      return;
    }
    update(cellId, 'judging', { wer, error: null });
    try {
      const graded = await judging.run(() => judge.grade(ASR_JUDGE_SYSTEM_PROMPT, buildAsrJudgeMessage(reference, transcript), asrJudgementJsonSchema, abort.signal));
      const judgement = asrJudgementSchema.parse(graded.value);
      update(cellId, 'completed', { judgement, score: scoreAsr(judgement), judgeLatencyMs: graded.latencyMs });
    } catch (error) {
      if (!stopped) update(cellId, 'failed', { error: `Grading failed: ${String(redact(error instanceof Error ? error.message : 'unknown error', options.apiKey()))}` });
    }
  }
  queue.onSettled(resultId => {
    const row = db.query<CellRow, [string]>('SELECT * FROM asr_cells WHERE result_id = ?').get(resultId);
    if (!row) return;
    const result = store.resultById(resultId);
    if (result?.status === 'completed') track(grade(row.id));
    else update(row.id, 'failed', { error: `Transcription ${result?.status ?? 'failed'}: ${result?.error ?? 'no transcript was saved.'}` });
  });

  // One transcription run per chunk size. Runs are saved first and enqueued only after every
  // chunk variant is ready, so a setup failure leaves no half-started benchmark.
  async function createRuns(audioId: string, models: CreateRun['models'], runOptions: RunOptions, sizes: number[]) {
    const runs: Run[] = [];
    try {
      for (const chunkSeconds of sizes) runs.push(await options.prepareRun({ audioId, models, options: { ...runOptions, chunkSeconds } }));
      return runs;
    } catch (error) {
      for (const run of runs) for (const result of run.results) store.status(result.id, 'failed', 'Benchmark setup failed before this run started.');
      throw error;
    }
  }

  async function handle(req: Request, path: string): Promise<Response | null> {
    if (path === '/api/asr-benchmarks/config' && req.method === 'GET') return json({ judge: { ...judge.status(), model: JUDGE_MODEL } });
    if (path === '/api/asr-benchmarks' && req.method === 'GET') {
      return json(db.query<{ id: string }, []>('SELECT id FROM asr_benchmarks ORDER BY rowid DESC').all().map(({ id }) => benchmark(id, true)!));
    }
    if (path === '/api/asr-benchmarks' && req.method === 'POST') {
      if (!req.headers.get('content-type')?.includes('application/json')) throw new HttpError(415, 'Send JSON.');
      const parsed = createAsrBenchmarkSchema.safeParse(await req.json());
      if (!parsed.success) throw new HttpError(400, parsed.error.issues.map(i => i.message).join('; '));
      const input = parsed.data;
      const status = judge.status();
      if (!status.available) throw new HttpError(503, status.error || 'The judge is unavailable.');
      const runOptions = runOptionsSchema.parse({ contextPrompt: input.useContext ? HOSPITAL_CONTEXT_PROMPT : '' });
      const runs = await createRuns(input.audioId, input.models, runOptions, input.chunkSeconds);
      const id = crypto.randomUUID();
      db.transaction(() => {
        db.run('INSERT INTO asr_benchmarks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', [
          id, new Date().toISOString(), input.audioId, JSON.stringify(input.models), JSON.stringify(input.chunkSeconds),
          input.reference.name, input.reference.text, createHash('sha256').update(input.reference.text).digest('hex'), JSON.stringify(runOptions),
        ]);
        for (const run of runs) for (const result of run.results) {
          db.run('INSERT INTO asr_cells VALUES (?, ?, ?, ?, ?, ?, ?, ?)', [crypto.randomUUID(), id, result.modelId, run.options.chunkSeconds, run.id, result.id, 'transcribing', JSON.stringify(emptyData)]);
        }
      })();
      for (const run of runs) queue.enqueue(run);
      return json(benchmark(id), 201);
    }
    const match = path.match(/^\/api\/asr-benchmarks\/([\w-]+)(?:\/(retry|reference|export|cells\/([\w-]+)\/transcript))?$/);
    if (!match) return null;
    const [, id, action, cellId] = match;
    const row = benchmarkRow(id);
    if (!row) throw new HttpError(404, 'Benchmark not found.');
    if (!action && req.method === 'GET') return json(benchmark(id));
    if (action === 'reference' && req.method === 'GET') return json({ name: row.reference_name, text: row.reference_text });
    if (cellId && req.method === 'GET') {
      const cell = cellRow(cellId);
      if (!cell || cell.benchmark_id !== id) throw new HttpError(404, 'Result not found.');
      return json({ transcript: store.resultById(cell.result_id)?.transcript ?? '' });
    }
    if (action === 'retry' && req.method === 'POST') {
      const cells = cellRows(id);
      if (cells.some(cell => cell.status === 'transcribing' || cell.status === 'judging')) throw new HttpError(409, 'Wait for the benchmark to finish before retrying.');
      const retry = cells.filter(cell => cell.status === 'failed' || cell.status === 'interrupted');
      if (!retry.length) throw new HttpError(400, 'No failed results to retry.');
      // Finished transcripts are only graded again; failed transcriptions get a fresh run per chunk size.
      const regrade = retry.filter(cell => store.resultById(cell.result_id)?.status === 'completed');
      const rerun = retry.filter(cell => !regrade.includes(cell));
      const runOptions = runOptionsSchema.parse(JSON.parse(row.options));
      const sizes = [...new Set(rerun.map(cell => cell.chunk_seconds))];
      const runs = await Promise.all(sizes.map(async size => (await createRuns(row.audio_id, rerun.filter(c => c.chunk_seconds === size).map(c => c.model_id) as CreateRun['models'], runOptions, [size]))[0]));
      db.transaction(() => {
        for (const run of runs) for (const result of run.results) {
          const cell = rerun.find(c => c.chunk_seconds === run.options.chunkSeconds && c.model_id === result.modelId)!;
          db.run('UPDATE asr_cells SET run_id = ?, result_id = ?, status = ?, data = ? WHERE id = ?', [run.id, result.id, 'transcribing', JSON.stringify(emptyData), cell.id]);
        }
      })();
      for (const run of runs) queue.enqueue(run);
      for (const cell of regrade) track(grade(cell.id));
      return json(benchmark(id));
    }
    if (action === 'export' && req.method === 'GET') {
      const full = benchmark(id)!;
      const cells = full.cells.map(cell => ({ ...cell, transcript: store.resultById(cell.resultId)?.transcript ?? '' }));
      return new Response(JSON.stringify({ ...full, reference: { ...full.reference, text: row.reference_text }, judgePrompt: ASR_JUDGE_SYSTEM_PROMPT, cells }, null, 2), {
        headers: { 'Content-Type': 'application/json', 'Content-Disposition': `attachment; filename="asr-benchmark-${id}.json"`, 'Cache-Control': 'no-store' },
      });
    }
    return null;
  }

  return {
    handle,
    benchmark,
    close: async () => { stopped = true; abort.abort(); await Promise.allSettled(pending); },
  };
}
