// Single app store (useReducer + context). One page, so no router.
import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, type ReactNode } from 'react';
import { api, API_MODE, ApiError, type JobStatus, type JobStatusResponse, type ParticipantAssignment, type ReviewContextResponse } from '../api';
import { parseMom, type Mom } from '../domain/mom';
import { segmentsFromTranscription, type Segment } from '../domain/transcript';
import { type Person } from '../data/directory';
import { DICT, type Dict, type LangCode } from '../i18n';
import { jobQueryPath, reviewEntryDecision, reviewJobIdFromSearch } from '../lib/reviewRoute';

export type Screen = 'upload' | 'recording' | 'processing' | 'restoring-review' | 'failed' | 'review' | 'done';
export type Outcome = 'download' | 'sent' | 'discard';
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
  errorRetryable: boolean;
  segments: Segment[];
  mom: Mom | null;
  reviewContext: ReviewContextResponse | null;
  edits: Edits;
  reviewEditing: boolean;
  participantEditing: boolean;
  approvalLocked: boolean;
  recipients: Person[];
  deliveredRecipientCount: number;
  portalSecs: number;
  portalOpenedAt: number;
  outcome: Outcome | null;
  exported: Mom | null;
  toast: string | null;
}

const initial = (lang: LangCode, openedAt = Date.now()): State => ({
  lang, screen: 'upload', serverOnline: null, jobId: null, fileName: null, job: null, seen: {}, uploadedAt: null, readyAt: null,
  error: null, errorRetryable: false, segments: [], mom: null, reviewContext: null, edits: {}, reviewEditing: false, participantEditing: false, approvalLocked: false, recipients: [], deliveredRecipientCount: 0, portalSecs: 0,
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
  | { type: 'failed'; error: string; retryable?: boolean }
  | { type: 'edits'; edits: Edits }
  | { type: 'reviewEditing'; editing: boolean }
  | { type: 'participantEditing'; editing: boolean }
  | { type: 'approvalLocked' }
  | { type: 'recipients'; recipients: Person[] }
  | { type: 'participantNames'; assignments: ParticipantAssignment[] }
  | { type: 'done'; outcome: Outcome; exported: Mom | null; deliveredRecipientCount?: number; clickedAt?: number }
  | { type: 'restored'; jobId: string; exported: Mom; reviewContext: ReviewContextResponse | null; elapsedSecs: number; deliveredRecipientCount: number }
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
      return { ...s, screen: 'review', mom: a.mom, segments: a.segments, reviewContext: a.reviewContext, readyAt: Date.now(), edits: {}, reviewEditing: false, participantEditing: false, approvalLocked: false, recipients: [] };
    }
    case 'failed': return { ...s, screen: 'failed', error: a.error, errorRetryable: a.retryable ?? false };
    case 'edits': return { ...s, edits: a.edits };
    case 'reviewEditing': return { ...s, reviewEditing: a.editing };
    case 'participantEditing': return { ...s, participantEditing: a.editing };
    case 'approvalLocked': return { ...s, reviewEditing: false, participantEditing: false, approvalLocked: true };
    case 'recipients': return { ...s, recipients: a.recipients };
    case 'participantNames': {
      const names = new Map(a.assignments.map((item) => [item.speakerId, item.displayName]));
      const speakers = s.reviewContext?.speakers.map((speaker) => ({ ...speaker, displayName: names.get(speaker.id) ?? speaker.displayName }));
      return {
        ...s,
        segments: s.segments.map((segment) => ({ ...segment, speaker: segment.speakerId ? names.get(segment.speakerId) ?? segment.speaker : segment.speaker })),
        reviewContext: s.reviewContext && speakers ? {
          ...s.reviewContext,
          speakers,
          meetingMetadata: {
            ...s.reviewContext.meetingMetadata,
            namedSpeakerCount: speakers.filter((speaker) => speaker.displayName).length,
          },
        } : s.reviewContext,
      };
    }
    case 'done': return { ...s, screen: 'done', outcome: a.outcome, exported: a.exported, deliveredRecipientCount: a.deliveredRecipientCount ?? 0, portalSecs: a.clickedAt ? Math.max(0, Math.round((a.clickedAt - s.portalOpenedAt) / 1000)) : 0 };
    case 'restored': return { ...s, screen: 'done', jobId: a.jobId, outcome: a.deliveredRecipientCount ? 'sent' : 'download', exported: a.exported, reviewContext: a.reviewContext, deliveredRecipientCount: a.deliveredRecipientCount, portalSecs: a.elapsedSecs };
    case 'toast': return { ...s, toast: a.msg };
    case 'reset': return { ...initial(s.lang, Date.now()), serverOnline: s.serverOnline };
  }
}

const LANG_KEY = 'smom-lang';
const savedLang = (): LangCode => {
  try { const v = localStorage.getItem(LANG_KEY); return v === 'ru' || v === 'en' ? v : 'ro'; } catch { return 'ro'; }
};

const initialFromLocation = (): State => {
  const state = initial(savedLang());
  const jobId = typeof window === 'undefined' ? null : reviewJobIdFromSearch(window.location.search);
  return jobId
    ? { ...state, screen: 'restoring-review', jobId }
    : state;
};

function replaceJobQuery(name: 'review' | 'approved', jobId: string): void {
  history.replaceState(null, '', jobQueryPath(window.location.href, name, jobId));
}

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
  /** MoM with edits applied (what the doctor sees). */
  view: Mom | null;
  setLang(lang: LangCode): void;
  upload(file: Blob, name: string): Promise<void>;
  retry(): Promise<void>;
  saveEdits(edits: Edits): void;
  setReviewEditing(editing: boolean): void;
  setParticipantEditing(editing: boolean): void;
  setRecipients(p: Person[]): void;
  saveParticipantNames(assignments: ParticipantAssignment[]): Promise<void>;
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
  const [s, dispatch] = useReducer(reducer, undefined, initialFromLocation);
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
    const params = new URLSearchParams(location.search);
    if (API_MODE === 'mock' && params.get('demo') === 'review' && !params.has('approved') && !params.has('review')) {
      dispatch({ type: 'uploaded', jobId: 'demo', fileName: 'Medpark_audio.m4a' });
    }
  }, []);

  useEffect(() => {
    const jobId = new URLSearchParams(location.search).get('approved');
    if (!jobId) return;
    let alive = true;
    Promise.all([api.getApprovedMom(jobId), api.getReviewContext(jobId).catch(() => null), api.getJob(jobId)])
      .then(([approved, reviewContext, job]) => {
        if (!alive) return;
        if (job.status !== 'COMPLETED') throw new Error('Approval delivery is not complete.');
        let elapsedSecs = 0;
        try { elapsedSecs = Number(sessionStorage.getItem(`smom-elapsed-${jobId}`)) || 0; } catch { /* private mode */ }
        dispatch({ type: 'restored', jobId, exported: parseMom(approved.document), reviewContext, elapsedSecs, deliveredRecipientCount: approved.recipients.length });
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

  // Job polling while processing or restoring a stable review link.
  useEffect(() => {
    if ((s.screen !== 'processing' && s.screen !== 'restoring-review') || !s.jobId) return;
    const jobId = s.jobId;
    const restoring = s.screen === 'restoring-review';
    let alive = true;
    let gotTranscript = false;
    const tick = async () => {
      try {
        const job = await api.getJob(jobId);
        if (!alive) return;
        dispatch({ type: 'job', job });
        const entry = reviewEntryDecision(job);
        if (entry === 'approved') {
          const [approved, reviewContext] = await Promise.all([
            api.getApprovedMom(jobId),
            api.getReviewContext(jobId).catch(() => null),
          ]);
          if (!alive) return;
          let elapsedSecs = 0;
          try { elapsedSecs = Number(sessionStorage.getItem(`smom-elapsed-${jobId}`)) || 0; } catch { /* private mode */ }
          try { replaceJobQuery('approved', jobId); } catch { /* history is optional */ }
          dispatch({ type: 'restored', jobId, exported: parseMom(approved.document), reviewContext, elapsedSecs, deliveredRecipientCount: approved.recipients.length });
          return;
        }
        if (entry === 'failed') {
          dispatch({
            type: 'failed',
            error: job.error?.message ?? job.stage,
            retryable: job.stage !== 'delivery_failed' && (job.error?.retryable ?? false),
          });
          return;
        }
        if (job.artifacts.transcriptAvailable && !gotTranscript) {
          gotTranscript = true;
          api.getTranscript(jobId).then((transcription) => alive && dispatch({ type: 'segments', segments: segmentsFromTranscription(transcription) })).catch(() => { gotTranscript = false; });
        }
        if (entry === 'review') {
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
        if (e instanceof ApiError && e.status === 404) { dispatch({ type: 'failed', error: e.message, retryable: false }); return; }
        if (restoring && e instanceof ApiError) { dispatch({ type: 'failed', error: e.message, retryable: e.retryable }); return; }
        // Network blip: keep polling.
      }
      if (alive) timer = window.setTimeout(tick, POLL_MS);
    };
    let timer = window.setTimeout(tick, 300);
    return () => { alive = false; window.clearTimeout(timer); };
  }, [s.screen, s.jobId]);

  const view = useMemo(() => (s.mom ? applyEdits(s.mom, s.edits) : null), [s.mom, s.edits]);

  const ctx: Ctx = {
    s, l, view,
    setLang: (lang) => dispatch({ type: 'lang', lang }),
    go: (screen) => dispatch({ type: 'screen', screen }),
    toast,
    async upload(file, name) {
      const job = await api.createJob(file, name);
      try { replaceJobQuery('review', job.jobId); } catch { /* history is optional */ }
      dispatch({ type: 'uploaded', jobId: job.jobId, fileName: name });
    },
    async retry() {
      if (!s.jobId) return;
      await api.retryJob(s.jobId);
      dispatch({ type: 'screen', screen: 'processing' });
    },
    saveEdits(edits) {
      dispatch({ type: 'edits', edits });
      toast(l.ed_toast);
    },
    setReviewEditing: (editing) => dispatch({ type: 'reviewEditing', editing }),
    setParticipantEditing: (editing) => dispatch({ type: 'participantEditing', editing }),
    setRecipients: (recipients) => dispatch({ type: 'recipients', recipients }),
    async saveParticipantNames(assignments) {
      if (!s.jobId || s.approvalLocked) return;
      try {
        const saved = await api.saveParticipantAssignments(s.jobId, assignments);
        dispatch({ type: 'participantNames', assignments: saved.assignments });
        toast(l.part_saved);
      } catch (error) {
        toast(error instanceof Error ? error.message : l.part_save_error);
        throw error;
      }
    },
    async exportMom() {
      if (!s.jobId || !view || s.reviewEditing || s.participantEditing) return;
      const clickedAt = Date.now();
      try {
        const approved = await api.approveMom(s.jobId, view, s.recipients.map((p) => p.email));
        const elapsedSecs = Math.max(0, Math.round((clickedAt - s.portalOpenedAt) / 1000));
        try {
          sessionStorage.setItem(`smom-elapsed-${s.jobId}`, String(elapsedSecs));
          replaceJobQuery('approved', s.jobId);
        } catch { /* storage and history are optional for this session */ }
        if (approved.skippedRecipients.length) toast(l.rc_skipped(approved.skippedRecipients.length));
        dispatch({ type: 'done', outcome: approved.recipients.length ? 'sent' : 'download', exported: parseMom(approved.document), deliveredRecipientCount: approved.recipients.length, clickedAt });
      } catch (e) {
        if (e instanceof ApiError && e.code === 'LOCAL_SMTP_FAILED') dispatch({ type: 'approvalLocked' });
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
