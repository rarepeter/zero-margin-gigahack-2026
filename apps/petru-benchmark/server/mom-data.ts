import { readdirSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { momTranscriptSchema, type MomTranscript, type MomTranscriptSummary } from '../shared/mom';

export const MOM_DATA_DIR = resolve(import.meta.dir, '../mom/transcripts');

// Reads and validates every fictional transcript. Throws with the file name on the first problem.
export function loadTranscripts(dir = MOM_DATA_DIR): MomTranscript[] {
  const transcripts = readdirSync(dir).filter(name => name.endsWith('.json')).sort().map(name => {
    const parsed = momTranscriptSchema.safeParse(JSON.parse(readFileSync(join(dir, name), 'utf8')));
    if (!parsed.success) throw new Error(`${name}: ${parsed.error.issues.map(i => `${i.path.join('.')}: ${i.message}`).join('; ')}`);
    const transcript = parsed.data;
    if (`${transcript.id}.json` !== name) throw new Error(`${name}: id must match the file name.`);
    const ids = [...transcript.answerKey.items, ...transcript.answerKey.traps].map(item => item.id);
    if (new Set(ids).size !== ids.length) throw new Error(`${name}: answer key IDs must be unique.`);
    return transcript;
  });
  if (!transcripts.length) throw new Error(`No transcripts found in ${dir}.`);
  return transcripts;
}

export function summarize(transcript: MomTranscript): MomTranscriptSummary {
  return {
    id: transcript.id, meetingType: transcript.meetingType, title: transcript.title, scenario: transcript.scenario,
    words: transcript.transcript.trim().split(/\s+/u).length,
    items: transcript.answerKey.items.length, traps: transcript.answerKey.traps.length,
  };
}
