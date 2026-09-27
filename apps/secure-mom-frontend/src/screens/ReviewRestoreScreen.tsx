import { Icon } from '../components/ui/Icon';
import { useApp } from '../state/store';

/** Fresh-session landing state for a stable ?review=<jobId> link. */
export function ReviewRestoreScreen() {
  const { s, l, newMeeting } = useApp();
  const offline = s.serverOnline === false;
  const waiting = s.job && !(s.job.status === 'AWAITING_REVIEW' && s.job.stage === 'review_ready');
  const title = offline ? l.review_offline_t : waiting ? l.review_waiting_t : l.review_loading_t;
  const detail = offline
    ? l.review_offline_s
    : waiting
      ? l.review_waiting_s(s.job!.stage)
      : l.review_loading_s;

  return (
    <>
      <h1>{title}</h1>
      <p className="lead">{detail}</p>
      <div className="privacy"><Icon name={offline ? 'warn' : 's_rev'} /><span>{l.review_local}</span></div>
      <div className="row" style={{ marginTop: 20 }}>
        <button className="btn btn-ghost" type="button" onClick={newMeeting}>{l.new_upload}</button>
      </div>
    </>
  );
}
