import { useEffect, useRef, useState } from 'react';
import { api } from '../../api';
import { demoDirectoryMatches, INTERNAL_DOMAIN, type Person } from '../../data/directory';
import { initials } from '../../domain/transcript';
import { useApp } from '../../state/store';
import { Icon } from '../ui/Icon';

const INTERNAL = new RegExp(`^[^@\\s]+${INTERNAL_DOMAIN.replace('.', '\\.')}$`, 'i');
const EMAIL = /^[a-z0-9][a-z0-9._%+\-]*@[a-z0-9][a-z0-9.\-]*$/i;

interface Props {
  recipients: Person[];
  onChange(recipients: Person[]): void;
  disabled?: boolean;
  /** Defaults to "Will be shared with". */
  label?: string;
}

/** "Will be shared with: (avatars) N participants + Add" → popover with chips, directory search, internal-only emails. */
export function RecipientPicker({ recipients: list, onChange, disabled = false, label }: Props) {
  const { l } = useApp();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const [directory, setDirectory] = useState<Person[]>([]);
  const box = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const n = list.length;

  useEffect(() => {
    if (!open) return;
    input.current?.focus();
    const off = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener('mousedown', off);
    return () => document.removeEventListener('mousedown', off);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    let alive = true;
    const timer = window.setTimeout(() => {
      api.searchDirectory(q).then((people) => { if (alive) setDirectory(people.length ? people : demoDirectoryMatches(q)); }).catch(() => { if (alive) setDirectory(demoDirectoryMatches(q)); });
    }, 120);
    return () => { alive = false; window.clearTimeout(timer); };
  }, [open, q]);

  const have = new Set(list.map((p) => p.email));
  const needle = q.trim().toLowerCase();
  const matches = directory.filter((p) => !have.has(p.email)).slice(0, 4);
  const mailOk = EMAIL.test(needle) && !have.has(needle);

  const add = (p: Person) => { if (!disabled) { onChange([...list, p]); setQ(''); input.current?.focus(); } };
  const remove = (i: number) => { if (!disabled) onChange(list.filter((_, k) => k !== i)); };
  const first = () => (matches[0] ? add(matches[0]) : mailOk && add({ name: needle.split('@')[0], email: needle }));

  return (
    <div className="rcp" ref={box}>
      <span className="rcl">{label ?? l.to}:</span>
      <button type="button" className="rcbtn" aria-expanded={open} disabled={disabled} onClick={() => setOpen((o) => !o)}>
        {list.slice(0, 4).map((p) => <span key={p.email} className="av xs">{initials(p.name)}</span>)}
        {n > 4 && <span className="av xs more">+{n - 4}</span>}
        <b>{l.rc_n(n)}</b>
        <span className="rcadd">＋ {l.rc_add}</span>
      </button>
      {open && (
        <div className="rcpop" role="dialog" aria-label={label ?? l.to} onKeyDown={(e) => e.key === 'Escape' && setOpen(false)}>
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
            {mailOk && !INTERNAL.test(needle) && <li className="rcerr">{l.rc_ext}</li>}
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
