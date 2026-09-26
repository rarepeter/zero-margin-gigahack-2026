import { useCallback, useEffect, useRef, useState } from 'react';
import { AudioLines, ArrowDownToLine, ArrowUpRight, Check, ChevronRight, CircleAlert, Clock3, Copy, FileAudio, FlaskConical, History, Layers3, Plus, RefreshCw, Settings2, Upload, X } from 'lucide-react';
import { z } from 'zod';
import { MODELS, unavailableModels, type ModelId } from '../shared/models';
import { chunkWindow, DEFAULT_CHUNK_SECONDS, MIN_CHUNK_SECONDS, MAX_CHUNK_SECONDS } from '../shared/chunking';
import { runOptionsSchema, type Config, type ModelResult, type Recording, type Run, type RunOptions } from '../shared/schema';
import { HOSPITAL_CONTEXT_PROMPT } from '../shared/prompt';

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  const body: unknown = await response.json();
  if (!response.ok) {
    const parsed = z.object({ error: z.string() }).safeParse(body);
    throw new Error(parsed.success ? parsed.data.error : `Request failed (${response.status}).`);
  }
  return body as T;
}
const duration = (seconds: number) => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
const date = (value: string) => new Date(value).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
const isActive = (run: Run) => run.results.some(r => r.status === 'queued' || r.status === 'running');
const statusLabel = (run: Run) => isActive(run) ? 'In progress' : run.results.every(r => r.status === 'completed') ? 'Completed' : 'Needs attention';
const localStateLabels = {
  unavailable: 'Not configured', idle: 'Configured · loads on first run', loading: 'Loading model',
  ready: 'Ready', running: 'Transcribing', error: 'Last run failed',
} satisfies Record<Config['localWhisper']['state'], string>;

function downloadText(text: string, name: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }));
  const a = document.createElement('a');
  a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const timedResponse = z.object({ segments: z.array(z.object({
  start: z.number(), end: z.number(), text: z.string(), speaker: z.union([z.number(), z.string()]).optional(),
})).optional() });

function ResultCard({ result, chunkSeconds, seek }: { result: ModelResult; chunkSeconds: number; seek: (seconds: number) => void }) {
  const model = MODELS.find(m => m.id === result.modelId);
  const local = model?.provider === 'local';
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState('');
  async function copy() {
    try { await navigator.clipboard.writeText(result.transcript); setCopied(true); setTimeout(() => setCopied(false), 1800); }
    catch { setCopyError('Clipboard unavailable. Use Download text.'); }
  }
  const segments = result.chunks.flatMap(chunk => {
    const data = timedResponse.safeParse(chunk.response);
    return data.success ? (data.data.segments || []).map(segment => ({ ...segment, start: segment.start + chunk.start, end: segment.end + chunk.start })) : [];
  });
  return <article className="result-card" aria-label={`${model?.name || result.modelId} transcript`}>
    <header className="result-heading">
      <div className="model-avatar">{model?.maker.slice(0, 1) || 'M'}</div>
      <div className="grow"><h3>{model?.name || result.modelId}</h3><span className="muted text-xs">{local ? 'Local · ' : ''}{model?.maker} · {model?.size} · {result.completedChunks}/{result.totalChunks} chunks</span></div>
      <span className={`status status-${result.status}`}>{result.status === 'completed' && <Check size={12} />}{result.status}</span>
    </header>
    <p className="chunking-label"><Layers3 size={13} />{chunkSeconds}s chunk target · up to {chunkWindow(chunkSeconds).max}s · split near pauses</p>
    <div className="result-stats">
      <span><Clock3 size={13} /> {result.latencyMs ? `${(result.latencyMs / 1000).toFixed(1)}s ${local ? 'local time' : 'API time'}` : 'Waiting'}</span>
      <span>{local ? 'No API charge' : result.cost === null ? 'Cost not reported' : `$${result.cost.toFixed(5)} reported cost`}</span>
      <span>{result.transcript ? `${result.transcript.trim().split(/\s+/u).filter(Boolean).length} words` : 'No text yet'}</span>
    </div>
    {result.error && <div className="notice error"><CircleAlert size={16} /><div><strong>{result.transcript ? 'Partial transcript saved' : 'Transcription did not complete'}</strong><p>{result.error}</p></div></div>}
    <div className="transcript" dir="auto">{result.transcript || <span className="muted">{result.status === 'completed' ? 'The model returned an empty transcript.' : result.status === 'running' ? 'Transcribing. Text appears here as each chunk finishes.' : result.status === 'queued' ? 'Queued. This model will start when a request slot is free.' : 'No transcript was returned.'}</span>}</div>
    <footer className="result-actions">
      <button className="text-button" onClick={copy} disabled={!result.transcript}>{copied ? <Check size={14} /> : <Copy size={14} />}{copied ? 'Copied' : 'Copy transcript'}</button>
      <button className="text-button" disabled={!result.transcript} onClick={() => downloadText(result.transcript, `${model?.name || 'transcript'}-${result.id}.txt`)}><ArrowDownToLine size={14} />Download text</button>
      {copyError && <span role="alert" className="muted text-xs">{copyError}</span>}
    </footer>
    {segments.length > 0 && <details className="result-details"><summary>{local ? 'Timestamped words' : 'Timestamped segments'} <span>{segments.length}</span></summary><div className="segments">{segments.map((segment, i) => <button key={i} onClick={() => seek(segment.start)}><span className="mono">{duration(segment.start)}</span><span>{segment.speaker !== undefined && <strong>Speaker {segment.speaker} · </strong>}{segment.text}</span></button>)}</div><p className="muted text-xs">Times include the chunk offset. Speaker IDs may restart in each chunk.</p></details>}
    <details className="result-details"><summary>Requests & raw responses <span>{result.chunks.length}</span></summary>
      {result.chunks.length === 0 ? <p className="muted">Saved after the first request finishes.</p> : result.chunks.map(chunk => <details className="chunk-details" key={chunk.index}><summary>Chunk {chunk.index + 1} · {duration(chunk.start)}–{duration(chunk.end)} · {chunk.status}</summary><pre>{JSON.stringify({ request: chunk.request, response: chunk.response, generationId: chunk.generationId, error: chunk.error }, null, 2)}</pre></details>)}
    </details>
  </article>;
}

export function App() {
  const [config, setConfig] = useState<Config>();
  const [recordings, setRecordings] = useState<Recording[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [recordingId, setRecordingId] = useState('');
  const [runId, setRunId] = useState<string | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [models, setModels] = useState<ModelId[]>(MODELS.filter(m => m.primary).map(m => m.id));
  const [options, setOptions] = useState<RunOptions>(runOptionsSchema.parse({ contextPrompt: HOSPITAL_CONTEXT_PROMPT }));
  const [chunkSecondsInput, setChunkSecondsInput] = useState(String(DEFAULT_CHUNK_SECONDS));
  const [providerText, setProviderText] = useState('{}');
  const [error, setError] = useState('');
  const [uploading, setUploading] = useState(false);
  const [starting, setStarting] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [showSetup, setShowSetup] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const player = useRef<HTMLAudioElement>(null);
  const polling = runs.some(isActive) || Boolean(run && isActive(run));

  const load = useCallback(async () => {
    const [c, a, r] = await Promise.all([api<Config>('/api/config'), api<Recording[]>('/api/recordings'), api<Run[]>('/api/runs')]);
    setConfig(c); setRecordings(a); setRuns(r);
  }, []);
  useEffect(() => { void load().catch(e => setError(String(e.message))); }, [load]);
  useEffect(() => {
    if (!runId) { setRun(null); return; }
    let live = true;
    setRun(null);
    void api<Run>(`/api/runs/${runId}`).then(r => { if (live) setRun(r); }).catch(e => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [runId]);
  useEffect(() => {
    if (!polling) return;
    let busy = false;
    let live = true;
    const timer = setInterval(async () => {
      if (busy) return;
      busy = true;
      try {
        const [list, detail, currentConfig] = await Promise.all([api<Run[]>('/api/runs'), runId ? api<Run>(`/api/runs/${runId}`) : Promise.resolve(null), api<Config>('/api/config')]);
        if (live) { setRuns(list); setConfig(currentConfig); if (detail) setRun(detail); }
      } catch (e) { if (live) setError(e instanceof Error ? e.message : 'Could not refresh results.'); }
      finally { busy = false; }
    }, 1500);
    return () => { live = false; clearInterval(timer); };
  }, [polling, runId]);

  const available = (id: string) => MODELS.find(model => model.id === id)?.provider === 'local'
    ? Boolean(config?.localWhisper.available)
    : !config?.catalog.ids || config.catalog.ids.includes(id);
  const selectedRecording = recordings.find(r => r.id === recordingId);
  const visibleRecording = run?.recording || (!runId ? selectedRecording : undefined);
  const selectedModels = models.filter(available);
  const needsKey = selectedModels.some(id => MODELS.find(model => model.id === id)?.provider === 'openrouter') && !config?.keyConfigured;
  const chunkSize = runOptionsSchema.shape.chunkSeconds.safeParse(Number(chunkSecondsInput));
  const unpromptedModels = MODELS.filter(model => selectedModels.includes(model.id) && model.family !== 'whisper');
  let groqPromptOverride = false;
  try { groqPromptOverride = Object.hasOwn(runOptionsSchema.shape.providerOptions.parse(JSON.parse(providerText)).groq ?? {}, 'prompt'); } catch { /* Validated when starting the run. */ }

  async function upload(file?: File) {
    if (!file || uploading) return;
    setUploading(true); setError(''); setRunId(null);
    try {
      const body = new FormData(); body.set('audio', file);
      const recording = await api<Recording>('/api/recordings', { method: 'POST', body });
      setRecordings(current => [recording, ...current]); setRecordingId(recording.id);
    } catch (e) { setError(e instanceof Error ? e.message : 'Upload failed.'); }
    finally { setUploading(false); if (fileInput.current) fileInput.current.value = ''; }
  }

  async function start() {
    setStarting(true); setError('');
    try {
      let custom: unknown;
      try { custom = JSON.parse(providerText); } catch { throw new Error('Provider options must be valid JSON.'); }
      const settings = runOptionsSchema.parse({ ...options, chunkSeconds: Number(chunkSecondsInput), providerOptions: custom });
      const newRun = await api<Run>('/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ audioId: recordingId, models: selectedModels, options: settings }) });
      setRuns(current => [newRun, ...current]); setRunId(newRun.id);
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not start the run.'); }
    finally { setStarting(false); }
  }

  function repeat() {
    if (!run) return;
    setRecordingId(run.audioId);
    setModels(MODELS.filter(m => run.models.includes(m.id)).map(m => m.id));
    setChunkSecondsInput(String(run.options.chunkSeconds));
    setOptions(run.options); setProviderText(JSON.stringify(run.options.providerOptions, null, 2)); setRunId(null);
  }
  async function refreshCatalog() {
    setRefreshing(true); setError('');
    try { await api('/api/catalog/refresh', { method: 'POST' }); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : 'Refresh failed.'); }
    finally { setRefreshing(false); }
  }

  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="/" aria-label="Speechbench home"><span className="brand-mark"><AudioLines size={23} /></span><span>speechbench<small>TRANSCRIPTION LAB</small></span></a>
      <button className="new-run" onClick={() => { setRunId(null); setError(''); }}><Plus size={17} />New comparison</button>
      <div className="sidebar-heading"><History size={14} />Run history<span>{runs.length}</span></div>
      <nav className="history" aria-label="Run history">
        {runs.length === 0 && <div className="history-empty">Your comparisons will appear here. Every run is saved on this Mac.</div>}
        {runs.map(item => <button key={item.id} className={`history-item ${runId === item.id ? 'selected' : ''}`} onClick={() => { setRunId(item.id); setError(''); }}><span className="history-title">{item.recording.name}</span><span>{date(item.createdAt)} · {item.options.chunkSeconds}s chunk target</span><span className="history-bottom"><i className={isActive(item) ? 'active-dot' : item.results.every(r => r.status === 'completed') ? 'done-dot' : 'warning-dot'} />{statusLabel(item)}<b>{item.models.length} {item.models.length === 1 ? 'model' : 'models'}</b></span></button>)}
      </nav>
      <div className="sidebar-bottom"><span className="storage-indicator" />Saved locally · SQLite<button onClick={() => setShowSetup(v => !v)}><Settings2 size={14} />Connection & setup</button></div>
    </aside>
    <main>
      <div className="topbar"><span><FlaskConical size={15} />Open-weight model benchmark</span><button className={`connection ${config?.keyConfigured ? 'connected' : ''}`} onClick={() => setShowSetup(v => !v)}><i />{config?.keyConfigured ? 'OpenRouter configured' : 'OpenRouter key not set'}<ChevronRight size={13} /></button></div>
      <div className="workspace">
        <header className="page-header"><div><div className="eyebrow">MIXED-LANGUAGE SPEECH</div><h1>{runId ? 'The words, side by side.' : 'Compare what each model hears.'}</h1><p>Romanian, Russian, English. Including the way people speak in Moldova.</p></div><div className="language-ribbon" aria-label="Romanian, Russian and English"><span>RO</span><span>РУ</span><span>EN</span></div></header>
        {error && <div className="notice error" role="alert"><CircleAlert size={18} /><div className="grow">{error}</div><button aria-label="Dismiss error" onClick={() => setError('')}><X size={16} /></button></div>}
        {showSetup && <section className="setup-panel"><div className="section-title"><h2>Connection & setup</h2><button className="icon-button" onClick={() => setShowSetup(false)} aria-label="Close setup"><X size={18} /></button></div><p>Put your key in a local <code>.env</code> file, then restart the server. The key stays on the server.</p><pre>OPENROUTER_API_KEY=your-key-here</pre><div className="setup-links"><a href="https://openrouter.ai/settings/keys" target="_blank" rel="noreferrer">Create API key <ArrowUpRight size={14} /></a><a href="https://openrouter.ai/settings/credits" target="_blank" rel="noreferrer">OpenRouter billing <ArrowUpRight size={14} /></a></div><p className="muted text-xs">Audio conversion: {config?.ffmpegAvailable ? 'FFmpeg is ready.' : 'Install FFmpeg with brew install ffmpeg.'} Uploads, local runs, and saved results work without an OpenRouter key.</p><p>Local Whisper: {config?.localWhisper.available ? `${localStateLabels[config.localWhisper.state]}${config.localWhisper.device ? ` · ${config.localWhisper.device.toUpperCase()}` : ''}` : 'not configured'}. {config?.localWhisper.error}</p><p className="muted text-xs">Install the Python dependencies from local/requirements.txt, then set LOCAL_WHISPER_MODEL_PATH in .env and restart. The model loads on the first local run.</p></section>}

        {!runId && <>
          <section className="panel recording-panel">
            <div className="section-title"><h2><FileAudio size={18} />Recording</h2><span className="muted text-xs">M4A supported · up to 250 MB</span></div>
            <input ref={fileInput} className="sr-only" type="file" id="audio-upload" accept=".m4a,.mp3,.wav,.flac,.ogg,.webm,.aac" onChange={e => void upload(e.target.files?.[0])} disabled={uploading} />
            <button className={`upload-area ${dragging ? 'dragging' : ''}`} disabled={uploading} onClick={() => fileInput.current?.click()} onDragOver={e => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={e => { e.preventDefault(); setDragging(false); void upload(e.dataTransfer.files[0]); }}>
              <span className="upload-icon"><Upload size={23} /></span><span><strong>{uploading ? 'Preparing your recording…' : 'Drop a recording here, or browse files'}</strong><small>{uploading ? 'Converting audio and finding pauses. This can take a moment.' : 'Upload once. Compare every model on the same audio.'}</small></span><Plus className="upload-plus" size={20} />
            </button>
            {recordings.length > 0 && <label className="recording-select">Or use a saved recording<select value={recordingId} onChange={e => setRecordingId(e.target.value)}><option value="">Choose recording</option>{recordings.map(r => <option key={r.id} value={r.id}>{r.name} · {duration(r.duration)}</option>)}</select></label>}
          </section>
          {visibleRecording && <div className="audio-player"><FileAudio size={18} /><div><strong>{visibleRecording.name}</strong><small>{duration(visibleRecording.duration)} · original audio</small></div><audio key={visibleRecording.id} ref={player} controls preload="metadata" src={`/api/recordings/${visibleRecording.id}/audio`} /></div>}
          <section className="panel">
            <div className="section-title"><h2><Layers3 size={18} />Models to compare <span className="count">{selectedModels.length}</span></h2><div className="button-group"><button className="text-button" onClick={() => setModels(MODELS.filter(m => m.primary && available(m.id)).map(m => m.id))}>Core five</button><button className="text-button" onClick={() => setModels(MODELS.filter(m => available(m.id)).map(m => m.id))}>Select all</button></div></div>
            <div className="model-grid">{MODELS.map(model => <label key={model.id} className={`model-option ${models.includes(model.id) && available(model.id) ? 'checked' : ''} ${!available(model.id) ? 'unavailable' : ''}`}><input type="checkbox" checked={models.includes(model.id) && available(model.id)} disabled={!available(model.id)} onChange={e => setModels(current => e.target.checked ? [...current, model.id] : current.filter(id => id !== model.id))} /><div><div className="model-name">{model.name}{model.provider === 'local' ? <span className="experimental">Local</span> : !model.primary && <span className="experimental">Exploratory</span>}</div><div className="model-meta">{model.maker} · {model.size} · {model.license}</div><p>{available(model.id) ? model.note : model.provider === 'local' ? config?.localWhisper.error || 'Checking local setup…' : 'Not in the current OpenRouter catalog.'}</p><a href={model.weights} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()}>Open weights <ArrowUpRight size={11} /></a></div></label>)}</div>
            <p className="field-help">Two OpenRouter models and one local model can run at the same time. Local Whisper: {config?.localWhisper.available ? `${localStateLabels[config.localWhisper.state]}${config.localWhisper.device ? ` · ${config.localWhisper.device.toUpperCase()}` : ''}` : 'not configured'}.</p>
            <div className="catalog-line"><span>{config?.catalog.checkedAt ? `Availability checked ${date(config.catalog.checkedAt)}` : config?.catalog.error || 'Checking live availability…'}</span><button className="text-button" disabled={refreshing} onClick={() => void refreshCatalog()}><RefreshCw size={12} />{refreshing ? 'Checking…' : 'Refresh'}</button></div>
            <details className="availability"><summary>What about VibeVoice and Canary?</summary>{unavailableModels.map(m => <p key={m.name}><a href={m.weights} target="_blank" rel="noreferrer">{m.name}</a> · {m.reason}</p>)}<p>Only models with verified downloadable weights are included. Closed models and unverified weight releases are excluded.</p></details>
          </section>
          <section className="panel settings-panel">
            <div className="section-title"><h2><Settings2 size={18} />Transcription settings</h2><span className="pill">Mixed-language defaults</span></div>
            <p className="settings-intro">Automatic language detection, temperature 0, original text preserved. No translation or transcript rewriting.</p>
            <label className="field-label chunk-size-field" htmlFor="chunk-seconds">Target chunk size (seconds)<input id="chunk-seconds" type="number" min={MIN_CHUNK_SECONDS} max={MAX_CHUNK_SECONDS} step="1" value={chunkSecondsInput} onChange={e => setChunkSecondsInput(e.target.value)} aria-invalid={!chunkSize.success} aria-describedby="chunk-help" /></label>
            <p className="field-help" id="chunk-help">{chunkSize.success ? `Splits near pauses, up to ${chunkWindow(chunkSize.data).max} seconds per chunk. No overlap. All selected models receive the same chunks. Larger chunks keep more context but can take longer or time out.` : `Enter a whole number from ${MIN_CHUNK_SECONDS} to ${MAX_CHUNK_SECONDS} seconds.`}</p>
            <div className="prompt-heading"><label className="field-label" htmlFor="context-prompt">Transcription context <span>Optional</span></label><div className="button-group"><button className="text-button" onClick={() => setOptions(o => ({ ...o, contextPrompt: HOSPITAL_CONTEXT_PROMPT }))}>Use hospital preset</button><button className="text-button" disabled={!options.contextPrompt} onClick={() => setOptions(o => ({ ...o, contextPrompt: '' }))}>Clear context</button></div></div>
            <textarea id="context-prompt" rows={6} maxLength={1500} value={options.contextPrompt} onChange={e => setOptions(o => ({ ...o, contextPrompt: e.target.value }))} aria-describedby="context-help context-support" placeholder="Describe the setting, language mix, and terminology expected in this recording." />
            <p className="field-help" id="context-help">Context for recognition, not a chat system prompt. Sent with the vocabulary below on each audio chunk. Keep both fields brief: Whisper has room for about 224 tokens. Clear both for a run without hints.</p>
            <div className="prompt-support" id="context-support"><p>Local Whisper receives this context. Hosted Whisper receives it when Groq serves the request; other routes may ignore it.</p>{unpromptedModels.length > 0 && <p>No verified context support through the current integration for: {unpromptedModels.map(model => model.name).join(', ')}. These models run without this hint.</p>}{groqPromptOverride && <p className="prompt-warning">The Groq prompt in Advanced options overrides context and vocabulary for hosted Whisper. Local Whisper still uses the fields above.</p>}{options.contextPrompt.trim() && options.language !== 'auto' && <p className="prompt-warning">Language is forced to {options.language}. Choose Automatic in Advanced options to avoid constraining mixed speech to one language.</p>}</div>
            <label className="field-label" htmlFor="vocabulary">Names & vocabulary <span>Optional</span></label><textarea id="vocabulary" rows={2} maxLength={1500} value={options.vocabulary} onChange={e => setOptions(o => ({ ...o, vocabulary: e.target.value }))} placeholder="Names, local terms, medical terminology, English product names…" />
            <p className="field-help">Add a few exact spellings, medicine names, or abbreviations actually present in the audio. These share the context budget above. Leave empty if you do not know which terms occur.</p>
            <details className="advanced"><summary>Advanced options</summary><div className="advanced-grid"><label className="field-label">Language<select value={options.language} onChange={e => setOptions(o => ({ ...o, language: runOptionsSchema.shape.language.parse(e.target.value) }))}><option value="auto">Automatic · recommended for mixed speech</option><option value="ro">Force Romanian</option><option value="ru">Force Russian</option><option value="en">Force English</option></select></label><label className="field-label">Temperature<input type="number" step="0.1" min="0" max="1" value={options.temperature} onChange={e => setOptions(o => ({ ...o, temperature: Number(e.target.value) }))} /></label></div>
              <label className="checkbox-row"><input type="checkbox" checked={options.timestamps} onChange={e => setOptions(o => ({ ...o, timestamps: e.target.checked }))} />Request timestamps</label><p className="field-help">Local Whisper returns word timestamps. Hosted models are asked for word and segment timestamps; some endpoints reject them. Rejected requests are saved as failures.</p>
              <label className="field-label" htmlFor="provider-options">Provider-specific options <span>JSON object, keyed by provider</span></label><textarea id="provider-options" className="mono" rows={5} value={providerText} onChange={e => setProviderText(e.target.value)} spellCheck={false} /><p className="field-help">Sent as provider.options to selected OpenRouter models. Local Whisper uses the settings above. Use documented provider fields for vocabulary hints or diarization. OpenRouter chooses the provider; options apply only to the matching route. <a href="https://openrouter.ai/docs/guides/overview/multimodal/stt#provider-specific-options" target="_blank" rel="noreferrer">View supported settings</a></p>
            </details>
          </section>
          <div className="start-bar"><div><strong>{selectedModels.length} {selectedModels.length === 1 ? 'model' : 'models'} selected</strong><span>{needsKey ? 'Add your OpenRouter key for the selected hosted models.' : !chunkSize.success ? 'Choose a valid chunk size to start.' : selectedRecording ? `${chunkSize.data}s chunk target · ${selectedModels.some(id => MODELS.find(model => model.id === id)?.provider === 'openrouter') ? 'hosted calls use OpenRouter credits' : 'runs on this computer'}` : 'Choose a recording to start.'}</span></div><button className="primary-button" disabled={needsKey || !selectedRecording || !selectedModels.length || !chunkSize.success || uploading || starting} onClick={() => void start()}><AudioLines size={17} />{starting ? 'Preparing run…' : `Run ${selectedModels.length} ${selectedModels.length === 1 ? 'model' : 'models'}`}<ChevronRight size={16} /></button></div>
          {needsKey && <button className="setup-prompt" onClick={() => setShowSetup(true)}>Set up your API key <ArrowUpRight size={14} /></button>}
        </>}

        {runId && !run && <div className="panel muted">Loading saved comparison…</div>}
        {run && <>
          <section className="run-summary"><div><span className="eyebrow">SAVED COMPARISON</span><h2>{run.recording.name}</h2><p>{date(run.createdAt)} · {duration(run.recording.duration)} audio · {run.models.length} {run.models.length === 1 ? 'model' : 'models'} · {statusLabel(run)}</p></div><div className="run-actions"><button className="secondary-button" onClick={repeat}><RefreshCw size={15} />Run again</button><a className="secondary-button" href={`/api/runs/${run.id}/export`}><ArrowDownToLine size={15} />Export JSON</a></div></section>
          <div className="audio-player"><FileAudio size={18} /><div><strong>Listen & compare</strong><small>Original recording · {run.chunkCount} {run.chunkCount === 1 ? 'chunk' : 'chunks'} per model</small></div><audio key={run.recording.id} ref={player} controls preload="metadata" src={`/api/recordings/${run.recording.id}/audio`} /></div>
          <details className="run-settings"><summary>Settings used for this run</summary><p>Chunk target: {run.options.chunkSeconds}s · maximum: {chunkWindow(run.options.chunkSeconds).max}s · split near pauses · no overlap</p><p>Language: {run.options.language} · Temperature: {run.options.temperature} · Timestamps: {run.options.timestamps ? 'requested' : 'off'}</p><p className="saved-context">Transcription context: {run.options.contextPrompt || 'None'}</p>{run.options.vocabulary && <p>Vocabulary: {run.options.vocabulary}</p>}<pre>{JSON.stringify(run.options.providerOptions, null, 2)}</pre><p className="muted text-xs">Audio SHA-256: {run.recording.sha256}</p></details>
          <div className="results-title"><h2>Full transcripts</h2><span>{run.results.filter(r => r.status === 'completed').length} / {run.results.length} completed · saved after each chunk</span></div>
          <div className="results-grid">{run.results.map(result => <ResultCard key={result.id} result={result} chunkSeconds={run.options.chunkSeconds} seek={seconds => { if (player.current) { player.current.currentTime = seconds; void player.current.play().catch(() => {}); } }} />)}</div>
          <p className="run-footnote">API time includes network time. Local time includes model loading on the first chunk; inference time and device are saved in raw responses. Local runs have no API charge. Hosted costs can be incomplete for failed requests. Full model text is preserved; blank lines mark chunk boundaries.</p>
        </>}
        <footer className="page-footer"><span>Speechbench · Local recordings & saved results</span><a href="https://openrouter.ai/docs/guides/overview/multimodal/stt" target="_blank" rel="noreferrer">OpenRouter transcription docs <ArrowUpRight size={12} /></a></footer>
      </div>
    </main>
  </div>;
}
