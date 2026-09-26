import { SegmentRow } from '../components/review/SegmentRow';
import { Icon } from '../components/ui/Icon';
import { useApp } from '../state/store';

const Sk = ({ i }: { i: number }) => (
  <div className="skr">
    <i className="sk c" />
    <div>
      <i className="sk" style={{ width: `${30 + ((i * 9) % 30)}%` }} />
      <i className="sk" style={{ width: `${82 - ((i * 7) % 20)}%` }} />
      <i className="sk" style={{ width: `${55 + ((i * 5) % 25)}%` }} />
    </div>
  </div>
);

function Tabs({ items }: { items: string[] }) {
  return (
    <div className="ptabs" role="tablist">
      {items.map((x, i) => (
        <button key={x} type="button" role="tab" className={i === 0 ? 'on' : 'dis'} aria-selected={i === 0} disabled>{x}</button>
      ))}
    </div>
  );
}

/** Same two-panel layout as Review, so nothing jumps when results arrive. */
export function ProcessingScreen() {
  const { s, l } = useApp();
  const segs = s.segments;
  return (
    <>
      <h1 className="sr-only">{l.min_t}</h1>
      <div className="board">
        <section className="pane" aria-label={l.lt_tx}>
          <div className="tbar"><Tabs items={[l.lt_tx, l.lt_det]} /></div>
          <div className="pbody pad">
            <p className="skcap">{l.pr_live}</p>
            <ol className="tl live">
              {[0, 1].map((i) => (segs[i] ? <SegmentRow key={i} seg={segs[i]} className="slot in" /> : <li key={i} className="slot"><Sk i={i} /></li>))}
            </ol>
            {[2, 3, 4].map((i) => <Sk key={i} i={i} />)}
            <p className={`skcount${segs.length ? ' ok' : ''}`}>{segs.length ? <><Icon name="check" />{segs.length} · {l.pr_rdy}</> : ''}</p>
          </div>
        </section>
        <section className="pane" aria-label={l.rt_sum}>
          <div className="tbar"><Tabs items={[l.rt_sum]} /></div>
          <div className="pbody pad">
            <p className="skcap">{l.pr_wait}</p>
            {[l.l_part, l.l_what, l.l_sol, l.l_next].map((h, i) => (
              <section className="lsec" key={h}>
                <h4><i className="ring" />{h}</h4>
                <div className="lbody"><i className="sk" style={{ width: `${88 - i * 9}%` }} /><i className="sk" style={{ width: `${62 + i * 6}%` }} /></div>
              </section>
            ))}
          </div>
        </section>
      </div>
      <div className="bar2">
        <div className="to">{l.proc_s}</div>
        <button className="btn btn-ghost" type="button" disabled>{l.discard}</button>
        <button className="btn btn-export" type="button" disabled><Icon name="down" />{l.exp}</button>
      </div>
    </>
  );
}
