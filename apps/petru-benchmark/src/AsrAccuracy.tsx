import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowDownToLine, ArrowUpRight, ChevronRight, CircleAlert, FileAudio, FileText, FlaskConical, Gavel, History, Layers3, Plus, RefreshCw, Target, Upload, X } from 'lucide-react';
import { MODELS, type ModelId } from '../shared/models';
import { chunkWindow, MIN_CHUNK_SECONDS, MAX_CHUNK_SECONDS } from '../shared/chunking';
import { ASR_CRITERIA, MAX_REFERENCE_CHARS, normalizeWords, type AsrBenchmark, type AsrCell } from '../shared/asr-benchmark';
import { ASR_JUDGE_SYSTEM_PROMPT } from '../shared/asr-prompt';
import { HOSPITAL_CONTEXT_PROMPT } from '../shared/prompt';
import type { Config, Recording } from '../shared/schema';
import { BenchmarkNav } from './Nav';
import { api, date, duration } from './api';
import { RAMP, scoreStyle } from './score';

type JudgeConfig = { judge: { available: boolean; error: string | null; model: string } };
const benchFromHash = () => location.hash.match(/^#\/accuracy\/([\w-]+)$/)?.[1] ?? null;
const modelName = (id: string) => MODELS.find(m => m.id === id)?.name ?? id;
const mean = (values: number[]) => values.length ? values.reduce((sum, v) => sum + v, 0) / values.length : null;
const isActive = (b: AsrBenchmark) => b.cells.some(c => c.status === 'transcribing' || c.status === 'judging');
const statusText = (b: AsrBenchmark) => isActive(b) ? 'In progress' : b.cells.every(c => c.status === 'completed') ? 'Completed' : 'Needs attention';
const DEFAULT_SIZES = [10, 20, 30];
// Conversational speech rarely drops below this; fewer reference words usually means a partial transcript.
const MIN_WORDS_PER_MINUTE = 80;
const MAX_SIZES = 8;

function CellMark({ cell }: { cell: AsrCell }) {
  if (cell.score !== null) return <>{cell.score.toFixed(0)}</>;
  if (cell.status === 'transcribing') return <span className="cell-status cell-generating">{cell.transcription.completedChunks}/{cell.transcription.totalChunks}</span>;
  const label = { judging: 'Grading', failed: 'Failed', interrupted: 'Stopped', completed: 'Done', transcribing: '' }[cell.status];
  return <span className={`cell-status cell-${cell.status}`}>{label}</span>;
}

type Row = { modelId: string; average: number | null; best: AsrCell | null; wer: number | null; graded: number; total: number };
function rowsFor(benchmark: AsrBenchmark): Row[] {
  return benchmark.models.map(modelId => {
    const cells = benchmark.cells.filter(c => c.modelId === modelId);
    const scored = cells.filter(c => c.score !== null);
    return {
      modelId, average: mean(scored.map(c => c.score!)), graded: scored.length, total: cells.length,
      best: scored.reduce<AsrCell | null>((best, c) => !best || c.score! > best.score! ? c : best, null),
      wer: mean(cells.flatMap(c => c.wer === null ? [] : [c.wer])),
    };
  }).sort((a, b) => (b.average ?? -1) - (a.average ?? -1));
}

function CellDetail({ benchmark, cell, reference }: { benchmark: AsrBenchmark; cell: AsrCell; reference: string | null }) {
  const [transcript, setTranscript] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    void api<{ transcript: string }>(`/api/asr-benchmarks/${benchmark.id}/cells/${cell.id}/transcript`).then(r => { if (live) setTranscript(r.transcript); }).catch(() => { if (live) setTranscript(''); });
    return () => { live = false; };
  }, [benchmark.id, cell.id, cell.status]);
  const judgement = cell.judgement;
  return <section className="panel cell-detail" aria-label="Selected result">
    <header className="detail-header">
      <div className="grow"><div className="eyebrow">{cell.chunkSeconds}S CHUNKS · UP TO {chunkWindow(cell.chunkSeconds).max}S</div><h2>{modelName(cell.modelId)}</h2></div>
      {cell.score !== null && <div className="detail-score" style={scoreStyle(cell.score)}>{cell.score.toFixed(1)}<small>/ 100</small></div>}
    </header>
    {judgement && <div className="breakdown">
      {(Object.keys(ASR_CRITERIA) as (keyof typeof ASR_CRITERIA)[]).map(name => <div key={name} title={ASR_CRITERIA[name].help}><span>{ASR_CRITERIA[name].label} · {ASR_CRITERIA[name].weight * 100}%</span><div className="meter"><i style={{ width: `${judgement.criteria[name]}%` }} /></div><b>{judgement.criteria[name]}%</b></div>)}
    </div>}
    {cell.error && <div className="notice error"><CircleAlert size={16} /><div><strong>{cell.status === 'completed' ? 'Scored without grading' : 'This result did not complete'}</strong><p>{cell.error}</p></div></div>}
    {judgement && <p className="judge-summary"><Gavel size={14} />{judgement.summary}</p>}
    <div className="result-stats detail-stats">
      <span>Normalized WER {cell.wer === null ? '—' : `${cell.wer.toFixed(1)}%`}</span>
      <span>{cell.transcription.completedChunks}/{cell.transcription.totalChunks} chunks</span>
      <span>Transcription time {(cell.transcription.latencyMs / 1000).toFixed(1)}s</span>
      <span>{MODELS.find(m => m.id === cell.modelId)?.provider === 'local' ? 'No API charge' : cell.transcription.cost === null ? 'Cost not reported' : `$${cell.transcription.cost.toFixed(4)}`}</span>
      <span>Judge time {cell.judgeLatencyMs === null ? '—' : `${(cell.judgeLatencyMs / 1000).toFixed(0)}s`}</span>
    </div>
    {judgement && judgement.errors.length > 0 && <>
      <h3 className="modal-heading">Errors that matter <span>{judgement.errors.length}, most severe first</span></h3>
      <table className="verdicts asr-errors">
        <thead><tr><th>Severity</th><th>Reference</th><th>Model</th><th>Why it matters</th></tr></thead>
        <tbody>{judgement.errors.map((error, i) => <tr key={i}>
          <td><span className={`verdict verdict-${error.severity === 'critical' ? 'wrong' : error.severity === 'major' ? 'partial' : 'missing'}`}>{error.severity}</span><span className="kind">{error.category}</span></td>
          <td lang="ro">{error.reference || <span className="muted">—</span>}</td><td lang="ro">{error.hypothesis || <span className="muted">—</span>}</td><td>{error.note}</td>
        </tr>)}</tbody>
      </table>
    </>}
    <div className="detail-columns even">
      <div><h3 className="modal-heading">Your reference</h3><div className="transcript mom-text" lang="ro">{reference ?? <span className="muted">Loading…</span>}</div></div>
      <div><h3 className="modal-heading">{modelName(cell.modelId)} <span>blank lines are chunk boundaries</span></h3><div className="transcript mom-text" lang="ro">{transcript === null ? <span className="muted">Loading…</span> : transcript || <span className="muted">No transcript yet.</span>}</div></div>
    </div>
  </section>;
}

export function AsrAccuracy() {
  const [config, setConfig] = useState<Config>();
  const [judge, setJudge] = useState<JudgeConfig['judge']>();
  const [recordings, setRecordings] = useState<Recording[]>([]);
  const [benchmarks, setBenchmarks] = useState<AsrBenchmark[]>([]);
  const [benchId, setBenchIdState] = useState<string | null>(benchFromHash);
  const [bench, setBench] = useState<AsrBenchmark | null>(null);
  const [recordingId, setRecordingId] = useState('');
  const [reference, setReference] = useState<{ name: string; text: string } | null>(null);
  const [sizes, setSizes] = useState<number[]>(DEFAULT_SIZES);
  const [sizeInput, setSizeInput] = useState('');
  const [models, setModels] = useState<ModelId[]>(MODELS.filter(m => m.primary).map(m => m.id));
  const [useContext, setUseContext] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const [referenceText, setReferenceText] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState<'' | 'upload' | 'start' | 'retry'>('');
  const audioInput = useRef<HTMLInputElement>(null);
  const referenceInput = useRef<HTMLInputElement>(null);
  // The open benchmark lives in the URL (#/accuracy/<id>) so results can be linked and reloaded.
  const setBenchId = (id: string | null) => { setBenchIdState(id); history.replaceState(null, '', id ? `#/accuracy/${id}` : '#/accuracy'); };
  const polling = benchmarks.some(isActive) || Boolean(bench && isActive(bench));

  async function load() {
    const [c, j, r, b] = await Promise.all([api<Config>('/api/config'), api<JudgeConfig>('/api/asr-benchmarks/config'), api<Recording[]>('/api/recordings'), api<AsrBenchmark[]>('/api/asr-benchmarks')]);
    setConfig(c); setJudge(j.judge); setRecordings(r); setBenchmarks(b);
  }
  useEffect(() => { void load().catch(e => setError(String(e.message))); }, []);
  useEffect(() => {
    setSelected(null); setReferenceText(null);
    if (!benchId) { setBench(null); return; }
    let live = true;
    void api<AsrBenchmark>(`/api/asr-benchmarks/${benchId}`).then(b => { if (live) setBench(b); }).catch(e => { if (live) setError(e.message); });
    void api<{ text: string }>(`/api/asr-benchmarks/${benchId}/reference`).then(r => { if (live) setReferenceText(r.text); }).catch(() => {});
    return () => { live = false; };
  }, [benchId]);
  useEffect(() => {
    if (!polling) return;
    let busy = false;
    const timer = setInterval(async () => {
      if (busy) return;
      busy = true;
      try {
        const [list, detail] = await Promise.all([api<AsrBenchmark[]>('/api/asr-benchmarks'), benchId ? api<AsrBenchmark>(`/api/asr-benchmarks/${benchId}`) : Promise.resolve(null)]);
        setBenchmarks(list); if (detail) setBench(detail);
      } catch (e) { setError(e instanceof Error ? e.message : 'Could not refresh results.'); }
      finally { busy = false; }
    }, 2000);
    return () => clearInterval(timer);
  }, [polling, benchId]);

  const available = (id: string) => MODELS.find(m => m.id === id)?.provider === 'local'
    ? Boolean(config?.localWhisper.available)
    : !config?.catalog.ids || config.catalog.ids.includes(id);
  const selectedModels = models.filter(available);
  const needsKey = selectedModels.some(id => MODELS.find(m => m.id === id)?.provider === 'openrouter') && !config?.keyConfigured;
  const recording = recordings.find(r => r.id === recordingId);
  const referenceWords = useMemo(() => reference ? normalizeWords(reference.text).length : 0, [reference]);
  const wordsPerMinute = recording && reference ? referenceWords / (recording.duration / 60) : null;
  const blocker = !recording ? 'Choose or upload a recording.' : !reference ? 'Add your reference transcript.' : !sizes.length ? 'Add at least one chunk size.' : !selectedModels.length ? 'Select at least one model.'
    : needsKey ? 'Add OPENROUTER_API_KEY to .env and restart the server for hosted models.' : judge && !judge.available ? judge.error : null;
  const rows = useMemo(() => bench ? rowsFor(bench) : [], [bench]);
  const selectedCell = bench?.cells.find(c => c.id === selected);
  const finished = bench ? bench.cells.filter(c => c.status !== 'transcribing' && c.status !== 'judging').length : 0;
  const failed = bench ? bench.cells.filter(c => c.status === 'failed' || c.status === 'interrupted').length : 0;

  async function uploadAudio(file?: File) {
    if (!file || busy) return;
    setBusy('upload'); setError('');
    try {
      const body = new FormData(); body.set('audio', file);
      const created = await api<Recording>('/api/recordings', { method: 'POST', body });
      setRecordings(current => [created, ...current]); setRecordingId(created.id);
    } catch (e) { setError(e instanceof Error ? e.message : 'Upload failed.'); }
    finally { setBusy(''); if (audioInput.current) audioInput.current.value = ''; }
  }
  async function readReference(file?: File) {
    if (!file) return;
    setError('');
    if (!/\.(md|markdown|txt)$/i.test(file.name)) { setError('Choose a .md or .txt transcript.'); return; }
    const text = await file.text();
    if (!text.trim()) setError('That transcript is empty.');
    else if (text.length > MAX_REFERENCE_CHARS) setError(`The transcript is longer than ${MAX_REFERENCE_CHARS.toLocaleString()} characters.`);
    else setReference({ name: file.name, text });
    if (referenceInput.current) referenceInput.current.value = '';
  }
  function addSize() {
    const value = Number(sizeInput);
    if (!Number.isInteger(value) || value < MIN_CHUNK_SECONDS || value > MAX_CHUNK_SECONDS) { setError(`Chunk sizes are whole seconds from ${MIN_CHUNK_SECONDS} to ${MAX_CHUNK_SECONDS}.`); return; }
    if (sizes.length >= MAX_SIZES && !sizes.includes(value)) { setError(`Use at most ${MAX_SIZES} chunk sizes.`); return; }
    setSizes(current => [...new Set([...current, value])].sort((a, b) => a - b)); setSizeInput(''); setError('');
  }
  async function start() {
    if (!recording || !reference) return;
    setBusy('start'); setError('');
    try {
      const created = await api<AsrBenchmark>('/api/asr-benchmarks', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ audioId: recording.id, models: selectedModels, chunkSeconds: sizes, reference, useContext }) });
      setBenchmarks(current => [created, ...current]); setBenchId(created.id);
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not start the benchmark.'); }
    finally { setBusy(''); }
  }
  async function retry() {
    if (!bench) return;
    setBusy('retry'); setError('');
    try { setBench(await api<AsrBenchmark>(`/api/asr-benchmarks/${bench.id}/retry`, { method: 'POST' })); setBenchmarks(await api<AsrBenchmark[]>('/api/asr-benchmarks')); }
    catch (e) { setError(e instanceof Error ? e.message : 'Retry failed.'); }
    finally { setBusy(''); }
  }
  const toggle = <T extends string>(list: T[], id: T, on: boolean) => on ? [...list, id] : list.filter(item => item !== id);

  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="/" aria-label="Speechbench home"><span className="brand-mark"><Target size={23} /></span><span>speechbench<small>HOSPITAL MODEL LAB</small></span></a>
      <BenchmarkNav active="accuracy" />
      <button className="new-run" onClick={() => { setBenchId(null); setError(''); }}><Plus size={17} />New accuracy benchmark</button>
      <div className="sidebar-heading"><History size={14} />Benchmark history<span>{benchmarks.length}</span></div>
      <nav className="history" aria-label="ASR accuracy history">
        {benchmarks.length === 0 && <div className="history-empty">Benchmarks appear here. Results are saved on this Mac.</div>}
        {benchmarks.map(item => {
          const best = rowsFor(item)[0];
          return <button key={item.id} className={`history-item ${benchId === item.id ? 'selected' : ''}`} onClick={() => { setBenchId(item.id); setError(''); }}>
            <span className="history-title">{item.recording.name}</span>
            <span>{date(item.createdAt)} · {item.models.length} models × {item.chunkSeconds.length} chunk sizes</span>
            <span className="history-bottom"><i className={isActive(item) ? 'active-dot' : item.cells.every(c => c.status === 'completed') ? 'done-dot' : 'warning-dot'} />{statusText(item)}{best?.average != null && <b>best {best.average.toFixed(0)}</b>}</span>
          </button>;
        })}
      </nav>
      <div className="sidebar-bottom"><span className="storage-indicator" />Saved locally · SQLite</div>
    </aside>
    <main>
      <div className="topbar"><span><FlaskConical size={15} />ASR accuracy · judged by {judge?.model ?? 'Claude'}</span>
        <span className={`connection ${config?.keyConfigured && judge?.available ? 'connected' : ''}`}><i />{!config || !judge ? 'Checking setup…' : !judge.available ? 'Claude CLI not found' : !config.keyConfigured ? 'Judge ready · OpenRouter key not set' : 'OpenRouter and judge ready'}</span>
      </div>
      <div className="workspace">
        <header className="page-header"><div><div className="eyebrow">TRANSCRIPTION ACCURACY</div><h1>{benchId ? 'Which model heard it right?' : 'Rank the models against your own transcript.'}</h1><p>Every model transcribes the same recording at each chunk size. Each result is graded blind against your transcript, on content only.</p></div><div className="language-ribbon" aria-label="Romanian, Russian and English"><span>RO</span><span>РУ</span><span>EN</span></div></header>
        {error && <div className="notice error" role="alert"><CircleAlert size={18} /><div className="grow">{error}</div><button aria-label="Dismiss error" onClick={() => setError('')}><X size={16} /></button></div>}

        {!benchId && <>
          <section className="panel recording-panel">
            <div className="section-title"><h2><FileAudio size={18} />Recording</h2><span className="muted text-xs">M4A or MP3 · up to 250 MB</span></div>
            <input ref={audioInput} className="sr-only" type="file" accept=".m4a,.mp3,.wav,.flac,.ogg,.webm,.aac" onChange={e => void uploadAudio(e.target.files?.[0])} disabled={busy === 'upload'} />
            <button className="upload-area" disabled={busy === 'upload'} onClick={() => audioInput.current?.click()} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); void uploadAudio(e.dataTransfer.files[0]); }}>
              <span className="upload-icon"><Upload size={23} /></span><span><strong>{busy === 'upload' ? 'Preparing your recording…' : 'Drop a recording here, or browse files'}</strong><small>{busy === 'upload' ? 'Converting audio and finding pauses.' : 'The audio your reference transcript describes.'}</small></span><Plus className="upload-plus" size={20} />
            </button>
            {recordings.length > 0 && <label className="recording-select">Or use a saved recording<select value={recordingId} onChange={e => setRecordingId(e.target.value)}><option value="">Choose recording</option>{recordings.map(r => <option key={r.id} value={r.id}>{r.name} · {duration(r.duration)}</option>)}</select></label>}
            {recording && <div className="audio-player inline-player"><FileAudio size={18} /><div><strong>{recording.name}</strong><small>{duration(recording.duration)} · original audio</small></div><audio key={recording.id} controls preload="metadata" src={`/api/recordings/${recording.id}/audio`} /></div>}
          </section>

          <section className="panel">
            <div className="section-title"><h2><FileText size={18} />Reference transcript</h2><span className="muted text-xs">.md or .txt · your most accurate transcript</span></div>
            <input ref={referenceInput} className="sr-only" type="file" accept=".md,.markdown,.txt,text/markdown,text/plain" onChange={e => void readReference(e.target.files?.[0])} />
            {!reference ? <button className="upload-area" onClick={() => referenceInput.current?.click()} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); void readReference(e.dataTransfer.files[0]); }}>
              <span className="upload-icon"><FileText size={23} /></span><span><strong>Drop your transcript here, or browse files</strong><small>It must cover the whole recording. Speaker labels like "A:", "(?)" for uncertain words, and "(standard form)" notes are understood.</small></span><Plus className="upload-plus" size={20} />
            </button> : <div className="reference-card">
              <div className="section-title"><div><strong>{reference.name}</strong><span className="muted text-xs"> · {referenceWords.toLocaleString()} words after normalization</span></div><div className="button-group"><button className="text-button" onClick={() => referenceInput.current?.click()}>Replace</button><button className="text-button" onClick={() => setReference(null)}>Remove</button></div></div>
              {wordsPerMinute !== null && wordsPerMinute < MIN_WORDS_PER_MINUTE && <div className="notice warning"><CircleAlert size={16} /><div><strong>This transcript may not cover the whole recording</strong><p>It has {referenceWords.toLocaleString()} words for {duration(recording!.duration)} of audio, about {Math.round(wordsPerMinute)} words per minute. Speech missing from the reference counts against every model as invented text. Transcribe the whole recording, or upload only the audio it covers.</p></div></div>}
              <pre className="prompt-text reference-preview" lang="ro">{reference.text.slice(0, 1500)}{reference.text.length > 1500 ? '\n…' : ''}</pre>
            </div>}
          </section>

          <section className="panel">
            <div className="section-title"><h2><Layers3 size={18} />Chunk sizes <span className="count">{sizes.length}</span></h2><span className="muted text-xs">Seconds · one column each</span></div>
            <div className="chip-row">
              {sizes.map(size => <span key={size} className="chip">{size} s<small>up to {chunkWindow(size).max} s</small><button aria-label={`Remove ${size} seconds`} onClick={() => setSizes(current => current.filter(s => s !== size))}><X size={12} /></button></span>)}
              <form className="chip-add" onSubmit={e => { e.preventDefault(); addSize(); }}><input type="number" min={MIN_CHUNK_SECONDS} max={MAX_CHUNK_SECONDS} step="1" placeholder="Seconds" value={sizeInput} onChange={e => setSizeInput(e.target.value)} aria-label="Chunk size in seconds" /><button className="text-button" type="submit"><Plus size={13} />Add</button></form>
            </div>
            <p className="field-help">Each size splits the audio near pauses, from {MIN_CHUNK_SECONDS} to {MAX_CHUNK_SECONDS} seconds, with no overlap. Every model gets the same chunks for a given size. Sentence-based chunking comes later.</p>
          </section>

          <section className="panel">
            <div className="section-title"><h2><Layers3 size={18} />Models <span className="count">{selectedModels.length}</span></h2><div className="button-group"><button className="text-button" onClick={() => setModels(MODELS.filter(m => m.primary && available(m.id)).map(m => m.id))}>Core five</button><button className="text-button" onClick={() => setModels(MODELS.filter(m => available(m.id)).map(m => m.id))}>Select all</button><button className="text-button" onClick={() => setModels([])}>Clear</button></div></div>
            <div className="model-grid">{MODELS.map(model => <label key={model.id} className={`model-option ${models.includes(model.id) && available(model.id) ? 'checked' : ''} ${available(model.id) ? '' : 'unavailable'}`}>
              <input type="checkbox" checked={models.includes(model.id) && available(model.id)} disabled={!available(model.id)} onChange={e => setModels(toggle(models, model.id, e.target.checked))} />
              <div><div className="model-name">{model.name}{model.provider === 'local' ? <span className="experimental local-badge">Local</span> : !model.primary && <span className="experimental">Exploratory</span>}</div><div className="model-meta">{model.maker} · {model.size} · {model.license}</div><p>{available(model.id) ? model.note : model.provider === 'local' ? config?.localWhisper.error || 'Local Whisper is not configured.' : 'Not in the current OpenRouter catalog.'}</p></div>
            </label>)}</div>
          </section>

          <section className="panel">
            <div className="section-title"><h2><Gavel size={18} />How grading works</h2><span className="pill">Blind · content only</span></div>
            <ol className="method">
              <li>Each model transcribes the recording once per chunk size, using the same settings as the Speech to text tab: automatic language and temperature 0.</li>
              <li>{judge?.model ?? 'The judge'} compares each finished transcript with your reference without seeing the model's name. It ignores punctuation, capitalization, speaker labels, diacritics that don't change meaning, and whether Russian is in Cyrillic or Latin letters.</li>
              <li>It rates five content criteria from 0 to 100. The score is their weighted mean: {Object.values(ASR_CRITERIA).map(c => `${c.label.toLowerCase()} ${c.weight * 100}%`).join(', ')}.</li>
              <li>A normalized word error rate is shown next to each score as a cross-check. It is not part of the score.</li>
            </ol>
            <label className="checkbox-row"><input type="checkbox" checked={useContext} onChange={e => setUseContext(e.target.checked)} />Use the hospital context prompt for Whisper models</label>
            <p className="field-help">{useContext ? HOSPITAL_CONTEXT_PROMPT : 'Whisper models run without a context hint. Other models never receive one.'}</p>
            <details className="advanced"><summary>Judge grading prompt</summary><pre className="prompt-text">{ASR_JUDGE_SYSTEM_PROMPT}</pre></details>
          </section>

          <div className="start-bar"><div><strong>{selectedModels.length} models × {sizes.length} chunk sizes</strong><span>{blocker ?? `${selectedModels.length * sizes.length} transcriptions of ${duration(recording!.duration)} audio, then ${selectedModels.length * sizes.length} judge calls. You can leave this page.`}</span></div>
            <button className="primary-button" disabled={Boolean(blocker) || Boolean(busy)} onClick={() => void start()}><Target size={17} />{busy === 'start' ? 'Preparing chunks…' : 'Run benchmark'}<ChevronRight size={16} /></button></div>
        </>}

        {benchId && !bench && <div className="panel muted">Loading benchmark…</div>}
        {bench && <>
          <section className="run-summary"><div><span className="eyebrow">ACCURACY BENCHMARK</span><h2>{bench.recording.name}</h2><p>{date(bench.createdAt)} · {duration(bench.recording.duration)} audio · reference {bench.reference.name} ({bench.reference.words.toLocaleString()} words) · {finished}/{bench.cells.length} finished{failed ? ` · ${failed} failed` : ''} · judge {bench.settings.judgeModel}</p></div>
            <div className="run-actions">{failed > 0 && !isActive(bench) && <button className="secondary-button" disabled={Boolean(busy)} onClick={() => void retry()}><RefreshCw size={15} />Retry {failed} failed</button>}<a className="secondary-button" href={`/api/asr-benchmarks/${bench.id}/export`}><ArrowDownToLine size={15} />Export JSON</a></div></section>
          <div className="audio-player"><FileAudio size={18} /><div><strong>Listen</strong><small>Original recording</small></div><audio key={bench.recording.id} controls preload="metadata" src={`/api/recordings/${bench.recording.id}/audio`} /></div>
          <div className="matrix-wrap">
            <table className="matrix">
              <thead><tr>
                <th>#</th><th className="sticky-col">Model</th><th>Average</th>
                {bench.chunkSeconds.map(size => <th key={size} className="transcript-col"><span className="size-head"><small>Chunks</small>{size} s</span></th>)}
                <th>Best chunk</th><th>Avg WER</th>
              </tr></thead>
              <tbody>
                {rows.map((row, rank) => <tr key={row.modelId}>
                  <td className="numeric rank">{row.average === null ? '—' : rank + 1}</td>
                  <th className="sticky-col" scope="row">{modelName(row.modelId)}{MODELS.find(m => m.id === row.modelId)?.provider === 'local' && <span className="experimental local-badge">Local</span>}<small>{MODELS.find(m => m.id === row.modelId)?.maker}</small></th>
                  <td className="average">{row.average === null ? '—' : row.average.toFixed(1)}<small>{row.graded}/{row.total} graded</small></td>
                  {bench.chunkSeconds.map(size => {
                    const cell = bench.cells.find(c => c.modelId === row.modelId && c.chunkSeconds === size);
                    if (!cell) return <td key={size} />;
                    return <td key={size} className="score-cell"><button className={selected === cell.id ? 'selected' : ''} style={cell.score !== null ? scoreStyle(cell.score) : undefined} onClick={() => setSelected(cell.id)}
                      aria-label={`${modelName(cell.modelId)} at ${size} second chunks: ${cell.score !== null ? `${cell.score.toFixed(1)} percent` : cell.status}`}
                      title={cell.score !== null ? `${modelName(cell.modelId)} · ${size}s chunks · WER ${cell.wer ?? '—'}%` : cell.error ?? cell.status}><CellMark cell={cell} /></button></td>;
                  })}
                  <td className="numeric">{row.best ? `${row.best.chunkSeconds} s` : '—'}</td>
                  <td className="numeric">{row.wer === null ? '—' : `${row.wer.toFixed(1)}%`}</td>
                </tr>)}
                <tr className="reference-row">
                  <td /><th className="sticky-col" scope="row">Chunk size average<small>all models</small></th><td />
                  {bench.chunkSeconds.map(size => { const avg = mean(bench.cells.filter(c => c.chunkSeconds === size && c.score !== null).map(c => c.score!)); return <td key={size} className="numeric column-average">{avg === null ? '—' : avg.toFixed(1)}</td>; })}
                  <td colSpan={2} />
                </tr>
              </tbody>
            </table>
          </div>
          <div className="scale-legend" aria-hidden="true"><span>0</span>{RAMP.map(color => <i key={color} style={{ background: color }} />)}<span>100</span><em>Content score out of 100. Rows are ranked by average across chunk sizes. Select a cell for the errors and both transcripts.</em></div>
          {selectedCell && <CellDetail key={selectedCell.id} benchmark={bench} cell={selectedCell} reference={referenceText} />}
          <p className="run-footnote">Averages include graded cells only. Check the graded count. Transcription time is summed request time: network and provider time for hosted models, time on this Mac for local Whisper. Context prompt: {bench.settings.contextPrompt ? 'hospital preset for Whisper models' : 'none'}.</p>
        </>}
        <footer className="page-footer"><span>Speechbench · ASR accuracy</span><a href="https://openrouter.ai/docs/guides/overview/multimodal/stt" target="_blank" rel="noreferrer">OpenRouter transcription docs <ArrowUpRight size={12} /></a></footer>
      </div>
    </main>
  </div>;
}
