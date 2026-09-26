import type { TranscriptionResult } from '../api';

/** Portal projection of one structured transcription.v1alpha1 segment. */
export interface Segment {
  id: string;
  index: number;
  startMs: number;
  endMs: number | null;
  speakerId: string | null;
  speaker: string | null;
  languages: string[];
  lang: string | null;
  text: string;
  confidence: number | null;
  t: string;
}

export function timestampFromMs(milliseconds: number): string {
  const totalSeconds = Math.floor(milliseconds / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return [hours, minutes, seconds].map((value) => String(value).padStart(2, '0')).join(':');
}

/** Map the backend contract to display fields without inventing speaker identities. */
export function segmentsFromTranscription(result: TranscriptionResult): Segment[] {
  const speakerNames = new Map(
    result.speakers.map((speaker) => [speaker.id, speaker.displayName ?? speaker.id]),
  );
  return result.transcript.segments.map((segment, index) => ({
    id: segment.id,
    index,
    startMs: segment.startMs,
    endMs: segment.endMs,
    speakerId: segment.speakerId,
    speaker: segment.speakerId ? speakerNames.get(segment.speakerId) ?? segment.speakerId : null,
    languages: [...segment.languages],
    lang: segment.languages.length ? segment.languages.map((language) => language.toUpperCase()).join(' · ') : null,
    text: segment.text,
    confidence: segment.confidence,
    t: timestampFromMs(segment.startMs),
  }));
}

/** Share of spoken characters per speaker — used for the participants list. */
export function speakingShare(segs: Segment[]): { name: string; share: number; langs: string[] }[] {
  const total = segs.reduce((n, s) => n + s.text.length, 0) || 1;
  const by = new Map<string, { chars: number; langs: Set<string> }>();
  for (const s of segs) {
    if (!s.speaker) continue;
    for (const name of s.speaker.split('/').map((x) => x.trim())) {
      const e = by.get(name) ?? { chars: 0, langs: new Set<string>() };
      e.chars += s.text.length;
      s.lang?.split('·').forEach((l) => e.langs.add(l.trim()));
      by.set(name, e);
    }
  }
  return [...by.entries()]
    .map(([name, e]) => ({ name, share: Math.round((e.chars / total) * 100), langs: [...e.langs] }))
    .sort((a, b) => b.share - a.share);
}

export const initials = (name: string) => {
  const w = name.split(/[\s/]+/).filter((x) => /^[A-ZĂÎÂȘȚА-Я]/.test(x) && !/^dr\.?$/i.test(x));
  return w.map((x) => x[0]).join('').slice(0, 2) || '?';
};
