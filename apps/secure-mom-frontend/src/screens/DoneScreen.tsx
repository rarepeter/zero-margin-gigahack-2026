import { useState } from 'react';
import { RecipientPicker } from '../components/review/RecipientPicker';
import { Icon } from '../components/ui/Icon';
import type { Person } from '../data/directory';
import { printPdf } from '../lib/exportDoc';
import { useApp } from '../state/store';

/** After approval: pick more people and email them the approved MoM as a PDF. Repeatable. */
function SendMore() {
  const { l, sendApproved } = useApp();
  const [recipients, setRecipients] = useState<Person[]>([]);
  const [busy, setBusy] = useState(false);
  const send = async () => {
    setBusy(true);
    try {
      if (await sendApproved(recipients)) setRecipients([]);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="send-more">
      <div className="to"><RecipientPicker recipients={recipients} onChange={setRecipients} disabled={busy} label={l.send_to} /></div>
      <button className="btn btn-secondary" type="button" disabled={!recipients.length || busy} onClick={send}>
        <Icon name="send" />{busy ? l.send_busy : l.send_pdf}
      </button>
    </div>
  );
}

const mm = (sec: number) => `${Math.floor(sec / 60)} min ${String(sec % 60).padStart(2, '0')} s`;

export function DoneScreen() {
  const { s, l, newMeeting } = useApp();
  if (s.outcome === 'discard' || !s.exported) {
    return (
      <>
        <div className="done-hero"><h1>{l.purged}</h1></div>
        <button className="btn btn-primary btn-block" type="button" onClick={newMeeting}><Icon name="upload" />{l.newm}</button>
      </>
    );
  }

  const mom = s.exported;
  const timing = s.reviewContext?.processing;
  const proc = timing?.audioStageMs != null && timing.momStageMs != null
    ? Math.round((timing.audioStageMs + timing.momStageMs) / 1000)
    : null;
  const savedMinutes = Math.max(0, 60 - Math.round(s.portalSecs / 60));

  return (
    <>
      <div className="done-hero">
        <div className="check"><Icon name="bigcheck" /></div>
        <h1>{s.outcome === 'sent' ? l.sent_t : l.dl_t}</h1>
        <p className="lead" style={{ marginInline: 'auto' }}>{s.outcome === 'sent' ? l.sent_s(s.deliveredRecipientCount) : l.dl_s}</p>
      </div>
      {savedMinutes > 0 && <div className="thanks" role="note"><div><strong>{l.ty_t}</strong><span>{l.ty_s(savedMinutes)}</span></div></div>}
      <div className="row">
        <button className="btn btn-primary" type="button" onClick={() => printPdf(mom, l, s.lang)}><Icon name="down" />{l.pdf}</button>
      </div>
      <SendMore />
      <div className="saved">
        <div><div className="k">{l.your}</div><div className="big">~{savedMinutes} min</div><div className="k">{l.vs(mm(s.portalSecs))}</div></div>
        <div><div className="k">{l.proc}</div><div className="big">{proc !== null ? mm(proc) : '—'}</div><div className="k">{l.proc_note}</div></div>
      </div>
      <button className="btn btn-ghost btn-block" type="button" onClick={newMeeting}>{l.newm}</button>
    </>
  );
}
