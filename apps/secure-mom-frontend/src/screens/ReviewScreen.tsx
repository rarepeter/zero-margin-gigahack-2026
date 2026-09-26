import { useState } from 'react';
import { BottomBar } from '../components/review/BottomBar';
import { SummaryPane } from '../components/review/SummaryPane';
import { TranscriptPane } from '../components/review/TranscriptPane';
import type { Issue } from '../domain/mom';
import { useApp } from '../state/store';

/** Transcript on the left, minutes on the right. Clicking a red word jumps the transcript to its evidence. */
export function ReviewScreen() {
  const { s, l } = useApp();
  const [focus, setFocus] = useState<{ seg: number; n: number } | null>(null);

  const onEvidence = (issue: Issue) => {
    const ev = issue.evidence;
    const byTime = ev.t ? s.segments.find((x) => x.t === ev.t) : undefined;
    const seg = byTime?.index ?? ev.segment;
    setFocus((f) => ({ seg, n: (f?.n ?? 0) + 1 }));
  };

  return (
    <>
      <h1 className="sr-only">{l.min_t}</h1>
      <div className="board">
        <TranscriptPane focus={focus} />
        <SummaryPane onEvidence={onEvidence} />
      </div>
      <BottomBar />
    </>
  );
}
