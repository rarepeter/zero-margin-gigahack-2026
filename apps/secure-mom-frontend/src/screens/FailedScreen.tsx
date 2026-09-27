import { Icon } from '../components/ui/Icon';
import { useApp } from '../state/store';

export function FailedScreen() {
  const { s, l, retry, newMeeting, toast } = useApp();
  const retryable = s.errorRetryable;
  return (
    <>
      <div className="dconf failed" role="alert">
        <span className="dq-i"><Icon name="warn" /></span>
        <div className="dq-x"><b>{l.failed_t}</b><span>{s.error}</span></div>
      </div>
      <div className="row" style={{ marginTop: 20 }}>
        {retryable && <button className="btn btn-primary" type="button" onClick={() => retry().catch((e) => toast(String(e.message ?? e)))}>{l.retry}</button>}
        <button className="btn btn-ghost" type="button" onClick={newMeeting}>{l.new_upload}</button>
      </div>
    </>
  );
}
