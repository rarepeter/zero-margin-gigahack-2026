import { expect, test } from 'bun:test';
import { loadTranscripts } from '../server/mom-data';

// Validates the checked-in fictional meetings and their answer keys.
test('every MoM transcript parses and has a usable answer key', () => {
  const transcripts = loadTranscripts();
  for (const t of transcripts) {
    expect(t.answerKey.items.length).toBeGreaterThanOrEqual(8);
    expect(t.answerKey.traps.length).toBeGreaterThanOrEqual(3);
    expect(t.answerKey.items.some(item => item.kind === 'decision')).toBe(true);
    expect(t.answerKey.items.some(item => item.kind === 'action')).toBe(true);
    // Speaker labels would make the input easier than real ASR output.
    expect(t.transcript).not.toMatch(/^\s*[\p{L}. ]{2,30}:\s/mu);
  }
});
