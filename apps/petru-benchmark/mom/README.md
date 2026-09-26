# MoM benchmark transcripts

Fictional meeting transcripts from a private multidisciplinary hospital in Chișinău, used to benchmark text models that turn raw transcripts into Minutes of Meeting. Every person, patient, company, amount, and event is invented. Contains no real meeting data.

Each file `transcripts/<id>.json` matches `momTranscriptSchema` in `shared/mom.ts`. Run `bun test tests/mom-data.test.ts` after editing.

| Field | Purpose |
| --- | --- |
| `id` | `<meetingType>-<two digits>`, same as the file name. |
| `meetingType` | `clinical`, `financial`, `administrative`, `executive`, `operational`, or `crisis`. |
| `title`, `scenario` | For people reading the benchmark. Never sent to models. |
| `transcript` | The only text models receive. |
| `answerKey.items` | What a correct MoM must contain. Only the judge sees it. |
| `answerKey.traps` | Mistakes a careless MoM would make. Only the judge sees it. |

## Transcript format: raw ASR output

The transcripts imitate what our Whisper pipeline returns for a real recording:

- No speaker labels, stage directions, timestamps, titles, or agenda. Speaker changes are only implied by content: a question, an answer, an address by name (“Doamna Ceban, vă rog…”).
- Paragraphs are ASR chunk boundaries of roughly 45 seconds, about 90–130 words, joined by one blank line. A boundary can fall mid-sentence or mid-turn.
- Mostly correct punctuation, but mild ASR artifacts: a few missing diacritics (`sa`, `si`), some lowercase sentence starts, repeated words (`noi noi am`), hesitations (`ăăă`, `mmm`, `эээ`), false starts and cut-off words, and at most two or three plausibly misrecognized non-critical words per transcript. Never corrupt the facts in the answer key unless an item deliberately records that uncertainty.
- Russian speech appears in Cyrillic most of the time, sometimes transliterated in Latin script (`davai`, `normalno`), as Whisper does.
- 1,100–2,000 words for a regular transcript (8–15 minutes of speech). The long transcript is 5,500–7,000 words.

## Language: Moldovan workplace speech

Romanian is the base language. Speakers switch to Russian or English the way colleagues in Chișinău do:

- **Russian fillers and discourse markers** inside Romanian sentences: `davai`, `hai davai`, `karoce`/`короче`, `vaabșce`/`вообще`, `normalno`, `ну`, `значит`, `в общем`, `слушай`, `ладно`, `так`, `тоесть`, `как бы`, `просто`, `вот`.
- **Whole Russian sentences or turns**, especially from older staff or a Russian-speaking colleague, with the others answering in Romanian. Some important facts must appear only in the Russian part.
- **Russian workplace and medical vocabulary** used as loanwords: `spravka`/`справка`, `napravlenie`/`направление`, `vîpiska`/`выписка`, `planiorka`/`планёрка`, `otpusk`, `bolnicinîi`/`больничный`, `zavotdelenia`/`заведующий отделением`, `glavvrăci`, `dejurstvo`/`дежурство`, `obhod`/`обход`, `palata`, `procedurnaia`, `nakladnaia`/`накладная`, `sčiot`/`счёт`, `smeta`/`смета`, `dogovor`/`договор`, `ostatok`/`остаток`, `analizî`/`анализы`, `УЗИ`, `ЭКГ`, `КТ`, `капельница`.
- **Moldovan calques and colloquial phrasing**: “Tot normal?”, “la noi tot bine”, “a da la analize”, “a lua sub control”, “pe moment”, “deamu”, “amu”, “aista/asta-i”, “pîn' la”, “ieste”, “închidem întrebarea”, “să facem așa”.
- **English professional terms**: `deadline`, `follow-up`, `update`, `feedback`, `KPI`, `budget`, `call`, `meeting`, `staff`, `workflow`, `outsourcing`, `benchmark`, `compliance`, `turnover`, `cash-flow`, `stent`, `bundle`, `checklist`, `triage`.
- **Institutional context**: CNAM and polița de asigurare obligatorie de asistență medicală, AMDM, ANSP, Ministerul Sănătății, CNEAS accreditation, JCI, protocoale clinice naționale (PCN), private insurers, amounts in lei (MDL) and euro, 112 and AMU (asistența medicală urgentă), ATI, UPU/DMU, bloc operator, sterilizare (CSSD), fișa de observație clinică, epicriză, consimțământ informat.

Use real medical terminology, abbreviations, drug names with doses, laboratory values with units, and numbers spoken as people say them (“o sută douăzeci pe optzeci”, “doi virgulă cinci mililitri”, “trei sute cincizeci de mii de lei”). Mix spelled-out and digit numbers as ASR does.

## What each transcript must test

- **Decisions** clearly agreed, alongside ideas that are only discussed.
- **At least one rejected or postponed proposal** that a careless MoM would list as a decision.
- **At least one reversal**: a figure, date, owner, or choice corrected later (“nu, stați, nu douăzeci, douăzeci și cinci”; “anulăm ce am zis mai devreme”).
- **Actions with explicit owners and deadlines**, and **at least one action with no owner and one with no deadline**. The answer key uses `null` there.
- **Relative deadlines** (“până vineri”, “săptămâna viitoare”, “până la sfîrșitul lunii”). The key keeps them relative unless the speech states a calendar date.
- **A negation that changes meaning** (“nu mai administrăm”, “fără contrast”, “nu e alergic… ba nu, e alergic la penicilină”).
- **An uncertain or ambiguous point** that should appear as an open question, not a resolved fact.
- Small talk, repetition, and off-topic remarks that the MoM should drop.

## Answer key

Write the key in English. Quote Romanian or Russian terms where exact wording matters. Each item states one checkable fact:

- `kind`: `decision`, `action`, `finding` (reported data, results, costs, measurements), `risk`, or `open_question`.
- `owner` and `deadline` are required for actions: the person or role and the time exactly as stated, or `null` when the recording does not state them.
- `critical: true` for items whose loss or distortion would harm patients, money, or accountability (usually decisions, key actions, doses, amounts). Use it on roughly a third of the items.
- IDs: `D1…` decisions, `A1…` actions, `F1…` findings, `R1…` risks, `Q1…` open questions, `T1…` traps.

A regular transcript has 12–25 items and 3–6 traps. The long transcript has 30–45 items and 6–10 traps. Traps describe the wrong output precisely, for example: “Lists switching to supplier Farmaprim as a decision; it was proposed and rejected”, or “Reports the budget as 20 000 lei; it was corrected to 25 000 lei”.
