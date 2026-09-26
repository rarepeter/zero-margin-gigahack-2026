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

/** Sidebar card: transcript/summary confidence rings + shortcut to the first red word. */
export function AiConfidence() {
  const { s, l, left } = useApp();
  const verified = left === 0;
  const quality = s.reviewContext?.quality;
  const tx = quality ? Math.round(quality.transcriptConfidence * 100) : null;
  const sm = quality ? Math.round(quality.momConfidence * 100) : null;
  const avg = tx !== null && sm !== null ? Math.round((tx + sm) / 2) : null;

  const goFix = () => {
    const el = document.querySelector<HTMLElement>('.fix');
    if (!el) return;
    el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    window.setTimeout(() => el.click(), 350);
  };

  return (
    <div className={`aic${verified ? ' ver' : ''}`} title={l.cf_note}>
      <div className="aic-h"><Icon name="spark" /><span>{l.cf_t}</span></div>
      {tx !== null && sm !== null && (
        <div className="aic-b">
          <div className="aic-g">
            <svg className="rings anim" width="88" height="88" viewBox="0 0 88 88" aria-hidden="true">
              <defs>
                <linearGradient id="gT" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#00E0D6" /><stop offset="1" stopColor="#00A2A4" /></linearGradient>
                <linearGradient id="gS" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#FFD166" /><stop offset="1" stopColor="#FF7A59" /></linearGradient>
              </defs>
              <Ring r={38} p={tx} cls="r-t" />
              <Ring r={28} p={sm} cls={verified ? 'r-t' : 'r-s'} />
            </svg>
            <div className="aic-c">{verified ? <Icon name="check" /> : <b>{avg}<small>%</small></b>}</div>
          </div>
          <ul className="aic-l">
            <li><i className="d d-t" /><span>{l.cf_tx}</span><b>{tx}%</b></li>
            <li><i className={`d ${verified ? 'd-t' : 'd-s'}`} /><span>{l.cf_sum}</span><b>{sm}%</b></li>
          </ul>
        </div>
      )}
      {left ? (
        <button type="button" className="aic-go" onClick={goFix}><Icon name="alert" /><span>{l.st_rev(left)}</span><em>→</em></button>
      ) : (
        <div className="aic-ok"><Icon name="check" /><span>{l.cf_ver}</span></div>
      )}
    </div>
  );
}
