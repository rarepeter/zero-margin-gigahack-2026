import type { DirectoryPerson } from '../api';

export type Person = DirectoryPerson;

export const INTERNAL_DOMAIN = '@medpark.test';

/** Offline UI fallback. The live API exposes the same demo people from its local directory. */
export const DEMO_DIRECTORY: Person[] = [
  { name: 'Vasile Roibu', email: 'vasile.roibu@medpark.test', title: 'Coordonator operațional' },
  { name: 'Ana Ionescu', email: 'ana.ionescu@medpark.test', title: 'Director financiar' },
  { name: 'dr. Ciobanu', email: 'v.ciobanu@medpark.test', title: 'Medic' },
  { name: 'dr. Rusu', email: 'a.rusu@medpark.test', title: 'Medic' },
  { name: 'farmacist clinician Lungu', email: 'm.lungu@medpark.test', title: 'Farmacie clinică' },
  { name: 'asistenta-șefă Moraru', email: 'e.moraru@medpark.test', title: 'Asistență medicală' },
  { name: 'dr. Popa', email: 'i.popa@medpark.test', title: 'Director medical' },
  { name: 'dr. Ceban', email: 'd.ceban@medpark.test', title: 'Chirurgie' },
  { name: 'dr. Munteanu', email: 's.munteanu@medpark.test', title: 'Anestezie' },
  { name: 'Secretariat Consiliul medical', email: 'consiliu@medpark.test' },
];

export function demoDirectoryMatches(query: string, limit = 8): Person[] {
  const needle = query.trim().toLocaleLowerCase();
  const matches = DEMO_DIRECTORY.filter((person) => (
    !needle || `${person.name} ${person.email} ${person.title ?? ''}`.toLocaleLowerCase().includes(needle)
  ));
  return (matches.length ? matches : DEMO_DIRECTORY).slice(0, limit);
}
