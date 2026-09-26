import { useEffect, useRef, useState } from 'react';
import { fmtDate, type Issue } from '../../domain/mom';
import { EDITED, useApp } from '../../state/store';
import { Icon } from '../ui/Icon';

/** How a candidate / resolved value is shown to the doctor. */
export function useDisplay() {
  const { l } = useApp();
  return (issue: Issue, v: string) =>
    issue.kind === 'decision_status' ? l.status[v] ?? v : issue.kind === 'deadline' && /^\d{4}-\d{2}-\d{2}$/.test(v) ? fmtDate(v) : v;
}

/**
 * A red word: the model's uncertain value. Click → small popover with the question,
 * one-click "agree" (first candidate), alternatives, or a typed value.
 * Resolved values turn black with a green dotted underline and can be reopened.
 */
export function FixWord({ issue, onEvidence }: { issue: Issue; onEvidence: (issue: Issue) => void }) {
  const { s, l, resolve } = useApp();
  const show = useDisplay();
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState('');
  const [top, setTop] = useState(0);
  const ref = useRef<HTMLSpanElement>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const v = s.res[issue.id];
  const resolved = v !== undefined && v !== EDITED;

  useEffect(() => {
    if (!open) return;
    const off = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('mousedown', off);
    document.addEventListener('keydown', esc);
    return () => { document.removeEventListener('mousedown', off); document.removeEventListener('keydown', esc); };
  }, [open]);

  const pick = (val: string) => { resolve(issue.id, val); setOpen(false); setTyped(''); };
  const toggle = () => {
    if (!open) {
      // Anchor the popover under the word, inside the scrolling summary pane (#mnpane is position:relative).
      const pane = btn.current?.closest('#mnpane') as HTMLElement | null;
      const b = btn.current?.getBoundingClientRect();
      if (pane && b) {
        const t = b.bottom - pane.getBoundingClientRect().top + pane.scrollTop + 8;
        setTop(t);
        requestAnimationFrame(() => {
          const bottom = t + 170;
          if (bottom > pane.scrollTop + pane.clientHeight) pane.scrollTo({ top: bottom - pane.clientHeight + 16, behavior: 'smooth' });
        });
      }
      onEvidence(issue);
    }
    setOpen((o) => !o);
  };
  const label = resolved ? show(issue, v) : issue.proposed ? `${show(issue, issue.proposed)}?` : issue.kind === 'owner' ? `${l.own}?` : '?';
  const options = issue.candidates.length ? issue.candidates : issue.proposed ? [issue.proposed] : [];

  return (
    <span className="fxwrap" ref={ref}>
      <button
        ref={btn}
        type="button"
        className={resolved ? 'fixed' : issue.blocking ? 'fix' : 'fix soft'}
        title={resolved ? l.fx_tip : issue.reason}
        aria-expanded={open}
        onClick={toggle}
      >
        {label}
      </button>
      {open && (
        <span className="fxq" role="dialog" aria-label={issue.reason} style={{ top }}>
          <b>{issue.reason}</b>
          <span className="fxc">
            {options.map((c, i) => (
              <button key={c} type="button" className={`fchip2${i === 0 ? ' ai' : ''}`} onClick={() => pick(c)}>
                {i === 0 && <Icon name="check" />}{show(issue, c)}
              </button>
            ))}
          </span>
          <form className="fxtype" onSubmit={(e) => { e.preventDefault(); if (typed.trim()) pick(typed.trim()); }}>
            <input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="…" aria-label={issue.reason} />
          </form>
        </span>
      )}
    </span>
  );
}
