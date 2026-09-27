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

/** Fixed bottom bar: recipients, Discard, and approval/export controls. */
export function BottomBar() {
  const { s, l, exportMom } = useApp();
  const editing = s.reviewEditing || s.participantEditing;
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const discardBtn = useRef<HTMLButtonElement>(null);
  if (confirm) {
    return <div className="bar2"><DiscardConfirm onCancel={() => { setConfirm(false); requestAnimationFrame(() => discardBtn.current?.focus()); }} /></div>;
  }
  return (
    <div className="bar2">
      <div className="to">{editing ? l.ed_save : <RecipientPicker />}</div>
      <button ref={discardBtn} className="btn btn-ghost" type="button" onClick={() => setConfirm(true)}>{l.discard}</button>
      <button
        className="btn btn-export"
        type="button"
        disabled={editing || busy}
        onClick={async () => { setBusy(true); try { await exportMom(); } finally { setBusy(false); } }}
      >
        <Icon name={s.recipients.length ? 'send' : 'down'} />
        {busy
          ? (s.recipients.length ? l.sending : l.approving)
          : (s.recipients.length ? l.approve_send : l.approve_download)}
      </button>
    </div>
  );
}
