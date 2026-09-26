import { Fragment, useState, type ReactElement } from 'react';
import { fmtDate, type Issue } from '../../domain/mom';
import { useApp, type Edits } from '../../state/store';
import { Icon } from '../ui/Icon';
import { FixWord, useDisplay } from './FixWord';

type OnEv = (issue: Issue) => void;

/** Renders `text`, replacing the flagged value (number / term) with a red FixWord. Unplaceable flags are appended. */
function Inline({ text, issues, onEv }: { text: string; issues: Issue[]; onEv: OnEv }) {
  let parts: (string | ReactElement)[] = [text];
  const tail: Issue[] = [];
  for (const is of issues) {
    let placed = false;
    parts = parts.flatMap((p): (string | ReactElement)[] => {
      if (placed || typeof p !== 'string' || !is.proposed || !p.includes(is.proposed)) return [p];
      placed = true;
      const at = p.indexOf(is.proposed);
      return [p.slice(0, at), <FixWord key={is.id} issue={is} onEvidence={onEv} />, p.slice(at + is.proposed.length)];
    });
    if (!placed) tail.push(is);
  }
  return (
    <>
      {parts.map((p, i) => <Fragment key={i}>{p}</Fragment>)}
      {tail.map((is) => <Fragment key={is.id}> <FixWord issue={is} onEvidence={onEv} /></Fragment>)}
    </>
  );
}

/** Edit mode field: auto-growing textarea bound to a draft path such as `decisions.0.text`. */
function Field({ path, value, draft, set }: { path: string; value: string; draft: Edits; set: (p: string, v: string) => void }) {
  return (
    <textarea
      className="edta"
      rows={1}
      value={draft[path] ?? value}
      onChange={(e) => set(path, e.target.value)}
      ref={(el) => { if (el) { el.style.height = 'auto'; el.style.height = `${el.scrollHeight}px`; } }}
    />
  );
}

/** Right panel: the minutes as a readable document. Red words = values the doctor must confirm. */
export function SummaryPane({ onEvidence }: { onEvidence: OnEv }) {
  const { s, l, issues, view, saveEdits, setReviewEditing } = useApp();
  const show = useDisplay();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Edits>({});
  if (!view) return null;
  const h = view.header;
  const of = (sec: string, i: number) => issues.filter((x) => x.id.startsWith(`${sec}.${i}.`));
  const set = (p: string, v: string) => setDraft((d) => ({ ...d, [p]: v }));
  const text = (path: string, value: string, inline: Issue[]) =>
    editing ? <Field path={path} value={value} draft={draft} set={set} /> : <Inline text={value} issues={inline} onEv={onEvidence} />;

  const start = () => { setDraft({ ...s.edits }); setEditing(true); setReviewEditing(true); };
  const save = () => {
    const changed = Object.fromEntries(Object.entries(draft).filter(([k, v]) => {
      const orig = k.split('.').reduce<unknown>((o, key) => (o as Record<string, unknown>)?.[key], s.mom);
      return v !== orig;
    }));
    saveEdits(changed);
    setEditing(false);
    setReviewEditing(false);
  };

  const risks = [...view.risks, ...view.open_questions];

  return (
    <section className="pane" aria-labelledby="mh">
      <div className="tbar">
        <div className="ptabs" role="tablist">
          <h2 id="mh" className="sr-only">{l.min_t}</h2>
          <button type="button" role="tab" className="on" aria-selected>{l.rt_sum}</button>
        </div>
        <div className="tctl">
          <div className="hbtns">
            {editing ? (
              <>
                <button className="btn-sm btn-sm-primary" type="button" onClick={save}>{l.ed_save}</button>
              <button className="tx-toggle" type="button" onClick={() => { setEditing(false); setReviewEditing(false); }}>{l.ed_cancel}</button>
              </>
            ) : (
              <button className="tx-toggle" type="button" onClick={start}><Icon name="pen" />{l.ed}</button>
            )}
          </div>
        </div>
      </div>
      <div className="pbody pad" id="mnpane">
        {editing && <div className="fxbar need" role="status"><Icon name="pen" /><span>{l.ed_hint}</span></div>}
        <div className={`doc${editing ? ' editing' : ''}`}>
          <h3 className="mtitle">{h.subject}</h3>
          <p className="meta">{fmtDate(h.date)}{h.duration_min != null && ` · ${h.duration_min} min`} · {l.types[h.meeting_type] ?? h.meeting_type}</p>

          <h4>{l.l_part}</h4>
          <p>{(h.participants_mentioned ?? []).map((p) => (p.role ? `${p.name} (${p.role})` : p.name)).join(', ') || '—'}</p>

          <h4>{l.l_what}</h4>
          <p>{text('summary', view.summary, [])}</p>
          {(view.findings.length > 0 || view.topics.length > 0) && (
            <ul>
              {view.findings.map((f, i) => <li key={`f${i}`}>{text(`findings.${i}.text`, f.text, of('findings', i))}</li>)}
              {view.topics.map((t, i) => <li key={`t${i}`}><b>{t.title}</b> — {t.text}</li>)}
            </ul>
          )}

          {view.decisions.length > 0 && (
            <>
              <h4>{l.l_sol}</h4>
              <ul>
                {view.decisions.map((d, i) => {
                  const fl = of('decisions', i);
                  const st = fl.filter((x) => x.kind === 'decision_status');
                  return (
                    <li key={d.id}>
                      {text(`decisions.${i}.text`, d.text, fl.filter((x) => x.kind !== 'decision_status'))}
                      {st.length > 0
                        ? <> — {st.map((x) => <FixWord key={x.id} issue={x} onEvidence={onEvidence} />)}</>
                        : d.status !== 'decided' && <em className="st"> — {l.status[d.status] ?? d.status}</em>}
                    </li>
                  );
                })}
              </ul>
            </>
          )}

          {view.actions.length > 0 && (
            <>
              <h4>{l.l_next}</h4>
              <ul>
                {view.actions.map((a, i) => {
                  const fl = of('actions', i);
                  const own = fl.find((x) => x.kind === 'owner');
                  const due = fl.find((x) => x.kind === 'deadline');
                  const due0 = a.deadline.resolved ? fmtDate(a.deadline.resolved) : a.deadline.spoken;
                  return (
                    <li key={a.id}>
                      <b>{text(`actions.${i}.text`, a.text, fl.filter((x) => x.kind !== 'owner' && x.kind !== 'deadline'))}</b>
                      {' — '}
                      {own ? <FixWord issue={own} onEvidence={onEvidence} /> : a.owner ?? <span className="gap">{l.unassigned}</span>}
                      {', '}{l.due.toLowerCase()}{' '}
                      {due ? <FixWord issue={due} onEvidence={onEvidence} /> : due0 ? show({ kind: 'deadline' } as Issue, a.deadline.resolved ?? due0) : <span className="gap">{l.nodate}</span>}
                    </li>
                  );
                })}
              </ul>
            </>
          )}

          {risks.length > 0 && (
            <>
              <h4>{l.l_risk}</h4>
              <ul>{risks.map((r, i) => <li key={i}>{r.text}{r.raised_by && <span className="by"> — {r.raised_by}</span>}</li>)}</ul>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
