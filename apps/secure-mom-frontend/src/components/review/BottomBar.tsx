import { useEffect, useRef, useState } from 'react';
import { useApp } from '../../state/store';
import { Icon } from '../ui/Icon';
import { RecipientPicker } from './RecipientPicker';

function DiscardConfirm({ onCancel }: { onCancel: () => void }) {
  const { l, discard } = useApp();
  const no = useRef<HTMLButtonElement>(null);
  useEffect(() => no.current?.focus(), []);
  return (
    <div className="dconf" role="alertdialog" aria-labelledby="dq-t" aria-describedby="dq-s" onKeyDown={(e) => e.key === 'Escape' && onCancel()}>
      <span className="dq-i"><Icon name="warn" /></span>
      <div className="dq-x"><b id="dq-t">{l.dq_t}</b><span id="dq-s">{l.dq_s}</span></div>
      <button ref={no} className="btn btn-ghost" type="button" onClick={onCancel}>{l.keep}</button>
      <button className="btn btn-danger" type="button" onClick={() => discard()}><Icon name="trash" />{l.yes}</button>
    </div>
  );
}

/** Fixed bottom bar: what's blocking export / recipients, Discard, Export (disabled while blocking red words remain). */
export function BottomBar() {
  const { l, left, view, exportMom } = useApp();
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const discardBtn = useRef<HTMLButtonElement>(null);
  const patient = view?.header.meeting_type === 'patient_case';

  if (confirm) {
    return <div className="bar2"><DiscardConfirm onCancel={() => { setConfirm(false); requestAnimationFrame(() => discardBtn.current?.focus()); }} /></div>;
  }
  return (
    <div className="bar2">
      <div className="to">{left ? <span className="need">{l.exp_need(left)}</span> : patient ? l.patient : <RecipientPicker />}</div>
      <button ref={discardBtn} className="btn btn-ghost" type="button" onClick={() => setConfirm(true)}>{l.discard}</button>
      <button
        className="btn btn-export"
        type="button"
        disabled={left > 0 || busy}
        onClick={async () => { setBusy(true); try { await exportMom(patient); } finally { setBusy(false); } }}
      >
        <Icon name="down" />{busy ? l.exporting : l.exp}
      </button>
    </div>
  );
}
