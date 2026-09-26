import { useEffect, useRef, useState } from 'react';
import { hhmmss } from '../lib/format';
import { useApp } from '../state/store';

/** Records from the microphone in the browser (MediaRecorder) and uploads the result like a file. */
export function RecordingScreen() {
  const { l, upload, go, toast } = useApp();
  const [secs, setSecs] = useState(0);
  const rec = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);

  useEffect(() => {
    let stream: MediaStream | undefined;
    let t: number | undefined;
    navigator.mediaDevices
      ?.getUserMedia({ audio: true })
      .then((s) => {
        stream = s;
        const r = new MediaRecorder(s);
        r.ondataavailable = (e) => e.data.size && chunks.current.push(e.data);
        r.start(1000);
        rec.current = r;
        t = window.setInterval(() => setSecs((x) => x + 1), 1000);
      })
      .catch(() => { toast(l.mic_denied); go('upload'); });
    return () => { window.clearInterval(t); stream?.getTracks().forEach((x) => x.stop()); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const stop = () => {
    const r = rec.current;
    if (!r) return go('upload');
    r.onstop = () => {
      const type = r.mimeType || 'audio/webm';
      const ext = type.includes('mp4') ? 'm4a' : type.includes('ogg') ? 'ogg' : 'webm';
      upload(new Blob(chunks.current, { type }), `recording-${new Date().toISOString().slice(0, 16).replace(':', '')}.${ext}`).catch(() => go('upload'));
    };
    r.stop();
    r.stream.getTracks().forEach((x) => x.stop());
  };

  return (
    <>
      <h1>{l.recording}</h1>
      <div className="rec">
        <div className="rec-dot" aria-hidden="true" />
        <div className="timer">{hhmmss(secs)}</div>
        <button className="btn btn-primary" type="button" onClick={stop}>{l.stop}</button>
      </div>
    </>
  );
}
