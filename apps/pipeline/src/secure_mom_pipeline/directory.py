"""Small server-owned directory used by offline portal autocomplete."""

from __future__ import annotations

from .models import DirectoryPerson


PEOPLE: tuple[DirectoryPerson, ...] = (
    DirectoryPerson(
        name="Vasile Roibu",
        email="vasile.roibu@medpark.test",
        title="Coordonator operațional",
    ),
    DirectoryPerson(
        name="Ana Ionescu",
        email="ana.ionescu@medpark.test",
        title="Director financiar",
    ),
    DirectoryPerson(
        name="dr. Ciobanu",
        email="v.ciobanu@medpark.test",
        title="Medic",
    ),
    DirectoryPerson(
        name="dr. Rusu",
        email="a.rusu@medpark.test",
        title="Medic",
    ),
    DirectoryPerson(
        name="farmacist clinician Lungu",
        email="m.lungu@medpark.test",
        title="Farmacie clinică",
    ),
    DirectoryPerson(
        name="asistenta-șefă Moraru",
        email="e.moraru@medpark.test",
        title="Asistență medicală",
    ),
    DirectoryPerson(
        name="dr. Popa",
        email="i.popa@medpark.test",
        title="Director medical",
    ),
    DirectoryPerson(
        name="dr. Ceban",
        email="d.ceban@medpark.test",
        title="Chirurgie",
    ),
    DirectoryPerson(
        name="Secretariat Consiliul medical",
        email="consiliu@medpark.test",
    ),
    DirectoryPerson(
        name="dr. Munteanu",
        email="s.munteanu@medpark.test",
        title="Anestezie",
    ),
)


def search_people(query: str, *, limit: int = 8) -> list[DirectoryPerson]:
    """Return local matches by name, email, or title; never contacts a network service."""

    needle = query.strip().casefold()
    if not needle:
        return list(PEOPLE[:limit])
    return [
        person
        for person in PEOPLE
        if needle
        in " ".join((person.name, person.email, person.title or "")).casefold()
    ][:limit]
