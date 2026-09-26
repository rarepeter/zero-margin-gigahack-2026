import { API_MODE } from '../../api';
import type { LangCode } from '../../i18n';
import { useApp } from '../../state/store';

const LANGS: [LangCode, string][] = [['ro', 'RO'], ['ru', 'РУ'], ['en', 'EN']];

export function SecurityBar() {
  const { s, l, setLang } = useApp();
  return (
    <div className="secbar" role="status">
      <svg className="shield" width="26" height="28" viewBox="0 0 26 28" aria-hidden="true">
        <path d="M13 1.5l10.5 4v8c0 6.6-4.4 11.3-10.5 13-6.1-1.7-10.5-6.4-10.5-13v-8z" fill="currentColor" />
        <path d="M8.2 14l3.3 3.3 6.3-6.6" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <strong>{l.secure}</strong>
      {API_MODE === 'mock' && <span className="mockbadge" title="VITE_API_MODE=mock">{l.mock_badge}</span>}
      <div className="seg seg-top" role="group" aria-label="Limba / Язык / Language">
        {LANGS.map(([k, label]) => (
          <button key={k} type="button" aria-pressed={s.lang === k} onClick={() => setLang(k)}>{label}</button>
        ))}
      </div>
    </div>
  );
}
