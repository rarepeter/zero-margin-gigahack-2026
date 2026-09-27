// TypeScript mirror of openapi/mom.schema.json — the contract between the text service and the UI.
export type Lang = 'ro' | 'ru' | 'en' | 'mixed';
export type MeetingType = 'medical' | 'patient_case' | 'financial' | 'administrative' | 'executive' | 'operational' | 'crisis' | 'other';
export type FlagType = 'number' | 'decision_status' | 'owner' | 'deadline' | 'term';

/** `segment_id` is the stable transcript reference. `segment` remains only for old saved fixtures. */
export interface Evidence { quote: string; lang: Lang; segment_id?: string; segment?: number; t?: string | null; speaker?: string | null }
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

export const fmtDate = (iso: string | null | undefined) => {
  if (!iso) return '';
  const [y, m, d] = iso.split('-');
  return d && m && y ? `${d}.${m}.${y}` : iso;
};
