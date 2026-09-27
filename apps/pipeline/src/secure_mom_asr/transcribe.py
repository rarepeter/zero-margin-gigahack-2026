"""FraPiz-first transcription of one recording, following MedSpeech Module 04.

For each silence-aware segment (decoded with 2 s of the previous segment's
audio in front):

1. FraPiz transcribes with Romanian forced. MedSpeech's quality filter
   grades the result ACCEPT, REVIEW or REJECT, and its text checks add
   review flags.
2. Only a rejected FraPiz result (silence, very low confidence, Cyrillic,
   implausible length) triggers language identification with Whisper
   large-v3, and a retry with large-v3 in the detected language: Russian,
   English, or automatic for anything but Romanian. As in MedSpeech
   `classify_language`, a Russian detection on Latin-script FraPiz text with
   lexicon matches counts as Romanian/Moldovan and keeps FraPiz.
3. The better-graded result wins. REJECT segments leave the transcript;
   flagged or REVIEW segments report a confidence of at most 0.5.
4. Words repeated from the previous segment's overlap are removed, and each
   segment is attributed to the diarization speaker who overlaps it longest.

Language detection never replaces a usable FraPiz result: on a Medpark
recording, both Whisper large-v3 and ECAPA (VoxLingua107) labelled most
Moldovan Romanian segments as Russian, Ukrainian or Belarusian, and large-v3
then wrote Romanian phonetically in Cyrillic.

Diarization runs in parallel with recognition. Every attempt, raw text
included, is kept in `segments.json` in the job directory.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from secure_mom_pipeline.models import TranscriptionResult

from . import audio
from .config import AsrSettings
from .diarize import DiarizationError, Turn, attribute
from .lexicon import Lexicon
from .quality import (
    STATUS_RANK,
    Assessment,
    clean,
    quality_filter,
    repeat_guard,
    script_counts,
    strict_text_reasons,
    trim_overlap,
)
from .whisper import Recognition


logger = logging.getLogger("secure_mom_asr")

REVIEW_CONFIDENCE_CAP = 0.5
_LID_LABELS = {"ro": "RO/MD", "ru": "RU", "en": "EN"}


class Recognizer(Protocol):
    def transcribe(self, wav: Path, language: str, prompt: str = "") -> Recognition: ...

    def identify_language(self, wav: Path) -> dict[str, float]: ...


class SpeakerTurns(Protocol):
    def turns(self, wav: Path) -> list[Turn]: ...


class NoSpeechError(Exception):
    """No segment of the recording contained usable speech."""


@dataclass(frozen=True, slots=True)
class Attempt:
    model: str
    language: str
    recognition: Recognition
    raw: str
    text: str
    reasons: tuple[str, ...]
    assessment: Assessment

    def record(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "language": self.language,
            "raw": self.raw,
            "text": self.text,
            "reasons": list(self.reasons),
            "status": self.assessment.status,
            "qualityReasons": list(self.assessment.reasons),
            "avgLogprob": self.recognition.avg_logprob,
            "noSpeechProb": self.recognition.no_speech_prob,
            "confidence": self.recognition.confidence,
        }


@dataclass(frozen=True, slots=True)
class Kept:
    segment_id: str
    span: audio.Span
    attempt: Attempt
    text: str
    review: bool


def language_label(lid: dict[str, float], frapiz_text: str, lexicon_hits: int) -> str:
    """MedSpeech language class of a segment: RO/MD, RU, EN, OTHER or UNKNOWN."""
    if not lid:
        return "UNKNOWN"
    label = _LID_LABELS.get(max(lid, key=lambda key: lid[key]), "OTHER")
    latin, _ = script_counts(frapiz_text)
    return "RO/MD" if label == "RU" and latin and lexicon_hits else label


def fallback_language(label: str) -> str | None:
    """Whisper language for the large-v3 retry, or None to keep FraPiz."""
    if label == "RO/MD":
        return None
    return {"RU": "ru", "EN": "en"}.get(label, "auto")


def choose(frapiz: Attempt, fallback: Attempt | None) -> Attempt:
    """The better-graded attempt; FraPiz on a tie."""
    if fallback is None:
        return frapiz
    if STATUS_RANK[fallback.assessment.status] < STATUS_RANK[frapiz.assessment.status]:
        return fallback
    return frapiz


def _attempt(
    model: Recognizer,
    name: str,
    wav: Path,
    language: str,
    seconds: float,
    *,
    russian_confirmed: bool,
    prompt: str = "",
) -> Attempt:
    recognition = model.transcribe(wav, language, prompt)
    raw = clean(recognition.text)
    text, trimmed = repeat_guard(raw)
    assessment = quality_filter(
        raw,
        russian_confirmed=russian_confirmed,
        seconds=seconds,
        avg_logprob=recognition.avg_logprob,
        no_speech_prob=recognition.no_speech_prob,
        repetition_trimmed=trimmed,
    )
    reasons = strict_text_reasons(raw, romanian=language == "ro", seconds=seconds)
    return Attempt(name, language, recognition, raw, text, tuple(reasons), assessment)


def transcribe_recording(
    settings: AsrSettings,
    frapiz: Recognizer,
    fallback: Recognizer,
    *,
    source: Path,
    workdir: Path,
    pipeline_job_id: str,
    lexicon: Lexicon | None = None,
    diarizer: SpeakerTurns | None = None,
) -> bytes:
    """Transcribe `source` and return the serialized transcription result."""
    started = time.monotonic()
    ffmpeg = settings.ffmpeg_bin
    segmentation = settings.segmentation
    wav = workdir / "normalized.wav"
    audio.normalize(ffmpeg, source, wav)
    duration, _ = audio.probe(settings.ffprobe_bin, wav)
    _, recorded_at = audio.probe(settings.ffprobe_bin, source)
    spans = audio.plan_segments(duration, audio.detect_pauses(ffmpeg, wav, segmentation), segmentation)
    segment_dir = workdir / "segments"
    segment_dir.mkdir(exist_ok=True)
    logger.info("event=segmentation_done duration_s=%.0f segments=%d", duration, len(spans))
    prompt = lexicon.prompt if lexicon and settings.lexicon_mode == "assisted" else ""

    records: dict[str, dict[str, Any]] = {}
    kept: list[Kept] = []
    turns: list[Turn] = []
    with ThreadPoolExecutor(max_workers=1) as pool:
        diarization: Future[list[Turn]] | None = (
            pool.submit(diarizer.turns, wav) if diarizer is not None else None
        )
        previous_text = ""
        for index, span in enumerate(spans, start=1):
            segment_id = f"segment-{index}"
            wav_path = segment_dir / f"{segment_id}.wav"
            audio.cut(ffmpeg, wav, span, duration, segmentation, wav_path, first=index == 1)
            # The decoded clip also holds the previous segment's overlap.
            seconds = span.end - span.start + (segmentation.overlap_seconds if index > 1 else 0.0)

            first = _attempt(
                frapiz, "frapiz", wav_path, "ro", seconds, russian_confirmed=False, prompt=prompt
            )
            lid: dict[str, float] = {}
            label = "RO/MD"
            second = None
            if first.assessment.status == "REJECT":
                lid = fallback.identify_language(wav_path)
                hits = lexicon.evidence(first.raw) if lexicon else []
                label = language_label(lid, first.raw, len(hits))
                language = fallback_language(label)
                if language:
                    second = _attempt(
                        fallback, "large-v3", wav_path, language, seconds,
                        russian_confirmed=label == "RU",
                    )
                    if language == "auto":
                        second = replace(second, language=max(lid, key=lambda k: lid[k]))
            chosen = choose(first, second)
            text = trim_overlap(previous_text, chosen.text) if index > 1 else chosen.text
            previous_text = chosen.text
            rejected = chosen.assessment.status == "REJECT" or not text
            review = bool(chosen.reasons) or chosen.assessment.status == "REVIEW"
            records[segment_id] = {
                "id": segment_id,
                "start": round(span.start, 3),
                "end": round(span.end, 3),
                "languageProbabilities": {k: round(v, 4) for k, v in lid.items() if v >= 0.01},
                "languageClass": label,
                "lexiconHits": lexicon.evidence(chosen.text) if lexicon else [],
                "attempts": [a.record() for a in (first, second) if a is not None],
                "chosen": chosen.model,
                "text": text,
                "status": "REJECT" if rejected else chosen.assessment.status,
                "reviewRequired": review,
            }
            if not rejected:
                kept.append(Kept(segment_id, span, chosen, text, review))

        if diarization is not None:
            try:
                turns = diarization.result()
            except DiarizationError as exc:
                logger.error("event=diarization_failed reason=%s", exc)
    shutil.rmtree(segment_dir, ignore_errors=True)

    segments: list[dict[str, Any]] = []
    for item in kept:
        overlaps = attribute(item.span.start, item.span.end, turns)
        records[item.segment_id]["speakers"] = [
            {"speaker": speaker, "overlapSeconds": round(seconds, 3)} for speaker, seconds in overlaps
        ]
        confidence = item.attempt.recognition.confidence
        if item.review:
            confidence = min(confidence if confidence is not None else 1.0, REVIEW_CONFIDENCE_CAP)
        segments.append({
            "id": item.segment_id,
            "startMs": round(item.span.start * 1000),
            "endMs": round(item.span.end * 1000),
            "speakerId": overlaps[0][0] if overlaps else None,
            "languages": [item.attempt.language],
            "text": item.text,
            "confidence": confidence,
        })
    (workdir / "segments.json").write_text(
        json.dumps(list(records.values()), ensure_ascii=False, indent=1), encoding="utf-8"
    )
    if not segments:
        raise NoSpeechError("no segment contained usable speech")

    body = _result(pipeline_job_id, segments, turns, duration, recorded_at)
    elapsed = time.monotonic() - started
    logger.info(
        "event=transcription_done duration_s=%.0f elapsed_s=%.0f realtime_x=%.1f kept=%d "
        "rejected=%d fallback=%d review=%d speakers=%d",
        duration,
        elapsed,
        duration / elapsed if elapsed else 0.0,
        len(segments),
        len(spans) - len(segments),
        sum(1 for item in kept if item.attempt.model == "large-v3"),
        sum(1 for item in kept if item.review),
        len({s["speakerId"] for s in segments if s["speakerId"]}),
    )
    return body


def _result(
    pipeline_job_id: str,
    segments: list[dict[str, Any]],
    turns: list[Turn],
    duration: float,
    recorded_at: datetime | None,
) -> bytes:
    spoken = {s["id"]: s["endMs"] - s["startMs"] for s in segments}
    total = sum(spoken.values()) or 1
    shares: dict[str, float] = {}
    for segment in segments:
        code = segment["languages"][0]
        shares[code] = shares.get(code, 0.0) + spoken[segment["id"]] / total

    # Only speakers who own a kept segment: tiny spurious clusters would
    # otherwise appear as participants.
    attributed = {s["speakerId"] for s in segments if s["speakerId"]}
    turn_seconds: dict[str, float] = {}
    for turn in turns:
        turn_seconds[turn.speaker] = turn_seconds.get(turn.speaker, 0.0) + turn.end - turn.start
    all_turns = sum(turn_seconds.values()) or 1.0
    speakers = [
        {
            "id": speaker,
            "displayName": None,
            "languages": sorted({s["languages"][0] for s in segments if s["speakerId"] == speaker}),
            "speakingTimeProportion": round(seconds / all_turns, 4),
        }
        for speaker, seconds in turn_seconds.items()
        if speaker in attributed
    ]

    scored = [s for s in segments if s["confidence"] is not None]
    weight = sum(spoken[s["id"]] for s in scored)
    result = {
        "schemaVersion": 1,
        "jobId": pipeline_job_id,
        "transcript": {
            "text": "\n".join(segment["text"] for segment in segments),
            "segments": segments,
        },
        "audioMetadata": {
            "durationMs": max(1, round(duration * 1000)),
            "recordedAt": recorded_at.isoformat() if recorded_at else None,
        },
        "languageDetection": {
            "languages": [
                {"code": code, "proportion": round(share, 4)}
                for code, share in sorted(shares.items(), key=lambda item: -item[1])
            ]
        },
        "speakers": speakers,
        "quality": {
            "transcriptConfidence": (
                round(sum(s["confidence"] * spoken[s["id"]] for s in scored) / weight, 4)
                if weight else None
            ),
            "confidenceScale": "ZERO_TO_ONE",
        },
    }
    return TranscriptionResult.model_validate(result).model_dump_json(by_alias=True).encode("utf-8")
