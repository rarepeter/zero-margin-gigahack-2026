import { Icon } from '../components/ui/Icon';
import { downloadJson, printPdf } from '../lib/exportDoc';
import { useApp } from '../state/store';

const mm = (sec: number) => `${Math.floor(sec / 60)} min ${String(sec % 60).padStart(2, '0')} s`;

export function DoneScreen() {
  const { s, l, newMeeting } = useApp();
  const purge = <ul className="purge">{l.purge.map((p) => <li key={p}><Icon name="check" />{p}</li>)}</ul>;

  if (s.outcome === 'discard' || !s.exported) {
    return (
      <>
        <div className="done-hero"><h1>{l.purged}</h1></div>
        {purge}
        <button className="btn btn-primary btn-block" type="button" onClick={newMeeting}><Icon name="upload" />{l.newm}</button>
      </>
    );
  }

  const mom = s.exported;
  const review = Math.max(s.reviewSecs, 1);
  const proc = s.reviewContext
    ? Math.round(s.reviewContext.processing.elapsedMs / 1000)
    : s.readyAt && s.uploadedAt
      ? Math.round((s.readyAt - s.uploadedAt) / 1000)
      : null;
  const saved = Math.max(1, 60 - Math.ceil(review / 60));

  return (
    <>
      <div className="done-hero">
        <div className="check"><Icon name="bigcheck" /></div>
        <h1>{s.outcome === 'share' ? l.shared : l.dl_t}</h1>
        <p className="lead" style={{ marginInline: 'auto' }}>{s.outcome === 'share' ? `${l.rc_n(s.recipients.length)} · ${l.rc_via}` : l.dl_s}</p>
      </div>
      <div className="thanks" role="note"><div><strong>{l.ty_t}</strong><span>{l.ty_s(saved)}</span></div></div>
      <div className="row">
        <button className="btn btn-primary" type="button" onClick={() => printPdf(mom, l)}><Icon name="down" />{l.pdf}</button>
        <button className="btn btn-secondary" type="button" onClick={() => downloadJson(mom)}><Icon name="down" />{l.json}</button>
      </div>
      <div className="saved">
        <div><div className="k">{l.your}</div><div className="big">{mm(review)}</div><div className="k">{l.vs}</div></div>
        <div><div className="k">{l.proc}</div><div className="big">{proc !== null ? mm(proc) : '—'}</div><div className="k">{mom.header.duration_min != null ? `${mom.header.duration_min} min audio` : ''}</div></div>
      </div>
      <p className="eyebrow" style={{ marginBottom: 10 }}>{l.purged}</p>
      {purge}
      <button className="btn btn-ghost btn-block" type="button" onClick={newMeeting}>{l.newm}</button>
    </>
  );
}
