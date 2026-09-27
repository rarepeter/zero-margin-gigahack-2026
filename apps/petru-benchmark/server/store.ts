import { Database } from 'bun:sqlite';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import type { AudioChunk } from './audio';
import { runOptionsSchema, type ChunkResult, type ModelResult, type Recording, type Run, type RunOptions } from '../shared/schema';

type AudioRow = { id: string; metadata: string; chunks: string; original: string };
type RunRow = { id: string; audio_id: string; created_at: string; options: string; models: string };
type ResultRow = {
  id: string; run_id: string; model_id: string; status: ModelResult['status'];
  transcript: string; total_chunks: number; error: string | null; chunks: string;
};

export class Store {
  readonly db: Database;
  constructor(readonly root: string) {
    mkdirSync(root, { recursive: true });
    this.db = new Database(join(root, 'benchmarks.sqlite'), { create: true });
    this.db.exec(`PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;
      CREATE TABLE IF NOT EXISTS recordings (id TEXT PRIMARY KEY, metadata TEXT NOT NULL, chunks TEXT NOT NULL, original TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, audio_id TEXT NOT NULL REFERENCES recordings(id), created_at TEXT NOT NULL, options TEXT NOT NULL, models TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS run_audio (run_id TEXT PRIMARY KEY REFERENCES runs(id), chunks TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS results (id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), model_id TEXT NOT NULL, status TEXT NOT NULL, transcript TEXT NOT NULL DEFAULT '', total_chunks INTEGER NOT NULL, error TEXT, chunks TEXT NOT NULL DEFAULT '[]');
      CREATE INDEX IF NOT EXISTS results_run ON results(run_id);
    `);
  }
  recover() {
    this.db.run("UPDATE results SET status = 'interrupted', error = 'The server stopped during this run. Saved chunks are intact. Start a new run to transcribe again.' WHERE status IN ('queued', 'running')");
  }
  addRecording(recording: Recording, chunks: AudioChunk[], original: string) {
    this.db.run('INSERT INTO recordings VALUES (?, ?, ?, ?)', [recording.id, JSON.stringify(recording), JSON.stringify(chunks), original]);
  }
  recording(id: string) {
    const row = this.db.query<AudioRow, [string]>('SELECT * FROM recordings WHERE id = ?').get(id);
    if (!row) return null;
    return { recording: JSON.parse(row.metadata) as Recording, chunks: JSON.parse(row.chunks) as AudioChunk[], original: row.original };
  }
  recordings() {
    return this.db.query<AudioRow, []>('SELECT * FROM recordings ORDER BY rowid DESC').all().map(row => JSON.parse(row.metadata) as Recording);
  }
  createRun(audioId: string, models: string[], options: RunOptions, preparedChunks?: AudioChunk[]) {
    const recording = this.recording(audioId);
    if (!recording) throw new Error('Recording not found.');
    const chunks = preparedChunks ?? recording.chunks;
    const id = crypto.randomUUID();
    this.db.transaction(() => {
      this.db.run('INSERT INTO runs VALUES (?, ?, ?, ?, ?)', [id, audioId, new Date().toISOString(), JSON.stringify(options), JSON.stringify(models)]);
      this.db.run('INSERT INTO run_audio VALUES (?, ?)', [id, JSON.stringify(chunks)]);
      for (const modelId of models) this.db.run('INSERT INTO results (id, run_id, model_id, status, total_chunks) VALUES (?, ?, ?, ?, ?)', [crypto.randomUUID(), id, modelId, 'queued', chunks.length]);
    })();
    return this.run(id)!;
  }
  runChunks(id: string): AudioChunk[] {
    const row = this.db.query<{ chunks: string }, [string]>('SELECT chunks FROM run_audio WHERE run_id = ?').get(id);
    if (row) return JSON.parse(row.chunks) as AudioChunk[];
    // Runs created before configurable chunking used the recording's original chunks.
    const run = this.db.query<{ audio_id: string }, [string]>('SELECT audio_id FROM runs WHERE id = ?').get(id);
    if (!run) throw new Error('Run not found.');
    return this.recording(run.audio_id)!.chunks;
  }
  private result(row: ResultRow): ModelResult {
    const chunks = JSON.parse(row.chunks) as ChunkResult[];
    const costs = chunks.map(c => c.cost).filter((cost): cost is number => cost !== null);
    return {
      id: row.id, runId: row.run_id, modelId: row.model_id, status: row.status,
      transcript: row.transcript, completedChunks: chunks.filter(c => c.status === 'completed').length,
      totalChunks: row.total_chunks, latencyMs: chunks.reduce((sum, c) => sum + c.latencyMs, 0),
      cost: costs.length ? costs.reduce((sum, cost) => sum + cost, 0) : null,
      error: row.error, chunks,
    };
  }
  resultById(id: string): ModelResult | null {
    const row = this.db.query<ResultRow, [string]>('SELECT * FROM results WHERE id = ?').get(id);
    return row ? this.result(row) : null;
  }
  run(id: string): Run | null {
    const row = this.db.query<RunRow, [string]>('SELECT * FROM runs WHERE id = ?').get(id);
    if (!row) return null;
    return {
      id: row.id, audioId: row.audio_id, createdAt: row.created_at,
      chunkCount: this.runChunks(id).length,
      options: runOptionsSchema.parse(JSON.parse(row.options)), models: JSON.parse(row.models) as string[],
      recording: this.recording(row.audio_id)!.recording,
      results: this.db.query<ResultRow, [string]>('SELECT * FROM results WHERE run_id = ? ORDER BY rowid').all(id).map(row => this.result(row)),
    };
  }
  runs() {
    return this.db.query<{ id: string }, []>('SELECT id FROM runs ORDER BY rowid DESC').all().map(({ id }) => {
      const run = this.run(id)!;
      return { ...run, results: run.results.map(r => ({ ...r, chunks: [] })) };
    });
  }
  status(id: string, status: ModelResult['status'], error: string | null = null) {
    this.db.run('UPDATE results SET status = ?, error = ? WHERE id = ?', [status, error, id]);
  }
  saveChunk(id: string, chunk: ChunkResult) {
    this.db.transaction(() => {
      const row = this.db.query<ResultRow, [string]>('SELECT * FROM results WHERE id = ?').get(id)!;
      const chunks = [...(JSON.parse(row.chunks) as ChunkResult[]), chunk];
      // The separator marks the audio boundary without rewriting model text.
      const transcript = chunks.filter(c => c.status === 'completed').map(c => c.text).join('\n\n');
      this.db.run('UPDATE results SET chunks = ?, transcript = ? WHERE id = ?', [JSON.stringify(chunks), transcript, id]);
    })();
  }
  close() { this.db.close(); }
}
