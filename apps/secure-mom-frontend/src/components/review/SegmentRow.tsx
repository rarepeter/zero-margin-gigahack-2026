import type { ReactNode } from 'react';
import { initials, type Segment } from '../../domain/transcript';

export function SegmentRow({ seg, focus, children, className = '' }: { seg: Segment; focus?: boolean; children?: ReactNode; className?: string }) {
  return (
    <li className={`${className}${focus ? ' focus' : ''}`} id={`seg-${seg.index}`}>
      <time>{seg.t ?? ''}</time>
      <span className="av" aria-hidden="true">{seg.speaker ? initials(seg.speaker) : '?'}</span>
      <div>
        {seg.speaker && <div className="who">{seg.speaker}{seg.lang && <span className="lg">{seg.lang}</span>}</div>}
        <p className="orig">{children ?? seg.text}</p>
      </div>
    </li>
  );
}
