// TypeScript mirror of openapi/mom.schema.json — the contract between the text service and the UI.
export type Lang = 'ro' | 'ru' | 'en' | 'mixed';
export type MeetingType = 'medical' | 'patient_case' | 'financial' | 'administrative' | 'executive' | 'operational' | 'crisis' | 'other';
export type FlagType = 'number' | 'decision_status' | 'owner' | 'deadline' | 'term';

export interface Evidence { quote: string; lang: Lang; segment: number; t?: string | null; speaker?: string | null }
export interface Flag { type: FlagType; reason: string; blocking: boolean; candidates?: string[] }
export interface Decision { id: string; text: string; status: 'decided' | 'proposed' | 'revoked'; revised_in_meeting?: boolean; evidence: Evidence; flags: Flag[] }
export interface Action { id: string; text: string; decision_ids?: string[]; owner: string | null; deadline: { spoken: string | null; resolved: string | null }; evidence: Evidence; flags: Flag[] }
export interface Finding { text: string; source_stated?: string | null; evidence: Evidence; flags: Flag[] }
export interface Topic { title: string; text: string }
export interface Risk { text: string; category?: string; raised_by?: string | null; evidence?: Evidence }
export interface OpenQuestion { text: string; raised_by?: string | null; evidence?: Evidence }
export interface Participant { name: string; role?: string | null; role_stated?: boolean }

export interface Mom {
  header: {
    subject: string;
    meeting_type: MeetingType;
    meeting_type_confidence: 'high' | 'medium' | 'low';
    date: string;
    date_source: 'recording' | 'upload';
    duration_min?: number;
    languages?: Partial<Record<'ro' | 'ru' | 'en', number>>;
    participants_mentioned?: Participant[];
    also_discussed?: MeetingType[];
  };
  summary: string;
  decisions: Decision[];
  actions: Action[];
  findings: Finding[];
  topics: Topic[];
  risks: Risk[];
  open_questions: OpenQuestion[];
  patients?: { reference: string; findings?: string[]; decision_ids: string[]; plan?: string | null }[];
}

/** Light runtime guard — the backend owns validation; this only protects the UI from rendering garbage. */
export function parseMom(raw: unknown): Mom {
  const m = raw as Partial<Mom> | null;
  if (!m || typeof m !== 'object' || !m.header || typeof m.summary !== 'string') {
    throw new Error('MoM JSON does not match mom.schema.json (missing header/summary).');
  }
  return {
    ...(m as Mom),
    decisions: m.decisions ?? [],
    actions: m.actions ?? [],
    findings: m.findings ?? [],
    topics: m.topics ?? [],
    risks: m.risks ?? [],
    open_questions: m.open_questions ?? [],
  };
}

/* ---------- Review items (a.k.a. "red words") ---------- */

/** One uncertain value the doctor must confirm. `id` is stable: `<section>.<index>.<flagIndex>`. */
export interface Issue {
  id: string;
  kind: FlagType;
  reason: string;
  blocking: boolean;
  candidates: string[];
  /** The value currently shown in red (what the model proposed). */
  proposed: string;
  evidence: Evidence;
}

export type Resolutions = Record<string, string>;

export const fmtDate = (iso: string | null | undefined) => {
  if (!iso) return '';
  const [y, m, d] = iso.split('-');
  return d && m && y ? `${d}.${m}.${y}` : iso;
};

export function collectIssues(mom: Mom): Issue[] {
  const out: Issue[] = [];
  mom.decisions.forEach((d, i) =>
    d.flags.forEach((f, k) =>
      out.push({ id: `decisions.${i}.${k}`, kind: f.type, reason: f.reason, blocking: f.blocking, candidates: f.candidates ?? [], proposed: d.status, evidence: d.evidence }),
    ),
  );
  mom.actions.forEach((a, i) =>
    a.flags.forEach((f, k) =>
      out.push({
        id: `actions.${i}.${k}`, kind: f.type, reason: f.reason, blocking: f.blocking, candidates: f.candidates ?? [], evidence: a.evidence,
        proposed: f.type === 'owner' ? a.owner ?? '' : f.type === 'deadline' ? a.deadline.resolved ?? a.deadline.spoken ?? '' : f.candidates?.[0] ?? '',
      }),
    ),
  );
  mom.findings.forEach((x, i) =>
    x.flags.forEach((f, k) =>
      out.push({ id: `findings.${i}.${k}`, kind: f.type, reason: f.reason, blocking: f.blocking, candidates: f.candidates ?? [], evidence: x.evidence, proposed: (f.candidates ?? []).find((c) => x.text.includes(c)) ?? f.candidates?.[0] ?? '' }),
    ),
  );
  return out;
}

export const blockingLeft = (issues: Issue[], res: Resolutions) => issues.filter((i) => i.blocking && !(i.id in res)).length;

/**
 * Returns the reviewed MoM: resolved values written back, resolved flags removed.
 * This is what gets exported / sent to the backend.
 */
export function applyResolutions(mom: Mom, issues: Issue[], res: Resolutions): Mom {
  const out: Mom = structuredClone(mom);
  const drop: Record<string, Set<number>> = {};
  for (const is of issues) {
    const v = res[is.id];
    if (v === undefined) continue;
    const [sec, iStr, kStr] = is.id.split('.');
    const i = Number(iStr);
    (drop[`${sec}.${i}`] ??= new Set()).add(Number(kStr));
    if (sec === 'decisions') {
      const d = out.decisions[i];
      if (v === 'decided' || v === 'proposed' || v === 'revoked') d.status = v;
    } else if (sec === 'actions') {
      const a = out.actions[i];
      if (is.kind === 'owner') a.owner = v || null;
      else if (is.kind === 'deadline') a.deadline.resolved = /^\d{4}-\d{2}-\d{2}$/.test(v) ? v : a.deadline.resolved;
      else if (is.proposed) a.text = a.text.replace(is.proposed, v);
    } else if (sec === 'findings') {
      const f = out.findings[i];
      f.text = is.proposed && f.text.includes(is.proposed) ? f.text.replace(is.proposed, v) : f.text;
    }
  }
  for (const [key, ks] of Object.entries(drop)) {
    const [sec, iStr] = key.split('.');
    const item = (out as unknown as Record<string, { flags: Flag[] }[]>)[sec][Number(iStr)];
    item.flags = item.flags.filter((_, k) => !ks.has(k));
  }
  return out;
}
