import { useRef, useState } from 'react';
import { fmtDate } from '../../domain/mom';
import { useApp, type Edits } from '../../state/store';
import { Icon } from '../ui/Icon';

/** Right panel: readable minutes, with every visible document value editable in place. */
export function SummaryPane() {
  const { s, l, view, saveEdits, setReviewEditing } = useApp();
  const [editing, setEditing] = useState(false);
  const docRef = useRef<HTMLDivElement>(null);
  if (!view) return null;
  const h = view.header;
  const text = (path: string, value: string, placeholder?: string) => editing
    ? <span className="edit-value" data-edit-path={path} data-edit-start={value} data-placeholder={placeholder}>{value}</span>
    : value || placeholder || '';
  const fixed = (value: string) => <span contentEditable={false}>{value}</span>;

  const start = () => { setEditing(true); setReviewEditing(true); };
  const save = () => {
    const draft: Edits = { ...s.edits };
    docRef.current?.querySelectorAll<HTMLElement>('[data-edit-path]').forEach((el) => {
      const path = el.dataset.editPath;
      const current = el.textContent ?? '';
      if (path && current !== (el.dataset.editStart ?? '')) draft[path] = current;
    });
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
              !s.approvalLocked && <button className="tx-toggle" type="button" onClick={start}><Icon name="pen" />{l.ed}</button>
            )}
          </div>
        </div>
      </div>
      <div className="pbody pad" id="mnpane">
        <div
          ref={docRef}
          className={`doc${editing ? ' editing' : ''}`}
          contentEditable={editing}
          suppressContentEditableWarning
          role={editing ? 'textbox' : undefined}
          aria-multiline={editing || undefined}
        >
          <h3 className="mtitle">{text('header.subject', h.subject)}</h3>
          <p className="meta" contentEditable={false}>{fmtDate(h.date)}{h.duration_min != null && ` · ${h.duration_min} min`} · {l.types[h.meeting_type] ?? h.meeting_type}</p>

          <h4 contentEditable={false}>{l.l_part}</h4>
          <p>{(h.participants_mentioned ?? []).length
            ? (h.participants_mentioned ?? []).map((p, i) => (
                <span key={i}>
                  {i > 0 && fixed(', ')}{text(`header.participants_mentioned.${i}.name`, p.name)}
                  {p.role && <>{fixed(' (')}{text(`header.participants_mentioned.${i}.role`, p.role)}{fixed(')')}</>}
                </span>
              ))
            : '—'}</p>

          <h4 contentEditable={false}>{l.l_what}</h4>
          <p>{text('summary', view.summary)}</p>
          {(view.findings.length > 0 || view.topics.length > 0) && (
            <ul>
              {view.findings.map((f, i) => <li key={`f${i}`}>{text(`findings.${i}.text`, f.text)}</li>)}
              {view.topics.map((t, i) => <li key={`t${i}`}><b>{text(`topics.${i}.title`, t.title)}</b>{fixed(' — ')}{text(`topics.${i}.text`, t.text)}</li>)}
            </ul>
          )}

          {view.decisions.length > 0 && (
            <>
              <h4 contentEditable={false}>{l.l_sol}</h4>
              <ul>
                {view.decisions.map((d, i) => (
                  <li key={d.id}>
                    {text(`decisions.${i}.text`, d.text)}
                    {d.status !== 'decided' && <em className="st" contentEditable={false}> — {l.status[d.status] ?? d.status}</em>}
                  </li>
                ))}
              </ul>
            </>
          )}

          {view.actions.length > 0 && (
            <>
              <h4 contentEditable={false}>{l.l_next}</h4>
              <ul>
                {view.actions.map((a, i) => {
                  const due0 = a.deadline.resolved ? fmtDate(a.deadline.resolved) : a.deadline.spoken;
                  const duePath = a.deadline.resolved ? `actions.${i}.deadline.resolved` : `actions.${i}.deadline.spoken`;
                  return (
                    <li key={a.id}>
                      <b>{text(`actions.${i}.text`, a.text)}</b>
                      {fixed(' — ')}
                      {text(`actions.${i}.owner`, a.owner ?? '', l.unassigned)}
                      {fixed(`, ${l.due.toLowerCase()} `)}
                      {editing
                        ? text(duePath, a.deadline.resolved ?? a.deadline.spoken ?? '', l.nodate)
                        : due0 ?? l.nodate}
                    </li>
                  );
                })}
              </ul>
            </>
          )}

          {risks.length > 0 && (
            <>
              <h4 contentEditable={false}>{l.l_risk}</h4>
              <ul>
                {view.risks.map((r, i) => <li key={`r${i}`}>{text(`risks.${i}.text`, r.text)}{r.raised_by && <span className="by">{fixed(' — ')}{text(`risks.${i}.raised_by`, r.raised_by)}</span>}</li>)}
                {view.open_questions.map((r, i) => <li key={`q${i}`}>{text(`open_questions.${i}.text`, r.text)}{r.raised_by && <span className="by">{fixed(' — ')}{text(`open_questions.${i}.raised_by`, r.raised_by)}</span>}</li>)}
              </ul>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
