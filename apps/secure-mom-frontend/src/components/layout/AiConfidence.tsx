import { useApp } from '../../state/store';
import { Icon } from '../ui/Icon';

function Ring({ r, p, cls }: { r: number; p: number; cls: string }) {
  const c = 2 * Math.PI * r;
  const style = { strokeDasharray: c.toFixed(1), '--off': (c * (1 - p / 100)).toFixed(1), '--c': c.toFixed(1) } as React.CSSProperties;
  return (
    <>
      <circle className="rt" cx="44" cy="44" r={r} />
      <circle className={`rv2 ${cls}`} cx="44" cy="44" r={r} style={style} />
    </>
  );
}

/** Sidebar card: transcript and summary confidence, without review suggestions. */
export function AiConfidence() {
  const { s, l } = useApp();
  const quality = s.reviewContext?.quality;
  const tx = quality?.transcriptConfidence == null ? null : Math.round(quality.transcriptConfidence * 100);
  const sm = quality?.momConfidence == null ? null : Math.round(quality.momConfidence * 100);
  const avg = tx !== null && sm !== null ? Math.round((tx + sm) / 2) : null;

  return (
    <div className="aic">
      <div className="aic-h"><Icon name="spark" /><span>{l.cf_t}</span></div>
      {tx === null || sm === null ? (
        <p className="aic-wip"><i className="d" />{l.cf_wip}</p>
      ) : (
        <div className="aic-b">
          <div className="aic-g">
            <svg className="rings anim" width="88" height="88" viewBox="0 0 88 88" aria-hidden="true">
              <defs>
                <linearGradient id="gT" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#00E0D6" /><stop offset="1" stopColor="#00A2A4" /></linearGradient>
                <linearGradient id="gS" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#FFD166" /><stop offset="1" stopColor="#FF7A59" /></linearGradient>
              </defs>
              <Ring r={38} p={tx} cls="r-t" />
              <Ring r={28} p={sm} cls="r-t" />
            </svg>
            <div className="aic-c"><b>{avg}<small>%</small></b></div>
          </div>
          <ul className="aic-l">
            <li><i className="d d-t" /><span>{l.cf_tx}</span><b>{tx}%</b></li>
            <li><i className="d d-t" /><span>{l.cf_sum}</span><b>{sm}%</b></li>
          </ul>
        </div>
      )}
    </div>
  );
}
