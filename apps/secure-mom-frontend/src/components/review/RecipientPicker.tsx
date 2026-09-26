import { useEffect, useRef, useState } from 'react';
import { DIRECTORY, INTERNAL_DOMAIN, type Person } from '../../data/directory';
import { initials } from '../../domain/transcript';
import { useApp } from '../../state/store';
import { Icon } from '../ui/Icon';

const INTERNAL = new RegExp(`^[^@\\s]+${INTERNAL_DOMAIN.replace('.', '\\.')}$`, 'i');

/** "Will be shared with: (avatars) N participants + Add" → popover with chips, directory search, internal-only emails. */
export function RecipientPicker() {
  const { s, l, setRecipients } = useApp();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const box = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const list = s.recipients;
  const n = list.length;

  useEffect(() => {
    if (!open) return;
    input.current?.focus();
    const off = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener('mousedown', off);
    return () => document.removeEventListener('mousedown', off);
  }, [open]);

  const have = new Set(list.map((p) => p.email));
  const needle = q.trim().toLowerCase();
  const matches = DIRECTORY.filter((p) => !have.has(p.email) && (!needle || `${p.name} ${p.email}`.toLowerCase().includes(needle))).slice(0, 4);
  const isMail = needle.includes('@');
  const mailOk = isMail && INTERNAL.test(needle) && !have.has(needle);

  const add = (p: Person) => { setRecipients([...list, p]); setQ(''); input.current?.focus(); };
  const remove = (i: number) => setRecipients(list.filter((_, k) => k !== i));
  const first = () => (matches[0] ? add(matches[0]) : mailOk && add({ name: needle.split('@')[0], email: needle }));

  return (
    <div className="rcp" ref={box}>
      <span className="rcl">{l.to}:</span>
      <button type="button" className="rcbtn" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {list.slice(0, 4).map((p) => <span key={p.email} className="av xs">{initials(p.name)}</span>)}
        {n > 4 && <span className="av xs more">+{n - 4}</span>}
        <b>{l.rc_n(n)}</b>
        <span className="rcadd">＋ {l.rc_add}</span>
      </button>
      {open && (
        <div className="rcpop" role="dialog" aria-label={l.to} onKeyDown={(e) => e.key === 'Escape' && setOpen(false)}>
          <div className="rcchips">
            {list.map((p, i) => (
              <span key={p.email} className="rchip" title={p.email}>
                <span className="av xs">{initials(p.name)}</span>{p.name}
                <button type="button" aria-label={`× ${p.name}`} onClick={() => remove(i)}>×</button>
              </span>
            ))}
          </div>
          <label className="sbox rcin">
            <Icon name="search" />
            <input ref={input} autoComplete="off" placeholder={l.rc_ph} value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), first())} />
          </label>
          <ul className="rclist">
            {matches.map((p) => (
              <li key={p.email}>
                <button type="button" onClick={() => add(p)}>
                  <span className="av xs">{initials(p.name)}</span>
                  <span>{p.name}<small>{p.email}</small></span>
                </button>
              </li>
            ))}
            {mailOk && <li><button type="button" onClick={() => add({ name: needle.split('@')[0], email: needle })}>＋ {needle}</button></li>}
            {isMail && !needle.endsWith(INTERNAL_DOMAIN) && <li className="rcerr">{l.rc_ext}</li>}
          </ul>
          <div className="rcfoot">
            <small><Icon name="lock" />{l.rc_hint}</small>
            <button type="button" className="btn btn-export rcok" onClick={() => { setOpen(false); setQ(''); }}>{l.rc_done}</button>
          </div>
        </div>
      )}
    </div>
  );
}
