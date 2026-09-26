// Local, offline export of the reviewed minutes. The browser's native print
// dialog writes the PDF; no document content is sent to a service.
import { fmtDate, type Mom } from '../domain/mom';
import type { Dict, LangCode } from '../i18n';

const esc = (s: string) => s.replace(/[&<>\"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);

export function downloadJson(mom: Mom, filename = 'proces-verbal.json') {
  const url = URL.createObjectURL(new Blob([JSON.stringify(mom, null, 2)], { type: 'application/json' }));
  const a = Object.assign(document.createElement('a'), { href: url, download: filename });
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const section = (title: string, content: string) => content ? `<section class="section"><h2>${esc(title)}</h2>${content}</section>` : '';
const list = (items: string[], className = 'items') => items.length ? `<ul class="${className}">${items.map((item) => `<li>${item}</li>`).join('')}</ul>` : '';

/** Opens a self-contained, print-optimised version of an already approved MoM. */
export function printPdf(mom: Mom, l: Dict, lang: LangCode) {
  const h = mom.header;
  const participants = (h.participants_mentioned ?? []).map((p) => esc(p.role ? `${p.name} — ${p.role}` : p.name)).join(', ');
  const date = fmtDate(h.date);
  const facts = [
    `${esc(l.k_type)}: <strong>${esc(l.types[h.meeting_type] ?? h.meeting_type)}</strong>`,
    date ? `${esc(l.d_date)}: <strong>${esc(date)}</strong>` : '',
    h.duration_min ? `${esc(l.k_dur)}: <strong>${h.duration_min} min</strong>` : '',
  ].filter(Boolean).join('<span class="fact-sep">•</span>');
  const topics = list(mom.topics.map((topic) => `<strong>${esc(topic.title)}</strong><span>${esc(topic.text)}</span>`), 'topic-list');
  const findings = list(mom.findings.map((finding) => esc(finding.text)));
  const decisions = list(mom.decisions.map((decision) => `<span class="decision-id">${esc(decision.id)}</span><span class="status status-${esc(decision.status)}">${esc(l.status[decision.status] ?? decision.status)}</span><span>${esc(decision.text)}</span>`), 'decision-list');
  const actions = mom.actions.length ? `<div class="action-wrap"><table><thead><tr><th>${esc(l.pdf_action)}</th><th>${esc(l.own)}</th><th>${esc(l.due)}</th></tr></thead><tbody>${mom.actions.map((action) => `<tr><td>${esc(action.text)}</td><td>${esc(action.owner ?? l.unassigned)}</td><td>${esc(action.deadline.resolved ? fmtDate(action.deadline.resolved) : action.deadline.spoken ?? l.nodate)}</td></tr>`).join('')}</tbody></table></div>` : '';
  const risks = list(mom.risks.map((risk) => esc(risk.text)));
  const questions = list(mom.open_questions.map((question) => esc(question.text)));
  const html = `<!doctype html><html lang="${lang}"><head><meta charset="utf-8"><title>${esc(h.subject)}</title>
<style>
  @page { size: A4; margin: 16mm 15mm 18mm; }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; background: #fff; color: #193034; }
  body { font-family: Arial, 'Segoe UI', sans-serif; font-size: 10.5pt; line-height: 1.52; }
  .doc { max-width: 180mm; margin: 0 auto; }
  .masthead { display: flex; justify-content: space-between; gap: 12mm; align-items: center; padding: 0 0 5mm; border-bottom: 1.5pt solid #008286; color: #53676a; font-size: 7.8pt; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
  .masthead .local { color: #008286; text-align: right; }
  h1 { margin: 8mm 0 2mm; color: #173235; font-size: 22pt; line-height: 1.15; letter-spacing: -.025em; }
  .facts { display: flex; flex-wrap: wrap; gap: 1.8mm; align-items: center; margin: 0 0 6mm; color: #52666a; font-size: 9pt; }
  .fact-sep { color: #9aadaf; }
  .participants { margin: 0 0 7mm; padding: 3.5mm 4mm; background: #f1f7f7; border-left: 2.5pt solid #8acccd; color: #3f5659; font-size: 9pt; }
  .participants strong { color: #173235; }
  .section { margin: 0 0 6.5mm; break-inside: avoid-page; }
  h2 { margin: 0 0 2.5mm; padding-bottom: 1.6mm; border-bottom: 1px solid #d6e3e4; color: #007579; font-size: 8.5pt; letter-spacing: .09em; text-transform: uppercase; }
  p { margin: 0; }
  ul { margin: 0; padding: 0; list-style: none; }
  .items li { position: relative; margin: 0 0 2.2mm; padding: 0 0 0 4mm; break-inside: avoid; }
  .items li::before { content: ''; position: absolute; left: 0; top: .68em; width: 1.5mm; height: 1.5mm; border-radius: 50%; background: #008286; }
  .topic-list { display: grid; gap: 2.4mm; }
  .topic-list li { padding: 3.2mm 4mm; border: 1px solid #d9e7e8; border-radius: 2mm; break-inside: avoid; }
  .topic-list strong, .topic-list span { display: block; }
  .topic-list strong { margin-bottom: .8mm; color: #173235; }
  .topic-list span { color: #4c6064; }
  .decision-list { display: grid; gap: 2.3mm; }
  .decision-list li { display: grid; grid-template-columns: auto auto 1fr; gap: 2mm; align-items: start; padding: 3.1mm 3.5mm; background: #f6f9f9; border-left: 2.5pt solid #008286; break-inside: avoid; }
  .decision-id { color: #00666a; font-family: 'Courier New', monospace; font-size: 8.5pt; font-weight: 700; }
  .status { padding: .35mm 1.5mm; border-radius: 1mm; font-size: 7pt; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; white-space: nowrap; }
  .status-decided { background: #dff3e7; color: #075d3d; }.status-proposed { background: #fff0d7; color: #875007; }.status-revoked { background: #f9e1e1; color: #9b3035; }
  .action-wrap { border: 1px solid #d6e3e4; border-radius: 2mm; overflow: hidden; }
  table { width: 100%; border-collapse: collapse; }
  th { padding: 2.5mm 3mm; background: #173235; color: #fff; font-size: 7.6pt; letter-spacing: .06em; text-align: left; text-transform: uppercase; }
  td { padding: 2.7mm 3mm; vertical-align: top; border-top: 1px solid #e0eaeb; }
  td:nth-child(2), td:nth-child(3) { width: 24%; color: #486064; font-size: 9.2pt; }
  tr { break-inside: avoid; }
  .footer { margin-top: 8mm; padding-top: 3mm; border-top: 1px solid #d6e3e4; color: #607477; font-size: 7.5pt; }
  @media print { .section { break-inside: avoid-page; } thead { display: table-header-group; } }
</style></head><body><main class="doc">
<header class="masthead"><span>${esc(l.pdf_confidential)}</span><span class="local">${esc(l.pdf_local)}</span></header>
<h1>${esc(h.subject)}</h1><div class="facts">${facts}</div>
${participants ? `<p class="participants"><strong>${esc(l.l_part)}:</strong> ${participants}</p>` : ''}
${section(l.min_t, `<p>${esc(mom.summary)}</p>`)}
${section(l.pdf_topics, topics)}
${section(l.pdf_findings, findings)}
${section(l.l_sol, decisions)}
${section(l.l_next, actions)}
${section(l.pdf_risks, risks)}
${section(l.pdf_questions, questions)}
<footer class="footer">${esc(l.pdf_confidential)} · ${esc(l.pdf_local)} · ${esc(l.pdf_approved)}</footer>
</main><script>window.onload=()=>{window.print()}</script></body></html>`;
  const w = window.open('', '_blank');
  if (!w) return;
  w.document.write(html);
  w.document.close();
}
