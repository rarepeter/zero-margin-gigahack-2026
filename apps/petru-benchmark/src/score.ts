// Single-hue sequential ramp (light → dark teal) for 0–100 scores. Scores are always printed too, so color is never the only cue.
export const RAMP = ['#eef6f4', '#d5ebe6', '#b3dbd2', '#86c3b6', '#57a597', '#2e8276', '#135d55'];
export function scoreStyle(score: number) {
  const step = Math.min(RAMP.length - 1, Math.floor((score / 100) * RAMP.length));
  return { background: RAMP[step], color: step >= 4 ? '#ffffff' : '#17313f' };
}
