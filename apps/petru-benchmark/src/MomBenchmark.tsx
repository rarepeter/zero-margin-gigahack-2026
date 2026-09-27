import { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowDownToLine, ArrowUpRight, Check, ChevronRight, CircleAlert, FileText, FlaskConical, Gavel, History, Layers3, Plus, RefreshCw, ScrollText, X } from 'lucide-react';
import { MOM_MODELS, REFERENCE_ID, isLocalMomModel, SCORE_WEIGHTS, HALLUCINATION_PENALTY, type MomCell, type MomConfig, type MomModelId, type MomRun, type MomTranscript, type MomTranscriptSummary } from '../shared/mom';
import { JUDGE_SYSTEM_PROMPT, MOM_SYSTEM_PROMPT } from '../shared/mom-prompt';
import { BenchmarkNav } from './Nav';
import { api, date } from './api';
import { RAMP, scoreStyle } from './score';

const typeLabels: Record<MomTranscriptSummary['meetingType'], string> = {
  clinical: 'Clinical', financial: 'Financial', administrative: 'Administrative', executive: 'Executive', operational: 'Operational', crisis: 'Crisis',
};
const activeStatuses = new Set<MomCell['status']>(['queued', 'generating', 'judging']);
const isActive = (run: MomRun) => run.cells.some(cell => activeStatuses.has(cell.status));
const modelName = (id: string) => id === REFERENCE_ID ? 'Judge reference' : MOM_MODELS.find(m => m.id === id)?.name ?? id;
const mean = (values: number[]) => values.length ? values.reduce((sum, v) => sum + v, 0) / values.length : null;
const runFromHash = () => location.hash.match(/^#\/mom\/([\w-]+)$/)?.[1] ?? null;
const seconds = (ms: number | null) => ms === null ? '—' : `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)}s`;

type Row = { modelId: string; average: number | null; graded: number; total: number; latency: number | null; tokens: number | null; cost: number | null };
function rowsFor(run: MomRun): Row[] {
  return run.models.map(modelId => {
    const cells = run.cells.filter(cell => cell.modelId === modelId);
    const scores = cells.flatMap(cell => cell.score ? [cell.score.total] : []);
    const costs = cells.flatMap(cell => cell.cost === null ? [] : [cell.cost]);
    return {
      modelId, average: mean(scores), graded: scores.length, total: cells.length,
      latency: mean(cells.flatMap(cell => cell.latencyMs === null || !cell.generated ? [] : [cell.latencyMs])),
      tokens: mean(cells.flatMap(cell => cell.usage?.completionTokens == null ? [] : [cell.usage.completionTokens])),
      cost: costs.length ? costs.reduce((sum, c) => sum + c, 0) : null,
    };
  }).sort((a, b) => (b.average ?? -1) - (a.average ?? -1));
}

function StatusMark({ cell }: { cell: MomCell }) {
  if (cell.score) return <>{cell.score.total.toFixed(0)}</>;
  const label = { queued: 'Queued', generating: 'Writing', judging: 'Grading', completed: 'Done', failed: 'Failed', interrupted: 'Stopped' }[cell.status];
  return <span className={`cell-status cell-${cell.status}`}>{label}</span>;
}

function TranscriptViewer({ transcript, onClose }: { transcript: MomTranscript; onClose: () => void }) {
  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', close);
    return () => window.removeEventListener('keydown', close);
  }, [onClose]);
  return <div className="modal-backdrop" onClick={onClose}>
    <section className="modal" role="dialog" aria-modal="true" aria-label={transcript.title} onClick={e => e.stopPropagation()}>
      <header className="section-title"><div><div className="eyebrow">{typeLabels[transcript.meetingType].toUpperCase()} · {transcript.id}</div><h2>{transcript.title}</h2><p className="muted text-xs modal-scenario">{transcript.scenario}</p></div><button className="icon-button" onClick={onClose} aria-label="Close"><X size={18} /></button></header>
      <div className="modal-columns">
        <div><h3 className="modal-heading">Raw transcript <span>what every model receives</span></h3><div className="transcript mom-text" lang="ro">{transcript.transcript}</div></div>
        <div><h3 className="modal-heading">Hidden answer key <span>only the judge sees this</span></h3>
          <ul className="key-list">{transcript.answerKey.items.map(item => <li key={item.id}><b>{item.id}</b><span className={`kind kind-${item.kind}`}>{item.kind.replace('_', ' ')}</span>{item.critical && <span className="critical">critical</span>}<p>{item.text}</p>{item.kind === 'action' && <p className="muted">Owner: {item.owner ?? 'not stated'} · Deadline: {item.deadline ?? 'not stated'}</p>}</li>)}</ul>
          <h3 className="modal-heading">Traps</h3>
          <ul className="key-list">{transcript.answerKey.traps.map(trap => <li key={trap.id}><b>{trap.id}</b><p>{trap.text}</p></li>)}</ul>
        </div>
      </div>
    </section>
  </div>;
}

function CellDetail({ run, cell, transcript }: { run: MomRun; cell: MomCell; transcript: MomTranscript | null }) {
  const [view, setView] = useState<'candidate' | 'reference'>('candidate');
  const reference = run.cells.find(c => c.transcriptId === cell.transcriptId && c.modelId === REFERENCE_ID);
  const summary = run.transcripts.find(t => t.id === cell.transcriptId);
  const judgement = cell.judgement;
  const verdicts = new Map(judgement?.items.map(item => [item.id, item]));
  const traps = new Map(judgement?.traps.map(trap => [trap.id, trap]));
  const shown = view === 'reference' ? reference : cell;
  return <section className="panel cell-detail" aria-label="Selected result">
    <header className="detail-header">
      <div className="grow"><div className="eyebrow">{summary ? `${typeLabels[summary.meetingType].toUpperCase()} · ${summary.id}` : cell.transcriptId}</div><h2>{modelName(cell.modelId)} <span className="muted">on</span> {summary?.title ?? cell.transcriptId}</h2></div>
      {cell.score && <div className="detail-score" style={scoreStyle(cell.score.total)}>{cell.score.total.toFixed(1)}<small>/ 100</small></div>}
    </header>
    {cell.score && <div className="breakdown">
      {(Object.keys(SCORE_WEIGHTS) as (keyof typeof SCORE_WEIGHTS)[]).map(part => <div key={part}><span>{part} · {SCORE_WEIGHTS[part] * 100}%</span><div className="meter"><i style={{ width: `${cell.score![part]}%` }} /></div><b>{cell.score![part].toFixed(0)}%</b></div>)}
      <div><span>hallucination penalty</span><b className={cell.score.penalty ? 'penalty' : ''}>{cell.score.penalty ? `−${cell.score.penalty}` : 'none'}</b></div>
    </div>}
    {cell.error && <div className="notice error"><CircleAlert size={16} /><div><strong>{cell.output ? 'Grading did not complete' : 'The model did not return minutes'}</strong><p>{cell.error}</p></div></div>}
    {judgement && <p className="judge-summary"><Gavel size={14} />{judgement.summary}</p>}
    <div className="result-stats detail-stats">
      <span>{cell.local ? 'Local time' : 'Model time'} {seconds(cell.latencyMs)}</span>
      {cell.local && <span>{cell.local.loadMs === null ? 'Model already loaded' : `Load ${seconds(cell.local.loadMs)}`} · prompt {cell.local.promptTokensPerSecond?.toFixed(0) ?? '?'} tok/s · generation {cell.local.generationTokensPerSecond?.toFixed(1) ?? '?'} tok/s</span>}
      <span>{cell.usage ? `${cell.usage.promptTokens ?? '?'} in · ${cell.usage.completionTokens ?? '?'} out${cell.usage.reasoningTokens ? ` (${cell.usage.reasoningTokens} reasoning)` : ''}` : 'Tokens not reported'}</span>
      <span>{cell.provider ? `Served by ${cell.provider}` : 'Provider not reported'}</span>
      {cell.finishReason && cell.finishReason !== 'stop' && <span className="warning-text">Finish reason: {cell.finishReason}</span>}
      <span>{cell.local ? 'No API charge' : cell.cost === null ? 'Cost not reported' : `$${cell.cost.toFixed(4)}`}</span>
      <span>Judge time {seconds(cell.judgeLatencyMs)}</span>
    </div>
    <div className="detail-columns">
      <div>
        <h3 className="modal-heading">Answer key, graded</h3>
        {!transcript ? <p className="muted text-xs">Loading answer key…</p> : <table className="verdicts">
          <thead><tr><th>Item</th><th>Expected</th><th>Verdict</th></tr></thead>
          <tbody>
            {transcript.answerKey.items.map(item => {
              const verdict = verdicts.get(item.id);
              return <tr key={item.id}>
                <td><b>{item.id}</b><span className={`kind kind-${item.kind}`}>{item.kind.replace('_', ' ')}</span>{item.critical && <span className="critical">critical</span>}</td>
                <td>{item.text}{item.kind === 'action' && <small>Owner: {item.owner ?? 'not stated'} · Deadline: {item.deadline ?? 'not stated'}</small>}{verdict?.note && <small className="note">{verdict.note}</small>}</td>
                <td><span className={`verdict verdict-${verdict?.verdict ?? 'pending'}`}>{verdict?.verdict ?? '—'}</span>{item.kind === 'action' && verdict && <small>owner {verdict.owner} · deadline {verdict.deadline}</small>}</td>
              </tr>;
            })}
            {transcript.answerKey.traps.map(trap => {
              const verdict = traps.get(trap.id);
              return <tr key={trap.id}><td><b>{trap.id}</b><span className="kind kind-trap">trap</span></td><td>{trap.text}{verdict?.note && <small className="note">{verdict.note}</small>}</td><td><span className={`verdict verdict-${verdict?.verdict ?? 'pending'}`}>{verdict?.verdict ?? '—'}</span></td></tr>;
            })}
          </tbody>
        </table>}
        {judgement && judgement.hallucinations.length > 0 && <><h3 className="modal-heading">Hallucinations</h3><ul className="key-list">{judgement.hallucinations.map((h, i) => <li key={i}><span className={`verdict verdict-${h.severity === 'major' ? 'wrong' : 'partial'}`}>{h.severity} · −{HALLUCINATION_PENALTY[h.severity]}</span><p>{h.claim}</p><p className="muted">{h.note}</p></li>)}</ul></>}
        {judgement && <><h3 className="modal-heading">Quality, 1–5</h3><div className="quality-grid">{Object.entries(judgement.quality).map(([name, value]) => <div key={name}><span>{name}</span><b>{value}</b></div>)}</div></>}
      </div>
      <div>
        <div className="minutes-toggle" role="tablist">
          <button role="tab" aria-selected={view === 'candidate'} className={view === 'candidate' ? 'active' : ''} onClick={() => setView('candidate')}>Model minutes</button>
          <button role="tab" aria-selected={view === 'reference'} className={view === 'reference' ? 'active' : ''} onClick={() => setView('reference')}>Judge reference</button>
        </div>
        <div className="transcript mom-text" lang="ro">{shown?.output || <span className="muted">{shown?.status === 'failed' ? shown.error : 'Not written yet.'}</span>}</div>
      </div>
    </div>
  </section>;
}

export function MomBenchmark() {
  const [config, setConfig] = useState<MomConfig>();
  const [runs, setRuns] = useState<MomRun[]>([]);
  const [runId, setRunIdState] = useState<string | null>(runFromHash);
  // The open run lives in the URL (#/mom/<id>) so a result can be linked and reloaded.
  const setRunId = (id: string | null) => { setRunIdState(id); history.replaceState(null, '', id ? `#/mom/${id}` : '#/mom'); };
  const [run, setRun] = useState<MomRun | null>(null);
  // Local models add hours of on-device inference, so they are opt-in.
  const [models, setModels] = useState<MomModelId[]>(MOM_MODELS.filter(m => m.provider === 'openrouter').map(m => m.id));
  const [picked, setPicked] = useState<string[] | null>(null);
  const [selected, setSelected] = useState<{ transcriptId: string; modelId: string } | null>(null);
  const [keys, setKeys] = useState<Record<string, MomTranscript>>({});
  const [viewer, setViewer] = useState<MomTranscript | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const polling = runs.some(isActive) || Boolean(run && isActive(run));
  const transcripts = picked ?? config?.transcripts.map(t => t.id) ?? [];

  const load = useCallback(async () => {
    const [c, r] = await Promise.all([api<MomConfig>('/api/mom/config'), api<MomRun[]>('/api/mom/runs')]);
    setConfig(c); setRuns(r);
  }, []);
  useEffect(() => { void load().catch(e => setError(String(e.message))); }, [load]);
  useEffect(() => {
    setSelected(null);
    if (!runId) { setRun(null); return; }
    let live = true;
    void api<MomRun>(`/api/mom/runs/${runId}`).then(r => { if (live) setRun(r); }).catch(e => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [runId]);
  useEffect(() => {
    if (!polling) return;
    let busy = false;
    const timer = setInterval(async () => {
      if (busy) return;
      busy = true;
      try {
        const [list, detail] = await Promise.all([api<MomRun[]>('/api/mom/runs'), runId ? api<MomRun>(`/api/mom/runs/${runId}`) : Promise.resolve(null)]);
        setRuns(list); if (detail) setRun(detail);
      } catch (e) { setError(e instanceof Error ? e.message : 'Could not refresh results.'); }
      finally { busy = false; }
    }, 2000);
    return () => clearInterval(timer);
  }, [polling, runId]);

  // Answer keys come from the run's frozen snapshot, so later dataset edits never change old results.
  async function loadKey(transcriptId: string, open = false) {
    const cacheKey = `${runId ?? 'current'}:${transcriptId}`;
    try {
      let transcript = keys[cacheKey];
      if (!transcript) {
        transcript = await api<MomTranscript>(runId ? `/api/mom/runs/${runId}/transcripts/${transcriptId}` : `/api/mom/transcripts/${transcriptId}`);
        setKeys(current => ({ ...current, [cacheKey]: transcript }));
      }
      if (open) setViewer(transcript);
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not load the transcript.'); }
  }
  // Selecting a cell loads that transcript's answer key once; loadKey skips cached keys.
  useEffect(() => { if (selected) void loadKey(selected.transcriptId); }, [selected?.transcriptId, runId]);

  const rows = useMemo(() => run ? rowsFor(run) : [], [run]);
  const selectedCell = run && selected ? run.cells.find(c => c.transcriptId === selected.transcriptId && c.modelId === selected.modelId) : undefined;
  const cellCount = run ? run.cells.length : 0;
  const doneCount = run ? run.cells.filter(c => !activeStatuses.has(c.status)).length : 0;
  const failedCount = run ? run.cells.filter(c => c.status === 'failed' || c.status === 'interrupted').length : 0;
  const localReady = (id: MomModelId) => !isLocalMomModel(id) || Boolean(config?.local[id].available);
  const selectedModels = models.filter(localReady);
  const hostedCount = selectedModels.filter(id => !isLocalMomModel(id)).length;
  const localCount = selectedModels.length - hostedCount;
  const setupProblem = !config ? 'Checking setup…' : !config.judge.available ? config.judge.error : hostedCount && !config.keyConfigured ? 'Add OPENROUTER_API_KEY to .env and restart the server to use hosted models.' : null;
  const ready = Boolean(config && !setupProblem && !config.datasetError);

  async function start() {
    setBusy(true); setError('');
    try {
      const created = await api<MomRun>('/api/mom/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ models: selectedModels, transcripts }) });
      setRuns(current => [created, ...current]); setRunId(created.id);
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not start the benchmark.'); }
    finally { setBusy(false); }
  }
  async function retry() {
    if (!run) return;
    setBusy(true); setError('');
    try { setRun(await api<MomRun>(`/api/mom/runs/${run.id}/retry`, { method: 'POST' })); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : 'Retry failed.'); }
    finally { setBusy(false); }
  }
  const toggle = <T extends string>(list: T[], id: T, on: boolean) => on ? [...list, id] : list.filter(item => item !== id);

  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="/" aria-label="Speechbench home"><span className="brand-mark"><FileText size={23} /></span><span>speechbench<small>HOSPITAL MODEL LAB</small></span></a>
      <BenchmarkNav active="mom" />
      <button className="new-run" onClick={() => { setRunId(null); setError(''); }}><Plus size={17} />New MoM benchmark</button>
      <div className="sidebar-heading"><History size={14} />Benchmark history<span>{runs.length}</span></div>
      <nav className="history" aria-label="MoM benchmark history">
        {runs.length === 0 && <div className="history-empty">Benchmarks appear here. Results are saved on this Mac.</div>}
        {runs.map(item => {
          const best = rowsFor(item)[0];
          return <button key={item.id} className={`history-item ${runId === item.id ? 'selected' : ''}`} onClick={() => { setRunId(item.id); setError(''); }}>
            <span className="history-title">{item.models.length} models × {item.transcripts.length} transcripts</span>
            <span>{date(item.createdAt)}{best?.average != null ? ` · best ${modelName(best.modelId)} ${best.average.toFixed(0)}` : ''}</span>
            <span className="history-bottom"><i className={isActive(item) ? 'active-dot' : item.cells.every(c => c.status === 'completed') ? 'done-dot' : 'warning-dot'} />{isActive(item) ? 'In progress' : item.cells.every(c => c.status === 'completed') ? 'Completed' : 'Needs attention'}</span>
          </button>;
        })}
      </nav>
      <div className="sidebar-bottom"><span className="storage-indicator" />Saved locally · SQLite</div>
    </aside>
    <main>
      <div className="topbar"><span><FlaskConical size={15} />Open-weight MoM benchmark · judged by {config?.judge.model ?? 'Claude'}</span>
        <span className={`connection ${ready ? 'connected' : ''}`}><i />{!config ? 'Checking setup…' : !config.judge.available ? 'Claude CLI not found' : !config.keyConfigured ? 'Judge ready · OpenRouter key not set' : 'OpenRouter and judge ready'}</span>
      </div>
      <div className="workspace">
        <header className="page-header"><div><div className="eyebrow">STRUCTURED MINUTES</div><h1>{runId ? 'Which minutes would you sign?' : 'Find the model that writes usable minutes.'}</h1><p>Raw Moldovan meeting transcripts in, Romanian minutes out. Each result is graded blind against a hidden answer key.</p></div><div className="language-ribbon" aria-label="Romanian, Russian and English in, Romanian out"><span>RO</span><span>РУ</span><span>EN</span></div></header>
        {error && <div className="notice error" role="alert"><CircleAlert size={18} /><div className="grow">{error}</div><button aria-label="Dismiss error" onClick={() => setError('')}><X size={16} /></button></div>}
        {config?.datasetError && <div className="notice error"><CircleAlert size={18} /><div><strong>The transcript dataset has a problem</strong><p>{config.datasetError}</p></div></div>}

        {!runId && <>
          <section className="panel">
            <div className="section-title"><h2><ScrollText size={18} />Transcripts <span className="count">{transcripts.length}</span></h2><div className="button-group"><button className="text-button" onClick={() => setPicked(config?.transcripts.map(t => t.id) ?? [])}>Select all</button><button className="text-button" onClick={() => setPicked([])}>Clear</button></div></div>
            <p className="settings-intro">Fictional meetings from a private hospital in Chișinău, written as raw ASR output: no speaker labels, Romanian with Russian and English switches. Each hides decisions, corrections, rejected proposals, and actions without owners or deadlines.</p>
            <div className="transcript-list">{config?.transcripts.map(t => <label key={t.id} className={`transcript-option ${transcripts.includes(t.id) ? 'checked' : ''}`}>
              <input type="checkbox" checked={transcripts.includes(t.id)} onChange={e => setPicked(toggle(transcripts, t.id, e.target.checked))} />
              <div className="grow"><div className="model-name">{t.title}<span className="experimental">{typeLabels[t.meetingType]}</span></div><p>{t.scenario}</p><div className="model-meta">{t.words.toLocaleString()} words · {t.items} key items · {t.traps} traps</div></div>
              <button className="text-button" onClick={e => { e.preventDefault(); void loadKey(t.id, true); }}>View</button>
            </label>)}</div>
          </section>
          <section className="panel">
            <div className="section-title"><h2><Layers3 size={18} />Models <span className="count">{selectedModels.length}</span></h2><div className="button-group"><button className="text-button" onClick={() => setModels(MOM_MODELS.filter(m => localReady(m.id)).map(m => m.id))}>Select all</button><button className="text-button" onClick={() => setModels([])}>Clear</button></div></div>
            <div className="model-grid">{MOM_MODELS.map(model => {
              const status = model.provider === 'local' ? config?.local[model.id] : undefined;
              const available = localReady(model.id);
              return <label key={model.id} className={`model-option ${models.includes(model.id) && available ? 'checked' : ''} ${available ? '' : 'unavailable'}`}>
              <input type="checkbox" checked={models.includes(model.id) && available} disabled={!available} onChange={e => setModels(toggle(models, model.id, e.target.checked))} />
              <div><div className="model-name">{model.name}{model.provider === 'local' && <span className="experimental local-badge">Local</span>}</div><div className="model-meta">{model.maker} · {model.size} · {model.license}</div><div className="model-meta">{model.provider === 'local' ? `Weights ${model.memory} · llama.cpp` : `Local weights ${model.memory}`}{model.aaIndex ? ` · AA index ${model.aaIndex}` : ''}</div><p>{status && !status.available ? status.error : model.note}</p>{status?.path && <p className="mono local-path">{status.path}</p>}<a href={model.weights} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()}>Open weights <ArrowUpRight size={11} /></a></div>
            </label>;
            })}</div>
            <p className="field-help">All models fit the team's 48 GB M4 Pro at 4–8 bit next to Whisper. OpenRouter serves them at its providers' precision. Models marked Local run on this Mac through llama.cpp, one model in memory at a time: all jobs for one variant finish before the next loads.</p>
          </section>
          <section className="panel">
            <div className="section-title"><h2><Gavel size={18} />How grading works</h2><span className="pill">Blind · answer key · strict</span></div>
            <ol className="method">
              <li>For each transcript, {config?.judge.model ?? 'the judge'} writes its own minutes first, using the same prompt as the models and without seeing the answer key.</li>
              <li>Every model receives only that prompt and the raw transcript through OpenRouter. It never sees the judge's minutes.</li>
              <li>The judge grades each model's minutes separately, without the model's name. It checks each answer key item and trap, lists hallucinations, and rates quality from 1 to 5.</li>
              <li>The score is calculated in code: {Object.entries(SCORE_WEIGHTS).map(([k, v]) => `${k} ${v * 100}%`).join(', ')}, minus {HALLUCINATION_PENALTY.major} points per major and {HALLUCINATION_PENALTY.minor} per minor hallucination. Distorted items and invented owners or deadlines lose more than omitted ones.</li>
            </ol>
            <details className="advanced"><summary>MoM system prompt (shared by all models and the judge)</summary><pre className="prompt-text">{MOM_SYSTEM_PROMPT}</pre></details>
            <details className="advanced"><summary>Judge grading prompt</summary><pre className="prompt-text">{JUDGE_SYSTEM_PROMPT}</pre></details>
          </section>
          <div className="start-bar"><div><strong>{selectedModels.length} models × {transcripts.length} transcripts</strong><span>{setupProblem ?? `${hostedCount * transcripts.length} OpenRouter calls, ${localCount * transcripts.length} local generations${localCount ? ' (several minutes each)' : ''}, and ${transcripts.length * (selectedModels.length + 1)} judge calls. You can leave this page.`}</span></div>
            <button className="primary-button" disabled={!ready || busy || !selectedModels.length || !transcripts.length} onClick={() => void start()}><FileText size={17} />{busy ? 'Starting…' : 'Run benchmark'}<ChevronRight size={16} /></button></div>
        </>}

        {runId && !run && <div className="panel muted">Loading benchmark…</div>}
        {run && <>
          <section className="run-summary"><div><span className="eyebrow">MOM BENCHMARK</span><h2>{run.models.length} models × {run.transcripts.length} transcripts</h2><p>{date(run.createdAt)} · {doneCount}/{cellCount} results finished{failedCount ? ` · ${failedCount} failed` : ''} · judge {run.settings.judgeModel} ({run.settings.judgeEffort} effort) · model reasoning {run.settings.reasoningEffort}</p></div>
            <div className="run-actions">{failedCount > 0 && !isActive(run) && <button className="secondary-button" disabled={busy} onClick={() => void retry()}><RefreshCw size={15} />Retry {failedCount} failed</button>}<a className="secondary-button" href={`/api/mom/runs/${run.id}/export`}><ArrowDownToLine size={15} />Export JSON</a></div></section>
          <div className="matrix-wrap">
            <table className="matrix">
              <thead><tr>
                <th className="sticky-col">Model</th><th>Average</th>
                {run.transcripts.map(t => <th key={t.id} className="transcript-col"><button onClick={() => void loadKey(t.id, true)} title={`${t.title} · ${t.words} words`}><small>{typeLabels[t.meetingType]}</small>{t.id.split('-')[1]}</button></th>)}
                <th>Avg time</th><th>Avg tokens out</th><th>Cost</th>
              </tr></thead>
              <tbody>
                {rows.map(row => <tr key={row.modelId}>
                  <th className="sticky-col" scope="row">{modelName(row.modelId)}{isLocalMomModel(row.modelId) && <span className="experimental local-badge">Local</span>}<small>{MOM_MODELS.find(m => m.id === row.modelId)?.size}</small></th>
                  <td className="average">{row.average === null ? '—' : row.average.toFixed(1)}<small>{row.graded}/{row.total} graded</small></td>
                  {run.transcripts.map(t => {
                    const cell = run.cells.find(c => c.modelId === row.modelId && c.transcriptId === t.id);
                    if (!cell) return <td key={t.id} />;
                    const isSelected = selected?.modelId === cell.modelId && selected.transcriptId === cell.transcriptId;
                    return <td key={t.id} className="score-cell"><button className={isSelected ? 'selected' : ''} style={cell.score ? scoreStyle(cell.score.total) : undefined} onClick={() => setSelected({ modelId: cell.modelId, transcriptId: cell.transcriptId })} aria-label={`${modelName(cell.modelId)} on ${t.title}: ${cell.score ? `${cell.score.total.toFixed(1)} percent` : cell.status}`} title={cell.score ? `${modelName(cell.modelId)} · ${t.title}\nCoverage ${cell.score.coverage}% · Attribution ${cell.score.attribution}% · Traps ${cell.score.traps}% · Quality ${cell.score.quality}% · Penalty −${cell.score.penalty}` : cell.error ?? cell.status}><StatusMark cell={cell} /></button></td>;
                  })}
                  <td className="numeric">{seconds(row.latency)}</td><td className="numeric">{row.tokens === null ? '—' : Math.round(row.tokens).toLocaleString()}</td><td className="numeric">{isLocalMomModel(row.modelId) ? 'No API charge' : row.cost === null ? '—' : `$${row.cost.toFixed(row.cost < 0.01 ? 4 : 3)}`}</td>
                </tr>)}
                <tr className="reference-row">
                  <th className="sticky-col" scope="row">Judge reference<small>{run.settings.judgeModel} · not graded</small></th><td />
                  {run.transcripts.map(t => {
                    const cell = run.cells.find(c => c.modelId === REFERENCE_ID && c.transcriptId === t.id);
                    return <td key={t.id} className="score-cell">{cell && <button onClick={() => setSelected({ modelId: REFERENCE_ID, transcriptId: t.id })} title={cell.error ?? cell.status}>{cell.status === 'completed' ? <Check size={14} aria-label="Written" /> : <StatusMark cell={cell} />}</button>}</td>;
                  })}
                  <td colSpan={3} />
                </tr>
              </tbody>
            </table>
          </div>
          <div className="scale-legend" aria-hidden="true"><span>0</span>{RAMP.map(color => <i key={color} style={{ background: color }} />)}<span>100</span><em>Score out of 100. Select a cell for the graded answer key, the model's minutes, and the judge's reference.</em></div>
          {selectedCell && (selectedCell.modelId === REFERENCE_ID
            ? <section className="panel cell-detail"><header className="detail-header"><div className="grow"><div className="eyebrow">JUDGE REFERENCE · NOT GRADED</div><h2>{run.transcripts.find(t => t.id === selectedCell.transcriptId)?.title}</h2></div></header>{selectedCell.error && <div className="notice error"><CircleAlert size={16} /><div>{selectedCell.error}</div></div>}<div className="transcript mom-text" lang="ro">{selectedCell.output || <span className="muted">Not written yet.</span>}</div></section>
            : <CellDetail key={selectedCell.id} run={run} cell={selectedCell} transcript={keys[`${run.id}:${selectedCell.transcriptId}`] ?? null} />)}
          <p className="run-footnote">Averages include graded cells only; check the graded count. Time is OpenRouter wall-clock time for hosted models and measured time on this Mac for Local models, excluding model loading. Use the token counts to estimate local speed. Judge costs are the Claude CLI's list-price estimates and are not shown.</p>
        </>}
        <footer className="page-footer"><span>Speechbench · MoM benchmark · fictional data only</span><a href="https://artificialanalysis.ai/models/open-source/small" target="_blank" rel="noreferrer">Artificial Analysis open-model rankings <ArrowUpRight size={12} /></a></footer>
      </div>
    </main>
    {viewer && <TranscriptViewer transcript={viewer} onClose={() => setViewer(null)} />}
  </div>;
}
