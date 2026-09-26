// Single app store (useReducer + context). One page, so no router.
import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, type ReactNode } from 'react';
import { api, API_MODE, ApiError, type JobStatus, type JobStatusResponse, type ReviewContextResponse } from '../api';
import { applyResolutions, blockingLeft, collectIssues, parseMom, type Issue, type Mom, type Resolutions } from '../domain/mom';
import { segmentsFromTranscription, type Segment } from '../domain/transcript';
import { type Person } from '../data/directory';
import { DICT, type Dict, type LangCode } from '../i18n';

export type Screen = 'upload' | 'recording' | 'processing' | 'failed' | 'review' | 'done';
export type Outcome = 'download' | 'discard';
/** Text edits made in Edit mode, keyed by path, e.g. `summary`, `decisions.0.text`. */
export type Edits = Record<string, string>;

export interface State {
  lang: LangCode;
  screen: Screen;
  serverOnline: boolean | null;
  jobId: string | null;
  fileName: string | null;
  job: JobStatusResponse | null;
  /** First time (ms) each status was observed — used for step durations. */
  seen: Partial<Record<JobStatus, number>>;
  uploadedAt: number | null;
  readyAt: number | null;
  error: string | null;
  segments: Segment[];
  mom: Mom | null;
  reviewContext: ReviewContextResponse | null;
  res: Resolutions;
  edits: Edits;
  reviewEditing: boolean;
  recipients: Person[];
  portalSecs: number;
  portalOpenedAt: number;
  outcome: Outcome | null;
  exported: Mom | null;
  toast: string | null;
}

const initial = (lang: LangCode, openedAt = Date.now()): State => ({
  lang, screen: 'upload', serverOnline: null, jobId: null, fileName: null, job: null, seen: {}, uploadedAt: null, readyAt: null,
  error: null, segments: [], mom: null, reviewContext: null, res: {}, edits: {}, reviewEditing: false, recipients: [], portalSecs: 0,
  portalOpenedAt: openedAt, outcome: null, exported: null, toast: null,
});

type Act =
  | { type: 'lang'; lang: LangCode }
  | { type: 'screen'; screen: Screen }
  | { type: 'server'; online: boolean }
  | { type: 'uploaded'; jobId: string; fileName: string }
  | { type: 'job'; job: JobStatusResponse }
  | { type: 'segments'; segments: Segment[] }
  | { type: 'ready'; mom: Mom; segments: Segment[]; reviewContext: ReviewContextResponse }
  | { type: 'failed'; error: string }
  | { type: 'resolve'; id: string; value: string }
  | { type: 'edits'; edits: Edits; autoResolve: string[] }
  | { type: 'reviewEditing'; editing: boolean }
  | { type: 'recipients'; recipients: Person[] }
  | { type: 'done'; outcome: Outcome; exported: Mom | null; clickedAt?: number }
  | { type: 'restored'; jobId: string; exported: Mom; reviewContext: ReviewContextResponse | null; elapsedSecs: number }
  | { type: 'toast'; msg: string | null }
  | { type: 'reset' };

function reducer(s: State, a: Act): State {
  switch (a.type) {
    case 'lang': return { ...s, lang: a.lang };
    case 'screen': return { ...s, screen: a.screen };
    case 'server': return { ...s, serverOnline: a.online };
    case 'uploaded': return { ...initial(s.lang, s.portalOpenedAt), serverOnline: s.serverOnline, screen: 'processing', jobId: a.jobId, fileName: a.fileName, uploadedAt: Date.now(), seen: { QUEUED: Date.now() } };
    case 'job': return { ...s, job: a.job, seen: s.seen[a.job.status] ? s.seen : { ...s.seen, [a.job.status]: Date.now() } };
    case 'segments': return { ...s, segments: a.segments };
    case 'ready': {
      return { ...s, screen: 'review', mom: a.mom, segments: a.segments, reviewContext: a.reviewContext, readyAt: Date.now(), res: {}, edits: {}, recipients: [] };
    }
    case 'failed': return { ...s, screen: 'failed', error: a.error };
    case 'resolve': return { ...s, res: { ...s.res, [a.id]: a.value } };
    case 'edits': {
      const res = { ...s.res };
      a.autoResolve.forEach((id) => { if (!(id in res)) res[id] = EDITED; });
      return { ...s, edits: a.edits, res };
    }
    case 'reviewEditing': return { ...s, reviewEditing: a.editing };
    case 'recipients': return { ...s, recipients: a.recipients };
    case 'done': return { ...s, screen: 'done', outcome: a.outcome, exported: a.exported, portalSecs: a.clickedAt ? Math.max(0, Math.round((a.clickedAt - s.portalOpenedAt) / 1000)) : 0 };
    case 'restored': return { ...s, screen: 'done', jobId: a.jobId, outcome: 'download', exported: a.exported, reviewContext: a.reviewContext, portalSecs: a.elapsedSecs };
    case 'toast': return { ...s, toast: a.msg };
    case 'reset': return { ...initial(s.lang, Date.now()), serverOnline: s.serverOnline };
  }
}

/** Resolution value used when the doctor rewrote the flagged sentence by hand in Edit mode. */
export const EDITED = '__edited__';

const LANG_KEY = 'smom-lang';
const savedLang = (): LangCode => {
  try { const v = localStorage.getItem(LANG_KEY); return v === 'ru' || v === 'en' ? v : 'ro'; } catch { return 'ro'; }
};

/** Writes Edit-mode text overrides into a MoM copy. */
export function applyEdits(mom: Mom, edits: Edits): Mom {
  if (!Object.keys(edits).length) return mom;
  const out = structuredClone(mom) as unknown as Record<string, unknown>;
  for (const [path, v] of Object.entries(edits)) {
    const parts = path.split('.');
    let o = out as Record<string, unknown>;
    for (let i = 0; i < parts.length - 1; i++) o = o[parts[i]] as Record<string, unknown>;
    o[parts[parts.length - 1]] = v;
  }
  return out as unknown as Mom;
}

interface Ctx {
  s: State;
  l: Dict;
  issues: Issue[];
  left: number;
  /** MoM with edits applied (what the doctor sees). */
  view: Mom | null;
  setLang(lang: LangCode): void;
  upload(file: Blob, name: string): Promise<void>;
  retry(): Promise<void>;
  resolve(id: string, value: string): void;
  saveEdits(edits: Edits): void;
  setReviewEditing(editing: boolean): void;
  setRecipients(p: Person[]): void;
  exportMom(): Promise<void>;
  discard(): Promise<void>;
  newMeeting(): void;
  toast(msg: string): void;
  go(screen: Screen): void;
}

const C = createContext<Ctx | null>(null);
export const useApp = () => {
  const c = useContext(C);
  if (!c) throw new Error('useApp outside <AppProvider>');
  return c;
};

const POLL_MS = 2000;
const HEALTH_MS = 15000;

export function AppProvider({ children }: { children: ReactNode }) {
  const [s, dispatch] = useReducer(reducer, undefined, () => initial(savedLang()));
  const l = DICT[s.lang];
  const toastTimer = useRef<number | undefined>(undefined);

  const toast = useCallback((msg: string) => {
    dispatch({ type: 'toast', msg });
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => dispatch({ type: 'toast', msg: null }), 2600);
  }, []);

  // Language: persist + <html lang>
  useEffect(() => {
    document.documentElement.lang = s.lang;
    try { localStorage.setItem(LANG_KEY, s.lang); } catch { /* private mode */ }
  }, [s.lang]);

  // Dev shortcut (mock mode only): ?demo=review opens the review screen with the example data.
  useEffect(() => {
    if (API_MODE === 'mock' && new URLSearchParams(location.search).get('demo') === 'review' && !new URLSearchParams(location.search).has('approved')) {
      dispatch({ type: 'uploaded', jobId: 'demo', fileName: 'Medpark_audio.m4a' });
    }
  }, []);

  useEffect(() => {
    const jobId = new URLSearchParams(location.search).get('approved');
    if (!jobId) return;
    let alive = true;
    Promise.all([api.getApprovedMom(jobId), api.getReviewContext(jobId).catch(() => null)])
      .then(([approved, reviewContext]) => {
        if (!alive) return;
        let elapsedSecs = 0;
        try { elapsedSecs = Number(sessionStorage.getItem(`smom-elapsed-${jobId}`)) || 0; } catch { /* private mode */ }
        dispatch({ type: 'restored', jobId, exported: parseMom(approved.document), reviewContext, elapsedSecs });
      })
      .catch(() => { if (alive) toast('Could not load the approved minutes.'); });
    return () => { alive = false; };
  }, [toast]);

  // Local server health → sidebar "Local server: Online/Offline"
  useEffect(() => {
    let alive = true;
    const check = async () => { const ok = await api.health(); if (alive) dispatch({ type: 'server', online: ok }); };
    check();
    const t = window.setInterval(check, HEALTH_MS);
    return () => { alive = false; window.clearInterval(t); };
  }, []);

  // Job polling while processing
  useEffect(() => {
    if (s.screen !== 'processing' || !s.jobId) return;
    const jobId = s.jobId;
    let alive = true;
    let gotTranscript = false;
    const tick = async () => {
      try {
        const job = await api.getJob(jobId);
        if (!alive) return;
        dispatch({ type: 'job', job });
        if (job.status === 'FAILED') {
          dispatch({ type: 'failed', error: job.error?.message ?? job.stage });
          return;
        }
        if (job.artifacts.transcriptAvailable && !gotTranscript) {
          gotTranscript = true;
          api.getTranscript(jobId).then((transcription) => alive && dispatch({ type: 'segments', segments: segmentsFromTranscription(transcription) })).catch(() => { gotTranscript = false; });
        }
        if (job.status === 'AWAITING_REVIEW' && job.artifacts.momAvailable && job.artifacts.reviewContextAvailable) {
          const [momResult, transcription, reviewContext] = await Promise.all([
            api.getMom(jobId),
            api.getTranscript(jobId),
            api.getReviewContext(jobId),
          ]);
          if (!alive) return;
          dispatch({
            type: 'ready',
            mom: parseMom(momResult.document),
            segments: segmentsFromTranscription(transcription),
            reviewContext,
          });
          return;
        }
      } catch (e) {
        if (!alive) return;
        if (e instanceof ApiError && e.status === 404) { dispatch({ type: 'failed', error: e.message }); return; }
        // Network blip: keep polling.
      }
      if (alive) timer = window.setTimeout(tick, POLL_MS);
    };
    let timer = window.setTimeout(tick, 300);
    return () => { alive = false; window.clearTimeout(timer); };
  }, [s.screen, s.jobId]);

  const issues = useMemo(() => (s.mom ? collectIssues(s.mom) : []), [s.mom]);
  const view = useMemo(() => (s.mom ? applyEdits(s.mom, s.edits) : null), [s.mom, s.edits]);
  const left = blockingLeft(issues, s.res);

  const ctx: Ctx = {
    s, l, issues, left, view,
    setLang: (lang) => dispatch({ type: 'lang', lang }),
    go: (screen) => dispatch({ type: 'screen', screen }),
    toast,
    async upload(file, name) {
      const job = await api.createJob(file, name);
      dispatch({ type: 'uploaded', jobId: job.jobId, fileName: name });
    },
    async retry() {
      if (!s.jobId) return;
      await api.retryJob(s.jobId);
      dispatch({ type: 'screen', screen: 'processing' });
    },
    resolve: (id, value) => { dispatch({ type: 'resolve', id, value }); toast(l.ed_toast); },
    saveEdits(edits) {
      // A flagged finding whose text was rewritten by hand no longer contains the red value → treat as resolved.
      const auto = issues.filter((i) => i.id.startsWith('findings.') && edits[`findings.${i.id.split('.')[1]}.text`] !== undefined && !edits[`findings.${i.id.split('.')[1]}.text`].includes(i.proposed)).map((i) => i.id);
      dispatch({ type: 'edits', edits, autoResolve: auto });
      toast(l.ed_toast);
    },
    setReviewEditing: (editing) => dispatch({ type: 'reviewEditing', editing }),
    setRecipients: (recipients) => dispatch({ type: 'recipients', recipients }),
    async exportMom() {
      if (!s.jobId || !view || left || s.reviewEditing) return;
      const clickedAt = Date.now();
      const reviewed = applyResolutions(view, issues, Object.fromEntries(Object.entries(s.res).filter(([, v]) => v !== EDITED)));
      try {
        const approved = await api.approveMom(s.jobId, reviewed, s.recipients.map((p) => p.email));
        const elapsedSecs = Math.max(0, Math.round((clickedAt - s.portalOpenedAt) / 1000));
        try {
          sessionStorage.setItem(`smom-elapsed-${s.jobId}`, String(elapsedSecs));
          history.replaceState(null, '', `?approved=${encodeURIComponent(s.jobId)}`);
        } catch { /* storage and history are optional for this session */ }
        dispatch({ type: 'done', outcome: 'download', exported: parseMom(approved.document), clickedAt });
      } catch (e) {
        toast(e instanceof Error ? e.message : 'Approval failed. Please try again.');
      }
    },
    async discard() {
      dispatch({ type: 'done', outcome: 'discard', exported: null });
      toast(l.discarded);
    },
    newMeeting: () => {
      try {
        history.replaceState(null, '', location.pathname);
      } catch { /* history is optional */ }
      dispatch({ type: 'reset' });
    },
  };

  return <C.Provider value={ctx}>{children}</C.Provider>;
}
