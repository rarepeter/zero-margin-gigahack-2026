// Local, offline export of the reviewed minutes: print-to-PDF and JSON download. Nothing leaves the browser.
import { fmtDate, type Mom } from '../domain/mom';
import type { Dict } from '../i18n';

const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);

export function downloadJson(mom: Mom, filename = 'proces-verbal.json') {
  const url = URL.createObjectURL(new Blob([JSON.stringify(mom, null, 2)], { type: 'application/json' }));
  const a = Object.assign(document.createElement('a'), { href: url, download: filename });
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function printPdf(mom: Mom, l: Dict) {
  const h = mom.header;
  const li = (xs: string[]) => (xs.length ? `<ul>${xs.map((x) => `<li>${x}</li>`).join('')}</ul>` : '');
  const html = `<!doctype html><html><head><meta charset="utf-8"><title>${esc(h.subject)}</title>
<style>body{font:12pt/1.5 system-ui,Arial,sans-serif;color:#1A2B2D;max-width:720px;margin:32px auto;padding:0 24px}
h1{font-size:18pt;margin:0 0 4px}h2{font-size:12pt;margin:22px 0 6px}.m{color:#5F676D;margin:0 0 16px}li{margin-bottom:6px}
q{color:#5F676D;font-style:italic}</style></head><body>
<h1>${esc(h.subject)}</h1><p class="m">${fmtDate(h.date)}${h.duration_min ? ` · ${h.duration_min} min` : ''} · ${esc(l.types[h.meeting_type] ?? h.meeting_type)}</p>
<h2>${esc(l.l_part)}</h2><p>${esc((h.participants_mentioned ?? []).map((p) => p.name).join(', '))}</p>
<h2>${esc(l.l_what)}</h2><p>${esc(mom.summary)}</p>${li(mom.findings.map((f) => esc(f.text)))}
<h2>${esc(l.l_sol)}</h2>${li(mom.decisions.map((d) => `<b>${esc(d.id)}.</b> ${esc(d.text)} <i>(${esc(l.status[d.status] ?? d.status)})</i>`))}
<h2>${esc(l.l_next)}</h2>${li(mom.actions.map((a) => `<b>${esc(a.text)}</b> — ${esc(a.owner ?? l.unassigned)}, ${esc(a.deadline.resolved ? fmtDate(a.deadline.resolved) : a.deadline.spoken ?? l.nodate)}`))}
${mom.risks.length || mom.open_questions.length ? `<h2>${esc(l.l_risk)}</h2>${li([...mom.risks, ...mom.open_questions].map((r) => esc(r.text)))}` : ''}
<script>window.onload=()=>{window.print()}</script></body></html>`;
  const w = window.open('', '_blank');
  if (!w) return;
  w.document.write(html);
  w.document.close();
}
