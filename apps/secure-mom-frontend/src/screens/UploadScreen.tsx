import { useRef, useState } from 'react';
import { ApiError } from '../api';
import { Icon } from '../components/ui/Icon';
import { useApp } from '../state/store';

const MAX_BYTES = 300 * 1024 * 1024; // matches the backend limit (300 MiB)
const AUDIO_EXTENSIONS = new Set(['aac', 'flac', 'm4a', 'mp3', 'mp4', 'ogg', 'opus', 'wav', 'webm']);

export function UploadScreen() {
  const { l, upload, go } = useApp();
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const send = async (f: File | undefined) => {
    if (!f) return;
    setErr(null);
    if (f.size > MAX_BYTES) return setErr(l.too_big);
    const extension = f.name.split('.').pop()?.toLowerCase() ?? '';
    if (!AUDIO_EXTENSIONS.has(extension)) return setErr(l.bad_type);
    setBusy(true);
    try {
      await upload(f, f.name);
    } catch (e) {
      setErr(e instanceof ApiError ? (e.status === 413 ? l.too_big : e.status === 415 ? l.bad_type : `${l.up_err}: ${e.message}`) : l.up_err);
      setBusy(false);
    }
  };

  return (
    <>
      <h1>{l.up_t}</h1>
      <p className="lead">{l.up_s}</p>
      <label
        className={`drop${over ? ' over' : ''}`}
        onDragEnter={(e) => { e.preventDefault(); setOver(true); }}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={(e) => { e.preventDefault(); setOver(false); }}
        onDrop={(e) => { e.preventDefault(); setOver(false); send(e.dataTransfer.files[0]); }}
        aria-busy={busy}
      >
        <span className="drop-icon"><Icon name="upload" /></span>
        <strong>{l.drop}</strong>
        <span className="hint">{l.fmt}</span>
        <input ref={input} type="file" accept=".aac,.flac,.m4a,.mp3,.mp4,.ogg,.opus,.wav,.webm" hidden disabled={busy} onChange={(e) => send(e.target.files?.[0])} />
      </label>
      {err && <p className="uperr" role="alert">{err}</p>}
      <div className="or">{l.or}</div>
      <div className="row">
        <button className="btn btn-secondary" id="b-rec" type="button" disabled={busy} onClick={() => go('recording')}>
          <Icon name="mic" />{l.rec}
        </button>
      </div>
      <div className="privacy"><Icon name="lock" /><span>{l.privacy}</span></div>
    </>
  );
}
