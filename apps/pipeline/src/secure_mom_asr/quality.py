"""Repeat Guard and quality checks, ported from MedSpeech `medspeech_main.py`.

Thresholds are the MedSpeech values. Deliberate differences:

- `strict_text_reasons` uses `\\w+` as intended; the original pattern
  `r"\\\\w+"` never matched, so its repetition and length checks never ran.
- Log probability, no-speech and compression checks also apply to FraPiz,
  because whisper.cpp reports them for every model.
- Repetition (repeated words or n-grams, a high compression ratio) marks a
  result for REVIEW instead of rejecting it. On a Medpark recording, the
  MedSpeech rule rejected 2 of 9 segments of real speech for phrases such as
  "la momentul de transfer" said three times in 20 s. The Repeat Guard
  already removes actual loops.
"""

from __future__ import annotations

import re
import unicodedata
import zlib
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal


Status = Literal["ACCEPT", "REVIEW", "REJECT"]
STATUS_RANK: dict[Status, int] = {"ACCEPT": 0, "REVIEW": 1, "REJECT": 2}

_BOILERPLATE = (
    "nu uitați să dați like", "nu uitati sa dati like",
    "lăsați un comentariu", "lasati un comentariu",
    "abonați-vă", "abonati-va",
    "thanks for watching", "thank you for watching",
    "приятного аппетита", "подписывайтесь", "ставьте лайк",
    # Subtitle credits Whisper-family models produce over silence.
    "subtitrare", "субтитр", "продолжение следует", "amara.org",
)
_WORD = re.compile(r"\w+", re.UNICODE)


def clean(text: str) -> str:
    """Normalise whitespace without changing recognised words or script."""
    text = re.sub(r"\s+", " ", text or "").strip()
    return re.sub(r"\s+([,.;:!?])", r"\1", text)


def script_counts(text: str) -> tuple[int, int]:
    """Latin and Cyrillic letter counts."""
    latin = len(re.findall(r"[A-Za-zĂÂÎȘŞȚŢăâîșşțţ]", text or ""))
    cyrillic = len(re.findall(r"[Ѐ-ӿ]", text or ""))
    return latin, cyrillic


def repeat_guard(text: str, max_repeats: int = 2, max_phrase_words: int = 8) -> tuple[str, bool]:
    """Keep consecutive repeated characters, units, words or phrases at most twice.

    "așa, așa, așa, așa" becomes "așa, așa"; "șașașașa" becomes "șașa";
    "aaaa" becomes "aa". Returns the text and whether it changed; callers
    keep the raw text separately.
    """
    x = clean(text)
    original = x
    if not x:
        return x, False

    # A. Three or more identical letters: no RO/RU medical word needs them.
    char_run = re.compile(r"([^\W\d_])\1{2,}", re.IGNORECASE | re.UNICODE)
    x = char_run.sub(lambda m: m.group(1) * max_repeats, x)

    # B. A unit of up to 12 characters repeated 3+ times inside one token.
    def collapse_token(match: re.Match[str]) -> str:
        token = match.group(0)
        low, length = token.casefold(), len(token)
        for unit in range(1, min(12, length // 3) + 1):
            copies = length // unit
            if length % unit == 0 and copies >= 3 and low[:unit] * copies == low:
                return token[:unit] * max_repeats
        return token

    x = re.sub(r"[^\W_]+", collapse_token, x)

    # C. Consecutive word sequences, compared without punctuation.
    def collapse_phrase_once(s: str, n: int) -> str | None:
        words = list(re.finditer(r"[^\W_]+(?:['’\-][^\W_]+)*", s, re.UNICODE))
        norms = [m.group(0).casefold() for m in words]
        i = 0
        while i + n * (max_repeats + 1) <= len(words):
            seq = norms[i:i + n]
            copies = 1
            while i + (copies + 1) * n <= len(words) and norms[i + copies * n:i + (copies + 1) * n] == seq:
                copies += 1
            if copies > max_repeats:
                remove_start = words[i + max_repeats * n - 1].end()
                run_last = i + copies * n - 1
                if run_last + 1 < len(words):
                    remove_end, replacement = words[run_last + 1].start(), " "
                else:
                    remove_end = len(s)
                    punct = re.search(r"([.!?])", s[words[run_last].end():])
                    replacement = punct.group(1) if punct else ""
                return clean(s[:remove_start] + replacement + s[remove_end:])
            i += 1
        return None

    for n in range(max_phrase_words, 0, -1):
        while (collapsed := collapse_phrase_once(x, n)) is not None:
            x = collapsed

    x = clean(x)
    return x, x != original


def _repetition_reasons(words: list[str], share: float) -> list[str]:
    reasons = []
    if len(words) >= 10:
        if max(Counter(words).values()) / len(words) >= share:
            reasons.append("EXCESSIVE_WORD_REPETITION")
        for n in (2, 3):
            if len(words) >= n * 3:
                grams = Counter(tuple(words[i:i + n]) for i in range(len(words) - n + 1))
                if max(grams.values()) >= 3:
                    reasons.append(f"REPEATED_{n}GRAM")
                    break
    return reasons


def strict_text_reasons(text: str, romanian: bool, seconds: float) -> list[str]:
    """Text-only hallucination flags; any flag on FraPiz output triggers routing."""
    low = (text or "").lower().strip()
    if not low:
        return ["EMPTY_TRANSCRIPT"]
    reasons = []
    if any(phrase in low for phrase in _BOILERPLATE):
        reasons.append("POSSIBLE_HALLUCINATION_BOILERPLATE")
    words = _WORD.findall(low)
    reasons += _repetition_reasons(words, 0.24)
    # 20 s of medical speech rarely exceeds ~90-100 lexical tokens.
    if len(words) > max(35, int(max(1.0, seconds) * 4.5)):
        reasons.append("IMPLAUSIBLY_LONG_TRANSCRIPT")
    latin, cyrillic = script_counts(text)
    if romanian and cyrillic > max(2, latin * 0.10):
        reasons.append("CYRILLIC_IN_RO_MD_PRIMARY")
    return reasons


def compression_ratio(text: str) -> float:
    data = text.encode("utf-8")
    return len(data) / len(zlib.compress(data)) if data else 0.0


@dataclass(frozen=True, slots=True)
class Assessment:
    status: Status
    reasons: tuple[str, ...]


def quality_filter(
    raw: str,
    *,
    russian_confirmed: bool,
    seconds: float,
    avg_logprob: float,
    no_speech_prob: float,
    repetition_trimmed: bool,
) -> Assessment:
    """MedSpeech's hallucination gate, judged on the raw decoder output.

    REJECT removes the segment from the transcript; REVIEW keeps it for a
    person to check.
    """
    text = (raw or "").strip()
    if not text:
        return Assessment("REJECT", ("EMPTY_TRANSCRIPT",))
    reasons: list[str] = []
    status: Status = "ACCEPT"

    def mark(reason: str, level: Status) -> None:
        nonlocal status
        reasons.append(reason)
        if STATUS_RANK[level] > STATUS_RANK[status]:
            status = level

    words = _WORD.findall(text.lower())
    for reason in _repetition_reasons(words, 0.28):
        mark(reason, "REVIEW")
    if len(words) > max(35, int(seconds * 4.8)):
        mark("IMPLAUSIBLY_LONG_TRANSCRIPT", "REJECT")

    # RO/MD first: mostly Cyrillic text needs a confirmed Russian route.
    latin, cyrillic = script_counts(text)
    cyrillic_ratio = cyrillic / max(1, latin + cyrillic)
    if not russian_confirmed:
        if cyrillic_ratio >= 0.55:
            mark("CYRILLIC_WITHOUT_RU_CONFIRMATION", "REJECT")
        elif cyrillic_ratio >= 0.15 and status != "REJECT":
            mark("MIXED_SCRIPT_WITHOUT_RU_CONFIRMATION", "REVIEW")

    if no_speech_prob >= 0.60:
        mark("HIGH_NO_SPEECH_PROBABILITY", "REJECT")
    elif no_speech_prob >= 0.35 and status == "ACCEPT":
        mark("ELEVATED_NO_SPEECH_PROBABILITY", "REVIEW")
    if avg_logprob < -1.25:
        mark("VERY_LOW_ASR_LOGPROB", "REJECT")
    elif avg_logprob < -0.90 and status == "ACCEPT":
        mark("LOW_ASR_LOGPROB", "REVIEW")
    if compression_ratio(text) > 2.4:
        mark("HIGH_COMPRESSION_RATIO", "REVIEW")
    if repetition_trimmed:
        mark("CONSECUTIVE_REPETITION_TRIMMED", "REVIEW")
    return Assessment(status, tuple(reasons))


def _key(word: str) -> str:
    """A word without case, diacritics or punctuation: "Dă," and "da" match."""
    decomposed = unicodedata.normalize("NFKD", word.casefold())
    return "".join(_WORD.findall("".join(c for c in decomposed if not unicodedata.combining(c))))


def trim_overlap(previous: str, current: str, window: int = 15, slack: int = 2) -> str:
    """Remove the words a segment repeats from the previous one's end.

    Each segment after the first is decoded with 2 s of the previous
    segment's audio in front of it, and the two decodes of that audio differ
    slightly ("da să vă" / "dă să vă", "fugem" / "fugim"). The last `window`
    words of `previous` are aligned with the first `window` of `current`. The
    current text loses its first words up to the end of the aligned run when
    the run starts within `slack` words of its start, reaches within `slack`
    words of the previous text's end, and matches at least half of the words
    it removes. A number repeated by chance ("două sute patruzeci") stays.
    """
    words = current.split()
    tail = [key for key in (_key(w) for w in previous.split()) if key][-window:]
    head = [_key(w) for w in words[:window]]
    blocks = [b for b in SequenceMatcher(None, tail, head, autojunk=False).get_matching_blocks() if b.size]
    near_end = [b for b in blocks if b.a + b.size >= len(tail) - slack]
    if not near_end or blocks[0].b > slack:
        return current
    cut = near_end[-1].b + near_end[-1].size
    matched = sum(b.size for b in blocks if b.b < cut)
    if matched < 2 or matched * 2 < cut:
        return current
    return " ".join(words[cut:])
