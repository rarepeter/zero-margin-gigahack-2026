import { useEffect, useMemo, useRef, useState } from 'react';
import { fmtDate } from '../../domain/mom';
import { initials, speakingShare } from '../../domain/transcript';
import { useApp } from '../../state/store';
import { Icon } from '../ui/Icon';
import { SegmentRow } from './SegmentRow';

function highlight(text: string, q: string) {
  if (!q) return text;
  const parts = text.split(new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi'));
  return parts.map((p, i) => (i % 2 ? <mark key={i} className="hit">{p}</mark> : p));
}

function MeetingDetails() {
  const { s, l, view } = useApp();
  if (!view) return null;
  const h = view.header;
  const context = s.reviewContext;
  const people = context
    ? context.speakers.map((speaker) => ({
        name: speaker.displayName ?? speaker.id,
        share: Math.round((speaker.speakingTimeProportion ?? 0) * 100),
        langs: speaker.languages.map((language) => language.toUpperCase()),
      }))
    : speakingShare(s.segments);
  const langs = context
    ? context.meetingMetadata.languages.map(({ code, proportion }) => `${code.toUpperCase()} ${Math.round(proportion * 100)}%`).join(' · ')
    : h.languages
      ? Object.entries(h.languages).map(([k, v]) => `${k.toUpperCase()} ${Math.round((v ?? 0) * 100)}%`).join(' · ')
      : '—';
  const durationMinutes = context ? Math.max(1, Math.ceil(context.meetingMetadata.durationMs / 60000)) : h.duration_min;
  const filename = context?.sourceRecording.originalFileName ?? s.fileName ?? '—';
  return (
    <div className="pbody pad" id="txpane">
      <dl className="dl">
        <dt>{l.k_type}</dt><dd>{l.types[h.meeting_type] ?? h.meeting_type}</dd>
        <dt>{l.d_date}</dt><dd>{fmtDate(h.date)}</dd>
        {durationMinutes != null && <><dt>{l.k_dur}</dt><dd>{durationMinutes} min</dd></>}
        <dt>{l.k_lang}</dt><dd>{langs}</dd>
        <dt>{l.d_file}</dt><dd>{filename} · {l.d_file_v}</dd>
      </dl>
      <h4 className="dsub">{l.lt_part(people.length)}</h4>
      <ul className="plist">
        {people.map((p) => (
          <li key={p.name}>
            <span className="av">{initials(p.name)}</span>
            <div><b>{p.name}</b><small>{p.langs.join(' · ')}</small></div>
            <div className="pct">{p.share}% <small>{l.p_talk}</small><i><span style={{ width: `${Math.min(100, p.share * 2.5)}%` }} /></i></div>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Left panel: transcript (with search) and meeting details. `focus` = segment index to scroll to and highlight. */
export function TranscriptPane({ focus }: { focus: { seg: number; n: number } | null }) {
  const { s, l } = useApp();
  const [tab, setTab] = useState<'tx' | 'det'>('tx');
  const [q, setQ] = useState('');
  const pane = useRef<HTMLDivElement>(null);

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return needle ? s.segments.filter((x) => `${x.text} ${x.speaker ?? ''}`.toLowerCase().includes(needle)) : s.segments;
  }, [s.segments, q]);

  // Evidence jump: switch to transcript, clear search, scroll the segment into the upper third.
  useEffect(() => {
    if (!focus) return;
    setTab('tx');
    setQ('');
    requestAnimationFrame(() => {
      const el = document.getElementById(`seg-${focus.seg}`);
      const pn = pane.current;
      if (!el || !pn) return;
      if (getComputedStyle(pn).overflowY === 'auto') {
        pn.scrollTo({ top: pn.scrollTop + el.getBoundingClientRect().top - pn.getBoundingClientRect().top - pn.clientHeight / 3, behavior: 'smooth' });
      }
    });
  }, [focus]);

  return (
    <section className="pane" aria-label={l.lt_tx}>
      <div className="tbar">
        <div className="ptabs" role="tablist">
          {([['tx', l.lt_tx], ['det', l.lt_det]] as const).map(([k, x]) => (
            <button key={k} type="button" role="tab" className={tab === k ? 'on' : ''} aria-selected={tab === k} onClick={() => setTab(k)}>{x}</button>
          ))}
        </div>
        {tab === 'tx' && (
          <label className="sbox sbox-top">
            <Icon name="search" />
            <input type="search" placeholder={l.tx_search} aria-label={l.tx_search} value={q} onChange={(e) => setQ(e.target.value)} />
          </label>
        )}
      </div>
      {tab === 'tx' ? (
        <div className="pbody" id="txpane" ref={pane}>
          <ol className="tl">
            {rows.length ? rows.map((seg) => (
              <SegmentRow key={seg.index} seg={seg} focus={focus?.seg === seg.index}>{highlight(seg.text, q.trim())}</SegmentRow>
            )) : <span className="empty">{l.tx_empty}</span>}
          </ol>
        </div>
      ) : (
        <MeetingDetails />
      )}
    </section>
  );
}
