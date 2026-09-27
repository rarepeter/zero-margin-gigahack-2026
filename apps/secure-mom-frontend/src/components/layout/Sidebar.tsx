import { useEffect, useState } from 'react';
import type { JobStatus } from '../../api';
import { mmss } from '../../lib/format';
import { useApp } from '../../state/store';
import { Icon, type IconName } from '../ui/Icon';
import { AiConfidence } from './AiConfidence';

/** Backend statuses in pipeline order → the 4 processing sub-steps shown in the sidebar. */
const PIPE: JobStatus[] = ['QUEUED', 'TRANSCRIBING', 'GENERATING_MOM', 'AWAITING_REVIEW'];
const STEP_ICON: IconName[] = ['s_up', 's_proc', 's_rev', 's_exp'];

function Logo() {
  const { l } = useApp();
  return (
    <div className="logo">
      <svg width="30" height="34" viewBox="0 0 30 34" aria-hidden="true">
        <path d="M7 14V9.5a8 8 0 0 1 16 0V14" fill="none" stroke="currentColor" strokeWidth="3.2" />
        <rect x="2" y="14" width="26" height="19" rx="3" fill="currentColor" />
        <circle cx="15" cy="22" r="2.6" fill="#1A2B2D" />
        <rect x="13.8" y="23" width="2.4" height="5" rx="1.2" fill="#1A2B2D" />
      </svg>
      <div>
        <b>Secure MOM</b>
        <small>{l.tag}</small>
      </div>
    </div>
  );
}

/** Live pipeline steps while processing; collapsible recap with durations afterwards. */
function ProcessingSteps({ live }: { live: boolean }) {
  const { s, l } = useApp();
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!live) return;
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, [live]);

  const cur = s.job ? PIPE.indexOf(s.job.status) : 0;
  const start = s.uploadedAt ?? now;
  const at = (i: number) => s.seen[PIPE[i]];
  const dur = (i: number) => {
    const a = at(i), b = at(i + 1) ?? (i === PIPE.length - 1 ? a : undefined);
    return a && b ? mmss((b - a) / 1000) : null;
  };
  // Progress: status-based floor + slow creep inside the current phase (the API exposes no percentage).
  const phase = [0.04, 0.1, 0.6, 1][Math.max(0, cur)] ?? 0;
  const next = [0.1, 0.6, 0.95, 1][Math.max(0, cur)] ?? 1;
  const inPhase = (now - (at(cur) ?? start)) / 1000;
  const p = live ? phase + (next - phase) * (1 - Math.exp(-inPhase / 60)) : 1;
  const total = (s.readyAt ?? now) - start;

  return (
    <li className={`vsub${live ? '' : ' past'}`} aria-live="polite">
      <ol className="sst">
        {l.stages.map((label, i) => {
          const st = !live || i < cur ? 'ok' : i === cur ? 'run' : 'wait';
          return (
            <li key={label} className={st}>
              <span className="dot2">{st === 'ok' && <Icon name="check" />}</span>
              <span className="lb">{label}</span>
              <time>{st === 'ok' ? dur(i) ?? '' : st === 'run' ? '…' : ''}</time>
            </li>
          );
        })}
      </ol>
      {live ? (
        <>
          <div className="sbar" aria-hidden="true"><i style={{ width: `${Math.round(p * 100)}%` }} /></div>
          <div className="smeta"><span>{Math.round(p * 100)}%</span><span>{l.elapsed} <b>{mmss((now - start) / 1000)}</b></span></div>
        </>
      ) : (
        <div className="smeta tot"><span>{l.pr_tot}</span><b>{mmss(total / 1000)}</b></div>
      )}
    </li>
  );
}

function Stepper() {
  const { s, l } = useApp();
  const [open, setOpen] = useState(false);
  const idx = { upload: 0, recording: 0, processing: 1, failed: 1, review: 2, done: 3 }[s.screen];
  const done = s.screen === 'done';
  const procTotal = s.readyAt && s.uploadedAt ? mmss((s.readyAt - s.uploadedAt) / 1000) : null;

  const sub = (i: number) => {
    if (done) return i === 3 ? (s.outcome === 'discard' ? l.purged : l.st_sent) : l.st_done;
    if (i < idx) return i === 1 && procTotal ? `${l.st_done} · ${procTotal}` : l.st_done;
    if (i > idx) return l.st_wait;
    if (i === 1 && s.screen === 'failed') return l.st_failed;
    if (i === 2) return l.st_now;
    if (i === 0 && s.screen === 'recording') return l.recording;
    return l.st_now;
  };

  return (
    <nav aria-label="Progress">
      <ol className="vsteps">
        {l.steps.map((label, i) => {
          const st = done ? (i === 3 ? 'now' : 'done') : i < idx ? 'done' : i === idx ? 'now' : 'wait';
          const recap = i === 1 && st === 'done' && !!s.uploadedAt;
          const toggle = () => setOpen((o) => !o);
          return [
            <li
              key={label}
              className={`${st}${st === 'now' && i === 1 ? ' busy' : ''}${recap ? ' pbtn' : ''}`}
              aria-current={st === 'now' ? 'step' : undefined}
              {...(recap ? { role: 'button', tabIndex: 0, 'aria-expanded': open, title: l.pr_open, onClick: toggle, onKeyDown: (e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), toggle()) } : {})}
            >
              <span className="si"><Icon name={st === 'done' ? 'check' : STEP_ICON[i]} /></span>
              <span><b>{label}</b><small>{sub(i)}</small></span>
              {recap && <span className={`pchev${open ? ' open' : ''}`}><Icon name="chev" /></span>}
            </li>,
            i === 1 && s.screen === 'processing' ? <ProcessingSteps key="live" live /> : null,
            recap && open ? <ProcessingSteps key="recap" live={false} /> : null,
          ];
        })}
      </ol>
    </nav>
  );
}

function ServerStatus() {
  const { s, l } = useApp();
  const on = s.serverOnline !== false;
  return (
    <div className="side-foot">
      <span className="srv srv-side">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <rect x="3" y="3.5" width="18" height="5" rx="1" /><rect x="3" y="9.5" width="18" height="5" rx="1" /><rect x="3" y="15.5" width="18" height="5" rx="1" />
          <path d="M6.5 6h.01M6.5 12h.01M6.5 18h.01" strokeWidth="2.6" strokeLinecap="round" />
        </svg>
        <i className={`dot${on ? '' : ' off'}`} />
        <span>{l.server}: <b>{on ? l.online : l.offline}</b></span>
      </span>
      <span className="ver">v1.0</span>
    </div>
  );
}

export function Sidebar() {
  const { s } = useApp();
  return (
    <aside className="side" aria-label="Secure MOM">
      <Logo />
      <Stepper />
      <div id="sidemeta">{s.screen === 'review' && <AiConfidence />}</div>
      <ServerStatus />
    </aside>
  );
}
