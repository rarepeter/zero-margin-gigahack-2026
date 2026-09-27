"""Moldova Medical Speech Lexicon (MMSL): hotword prompt and term evidence.

Following the lexicon's own usage notes:

- Before ASR (lexicon-assisted mode only): about 224 Whisper tokens of
  `asr_hotwords`, sampled across categories, become FraPiz's initial prompt.
- After ASR: `normalisation_map` rows are matched against the text, longest
  first and without overlaps. The text itself is never changed; matches are
  recorded as evidence. As in MedSpeech `classify_language`, a Latin-script
  FraPiz result with matches stays on the Romanian route when Whisper's
  language detection says Russian.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from itertools import zip_longest
from pathlib import Path
from typing import Any


# Whisper uses about one token per three characters of Romanian medical text;
# whisper.cpp keeps the last 224 prompt tokens.
PROMPT_CHARACTERS = 600


def match_key(text: str) -> str:
    """MMSL match_key_rule: lowercase, ş/ţ to ș/ț, no diacritics, single spaces."""
    text = (text or "").lower().replace("ş", "ș").replace("ţ", "ț")
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    text = re.sub(r"[^\w\-]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True, slots=True)
class Lexicon:
    rows: tuple[tuple[str, dict[str, Any]], ...]
    prompt: str

    @classmethod
    def load(cls, path: Path) -> Lexicon:
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = [
            (key, row)
            for row in data.get("normalisation_map", [])
            if len(key := match_key(row.get("match_key") or row.get("spoken_form") or "")) >= 4
        ]
        rows.sort(key=lambda item: len(item[0]), reverse=True)
        return cls(rows=tuple(rows), prompt=_hotword_prompt(data.get("asr_hotwords") or {}))

    def evidence(self, text: str, max_hits: int = 20) -> list[dict[str, str]]:
        """Non-overlapping lexicon matches in `text`, longest first."""
        haystack = f" {match_key(text)} "
        hits: list[dict[str, str]] = []
        taken: list[tuple[int, int]] = []
        for key, row in self.rows:
            position = haystack.find(f" {key} ")
            if position < 0:
                continue
            # The key itself, without its separating spaces: adjacent matches
            # share a space, which MedSpeech counted as an overlap.
            span = (position + 1, position + 1 + len(key))
            if any(not (span[1] <= a or span[0] >= b) for a, b in taken):
                continue
            taken.append(span)
            hits.append({
                field: str(row.get(field, ""))
                for field in ("spoken_form", "standard_ro", "variant_type", "action", "confidence", "category")
            })
            if len(hits) >= max_hits:
                break
        return hits


def _hotword_prompt(hotwords: dict[str, list[str]]) -> str:
    """Terms taken in turn from each category until the prompt budget is used."""
    columns = [values for values in hotwords.values() if isinstance(values, list)]
    chosen: list[str] = []
    length = 0
    for row in zip_longest(*columns):
        for term in row:
            term = str(term or "").strip()
            if not term or term in chosen:
                continue
            if length + len(term) + 2 > PROMPT_CHARACTERS:
                return ", ".join(chosen)
            chosen.append(term)
            length += len(term) + 2
    return ", ".join(chosen)

