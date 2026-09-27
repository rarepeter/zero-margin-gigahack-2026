// Hospital staff directory used by the recipient picker.
// TODO(backend): replace with a local directory endpoint (e.g. GET /api/v1/directory?q=) — never a cloud service.
export interface Person { name: string; email: string; title?: string }

export const DIRECTORY: Person[] = [
  { name: 'dr. Ciobanu', email: 'v.ciobanu@medpark.test' },
  { name: 'dr. Rusu', email: 'a.rusu@medpark.test' },
  { name: 'farmacist clinician Lungu', email: 'm.lungu@medpark.test' },
  { name: 'asistenta-șefă Moraru', email: 'e.moraru@medpark.test' },
  { name: 'dr. Popa', email: 'i.popa@medpark.test', title: 'Director medical' },
  { name: 'dr. Ceban', email: 'd.ceban@medpark.test', title: 'Chirurgie' },
  { name: 'Secretariat Consiliul medical', email: 'consiliu@medpark.test' },
  { name: 'dr. Munteanu', email: 's.munteanu@medpark.test', title: 'Anestezie' },
  { name: 'Farmacia spitalului', email: 'farmacie@medpark.test' },
];

export const INTERNAL_DOMAIN = '@medpark.test';

/** Default recipients = meeting participants that we can match in the directory (unknown voices have no address). */
export function defaultRecipients(participantNames: string[]): Person[] {
  const norm = (s: string) => s.toLowerCase();
  return DIRECTORY.filter((p) => participantNames.some((n) => norm(p.name).includes(norm(n)) || norm(n).includes(norm(p.name.split(' ').pop() ?? ''))));
}
