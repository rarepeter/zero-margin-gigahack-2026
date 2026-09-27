import { useEffect, useMemo, useRef, useState } from 'react';
import { api, ApiError, type DirectoryPerson } from '../../api';
import { demoDirectoryMatches } from '../../data/directory';
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

const generatedSpeakerName = /^speaker[-_ ]?\d+$/i;

function ParticipantNameEditor({ value, onChange, placeholder, hint, useName, suggestions, unavailable, autoFocus }: {
  value: string;
  onChange(value: string): void;
  placeholder: string;
  hint: string;
  useName(value: string): string;
  suggestions: string;
  unavailable: string;
  autoFocus: boolean;
}) {
  const [matches, setMatches] = useState<DirectoryPerson[]>([]);
  const [focused, setFocused] = useState(false);
  const [loading, setLoading] = useState(false);
  const [lookupFailed, setLookupFailed] = useState(false);

  useEffect(() => {
    if (!focused) return;
    let alive = true;
    const timer = window.setTimeout(() => {
      const query = generatedSpeakerName.test(value.trim()) ? '' : value;
      setLoading(true);
      setLookupFailed(false);
      api.searchDirectory(query)
        .then(async (people) => people.length || !query.trim() ? people : api.searchDirectory(''))
        .then((people) => { if (alive) setMatches(people.length ? people : demoDirectoryMatches(query)); })
        .catch(() => { if (alive) { setMatches(demoDirectoryMatches(query)); setLookupFailed(true); } })
        .finally(() => { if (alive) setLoading(false); });
    }, 120);
    return () => { alive = false; window.clearTimeout(timer); };
  }, [focused, value]);

  const customName = value.trim();
  const exactMatch = matches.some((person) => person.name.localeCompare(customName, undefined, { sensitivity: 'accent' }) === 0);

  return (
    <div className="part-combo">
      <input
        autoFocus={autoFocus}
        type="text"
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={focused}
        autoComplete="off"
        maxLength={160}
        placeholder={placeholder}
        value={value}
        onFocus={() => setFocused(true)}
        onBlur={() => window.setTimeout(() => setFocused(false), 100)}
        onChange={(event) => onChange(event.target.value)}
      />
      {focused && (
        <div className="part-options" role="listbox">
          {customName && !generatedSpeakerName.test(customName) && !exactMatch && (
            <button
              type="button"
              role="option"
              className="part-use-custom"
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => setFocused(false)}
            >
              <span>{useName(customName)}</span>
              <small>{hint}</small>
            </button>
          )}
          {!!matches.length && <small className="part-options-label">{suggestions}</small>}
          {matches.map((person) => (
            <button
              key={person.email}
              type="button"
              role="option"
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => { onChange(person.name); setFocused(false); }}
            >
              <span>{person.name}</span>
              <small>{person.title ?? person.email}</small>
            </button>
          ))}
          {loading && <small className="part-custom">…</small>}
          {lookupFailed && <small className="part-custom part-lookup-error">{unavailable}</small>}
          {!loading && !lookupFailed && !matches.length && !customName && <small className="part-custom">{hint}</small>}
        </div>
      )}
    </div>
  );
}

function MeetingDetails() {
  const { s, l, view, saveParticipantNames, setParticipantEditing } = useApp();
  const [editingParticipants, setEditingParticipants] = useState(false);
  const [participantNames, setParticipantNames] = useState<Record<string, string>>({});
  const [focusSpeakerId, setFocusSpeakerId] = useState<string | null>(null);
  const [savingParticipants, setSavingParticipants] = useState(false);
  const [participantSaveError, setParticipantSaveError] = useState<string | null>(null);
  if (!view) return null;
  const h = view.header;
  const context = s.reviewContext;
  const people = context
    ? context.speakers.map((speaker) => ({
        id: speaker.id,
        name: speaker.displayName ?? speaker.id,
        share: Math.round((speaker.speakingTimeProportion ?? 0) * 100),
        langs: speaker.languages.map((language) => language.toUpperCase()),
      }))
    : speakingShare(s.segments).map((person) => ({ ...person, id: person.name }));
  const langs = context
    ? context.meetingMetadata.languages.map(({ code, proportion }) => `${code.toUpperCase()} ${Math.round(proportion * 100)}%`).join(' · ')
    : h.languages
      ? Object.entries(h.languages).map(([k, v]) => `${k.toUpperCase()} ${Math.round((v ?? 0) * 100)}%`).join(' · ')
      : '—';
  const durationMinutes = context ? Math.max(1, Math.ceil(context.meetingMetadata.durationMs / 60000)) : h.duration_min;
  const filename = context?.sourceRecording.originalFileName ?? s.fileName ?? '—';
  const startParticipantEdit = (speakerId?: string) => {
    if (!context || s.approvalLocked) return;
    setParticipantNames(Object.fromEntries(people.map((person) => [person.id, person.name])));
    setFocusSpeakerId(speakerId ?? null);
    setParticipantSaveError(null);
    setEditingParticipants(true);
    setParticipantEditing(true);
  };
  const cancelParticipantEdit = () => {
    setEditingParticipants(false);
    setFocusSpeakerId(null);
    setParticipantSaveError(null);
    setParticipantEditing(false);
  };
  const participantValuesValid = people.every((person) => (participantNames[person.id] ?? person.name).trim());
  const saveParticipants = async () => {
    if (!context || !participantValuesValid) return;
    setSavingParticipants(true);
    setParticipantSaveError(null);
    try {
      await saveParticipantNames(context.speakers.map((speaker) => ({
        speakerId: speaker.id,
        displayName: (participantNames[speaker.id] ?? speaker.displayName ?? speaker.id).trim(),
      })));
      setEditingParticipants(false);
      setFocusSpeakerId(null);
      setParticipantEditing(false);
    } catch (error) {
      setParticipantSaveError(
        error instanceof ApiError && error.code === 'HTTP_404'
          ? l.part_restart
          : error instanceof Error ? error.message : l.part_save_error,
      );
    } finally {
      setSavingParticipants(false);
    }
  };
  return (
    <div className="pbody pad" id="txpane">
      <dl className="dl">
        <dt>{l.k_type}</dt><dd>{l.types[h.meeting_type] ?? h.meeting_type}</dd>
        <dt>{l.d_date}</dt><dd>{fmtDate(h.date)}</dd>
        {durationMinutes != null && <><dt>{l.k_dur}</dt><dd>{durationMinutes} min</dd></>}
        <dt>{l.k_lang}</dt><dd>{langs}</dd>
        <dt>{l.d_file}</dt><dd>{filename} · {l.d_file_v}</dd>
      </dl>
      <div className="part-heading">
        <h4 className="dsub">{l.lt_part(people.length)}</h4>
        {context && !s.approvalLocked && (editingParticipants ? (
          <span className="part-actions">
            <button type="button" className="btn-sm btn-sm-primary" disabled={!participantValuesValid || savingParticipants} onClick={saveParticipants}>{savingParticipants ? `${l.ed_save}…` : l.ed_save}</button>
            <button type="button" className="tx-toggle" disabled={savingParticipants} onClick={cancelParticipantEdit}>{l.ed_cancel}</button>
          </span>
        ) : <button type="button" className="tx-toggle" onClick={() => startParticipantEdit()}><Icon name="pen" />{l.ed}</button>)}
      </div>
      {participantSaveError && <p className="part-save-error" role="alert">{participantSaveError}</p>}
      <ul className="plist">
        {people.map((p) => (
          <li key={p.id}>
            <span className="av">{initials(editingParticipants ? participantNames[p.id] ?? p.name : p.name)}</span>
            <div className="part-name">
              {editingParticipants ? (
                <ParticipantNameEditor
                  value={participantNames[p.id] ?? p.name}
                  onChange={(name) => { setParticipantSaveError(null); setParticipantNames((current) => ({ ...current, [p.id]: name })); }}
                  placeholder={l.part_ph}
                  hint={l.part_hint}
                  useName={l.part_use}
                  suggestions={l.part_suggestions}
                  unavailable={l.part_unavailable}
                  autoFocus={focusSpeakerId === p.id}
                />
              ) : (
                <button type="button" className="part-name-button" disabled={!context || s.approvalLocked} onClick={() => startParticipantEdit(p.id)}>{p.name}</button>
              )}
              <small>{p.langs.join(' · ')}</small>
            </div>
            <div className="pct">{p.share}% <small>{l.p_talk}</small><i><span style={{ width: `${Math.min(100, p.share * 2.5)}%` }} /></i></div>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Left panel: transcript (with search) and meeting details. `focus` = segment index to scroll to and highlight. */
export function TranscriptPane({ focus }: { focus: { seg: number; n: number } | null }) {
  const { s, l, setParticipantEditing } = useApp();
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
    setParticipantEditing(false);
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
            <button key={k} type="button" role="tab" className={tab === k ? 'on' : ''} aria-selected={tab === k} onClick={() => { if (tab === 'det' && k !== 'det') setParticipantEditing(false); setTab(k); }}>{x}</button>
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
