from __future__ import annotations

import dataclasses
import json
import os
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from secure_mom_asr.audio import Span, plan_segments
from secure_mom_asr.config import Segmentation, get_asr_settings
from secure_mom_asr.diarize import DiarizationError, Diarizer, Turn, attribute
from secure_mom_asr.lexicon import Lexicon
from secure_mom_asr.quality import Assessment, quality_filter, repeat_guard, trim_overlap
from secure_mom_asr.transcribe import (
    Attempt,
    choose,
    fallback_language,
    language_label,
    transcribe_recording,
)
from secure_mom_asr.whisper import Recognition
from secure_mom_pipeline.audio_service import HttpAudioService
from secure_mom_pipeline.models import TranscriptionResult


def test_http_audio_service_submits_path_callbacks_and_idempotency_key(tmp_path: Path) -> None:
    audio = tmp_path / "meeting.m4a"
    audio.write_bytes(b"audio")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(202, json={"modelJobId": "asr-1", "status": "accepted"})

    service = HttpAudioService(
        "http://asr.local",
        "/jobs",
        5.0,
        callback_url="http://api.local/api/v1/integrations/audio/jobs/{job_id}/transcription",
        failure_url="http://api.local/api/v1/integrations/audio/jobs/{job_id}/failure",
        transport=httpx.MockTransport(handler),
    )

    submission = service.submit("job-1", audio, "job-1:transcription:1")

    assert submission.model_job_id == "asr-1"
    [request] = requests
    assert request.url == "http://asr.local/jobs"
    assert request.headers["idempotency-key"] == "job-1:transcription:1"
    assert json.loads(request.content) == {
        "pipelineJobId": "job-1",
        "audioPath": str(audio),
        "callbackUrl": "http://api.local/api/v1/integrations/audio/jobs/job-1/transcription",
        "failureUrl": "http://api.local/api/v1/integrations/audio/jobs/job-1/failure",
    }


def test_segments_are_cut_at_the_latest_pause_midpoint_within_target() -> None:
    pauses = [Span(0, 2), Span(9, 10), Span(18, 19), Span(27, 28), Span(40, 45)]

    assert plan_segments(50, pauses, Segmentation()) == [
        Span(0, 18.5), Span(18.5, 27.5), Span(27.5, 50),
    ]


def test_segments_fall_back_to_the_target_maximum_in_a_noisy_room() -> None:
    assert plan_segments(70, [], Segmentation()) == [Span(0, 20), Span(20, 40), Span(40, 70)]


def test_repeat_guard_keeps_two_repeats_of_letters_units_words_and_phrases() -> None:
    assert repeat_guard("așa, așa, așa, așa") == ("așa, așa", True)
    assert repeat_guard("daaaaa, șașașașa") == ("daa, șașa", True)
    looped = "cu oarecea mai departe, " * 6 + "dozele de zero"
    assert repeat_guard(looped) == (
        "cu oarecea mai departe, cu oarecea mai departe dozele de zero", True
    )
    assert repeat_guard("tensiunea optzeci pe patruzeci") == ("tensiunea optzeci pe patruzeci", False)


def test_quality_filter_reviews_repetition_but_rejects_silence_and_unconfirmed_cyrillic() -> None:
    graded = dict(russian_confirmed=False, seconds=20, avg_logprob=-0.2, repetition_trimmed=False)
    natural = "la momentul de transfer el a fost stabil, la momentul de transfer tensiunea, la momentul de transfer"

    assert quality_filter(natural, no_speech_prob=0.0, **graded).status == "REVIEW"
    assert quality_filter("mulțumesc", no_speech_prob=0.7, **graded).status == "REJECT"
    assert quality_filter(
        "давление восемьдесят на сорок", no_speech_prob=0.0, **graded
    ).reasons[0] == "CYRILLIC_WITHOUT_RU_CONFIRMATION"


def test_overlap_words_are_removed_even_after_a_partly_heard_word() -> None:
    previous = "pacientul are febră de trei zile"

    assert trim_overlap(previous, "febră de trei zile și tuse") == "și tuse"
    assert trim_overlap(previous, "ră de trei zile și tuse") == "și tuse"
    assert trim_overlap(previous, "altceva nou") == "altceva nou"
    # Real Medpark boundaries: two decodes of the same audio differ slightly,
    # and a number repeated by chance is new content.
    assert trim_overlap(
        "destul de activ, la momentul de transfer, da să vă...",
        "la momentul de transfer, dă să vă, la momentul de transfer, dacă",
    ) == "la momentul de transfer, dacă"
    assert trim_overlap(
        "doi sute patruzeci și uria nouăsprezece.",
        "nouăzeci, acuma-s două sute patruzeci, practic",
    ) == "nouăzeci, acuma-s două sute patruzeci, practic"


def test_lexicon_matches_moldovan_forms_without_changing_text(tmp_path: Path) -> None:
    path = tmp_path / "lexicon.json"
    path.write_text(json.dumps({
        "normalisation_map": [
            {"spoken_form": "a naznaci", "match_key": "naznacit", "standard_ro": "a prescrie",
             "variant_type": "russism", "action": "replace", "confidence": "verified",
             "category": "verb"},
            {"spoken_form": "bolniță", "standard_ro": "spital", "variant_type": "russism",
             "action": "replace", "confidence": "verified", "category": "place"},
        ],
        "asr_hotwords": {"drug": ["metamizol", "etamsilat"], "test": ["glicemie"]},
    }), encoding="utf-8")
    lexicon = Lexicon.load(path)

    hits = lexicon.evidence("L-am naznacit, bolnița e plină.")
    assert [(hit["spoken_form"], hit["standard_ro"]) for hit in hits] == [
        ("a naznaci", "a prescrie"), ("bolniță", "spital"),
    ]
    assert lexicon.prompt == "metamizol, glicemie, etamsilat"


def attempt(model: str, status: str, avg_logprob: float) -> Attempt:
    return Attempt(
        model, "ro", Recognition("text", avg_logprob, 0.0, 0.9), "text", "text", (),
        Assessment(status, ()),  # type: ignore[arg-type]
    )


def test_only_a_rejected_frapiz_result_is_replaced() -> None:
    # Whisper hears Moldovan Romanian as Russian; lexicon matches overrule it.
    assert language_label({"ru": 0.7, "ro": 0.2}, "l-am naznacit", 1) == "RO/MD"
    assert language_label({"ru": 0.7, "ro": 0.2}, "l-am naznacit", 0) == "RU"
    assert fallback_language("RO/MD") is None
    assert fallback_language("RU") == "ru"
    assert fallback_language("OTHER") == "auto"

    frapiz = attempt("frapiz", "REVIEW", -0.2)
    assert choose(frapiz, attempt("large-v3", "ACCEPT", -0.5)).model == "large-v3"
    assert choose(frapiz, attempt("large-v3", "REVIEW", -0.1)) is frapiz
    assert choose(frapiz, attempt("large-v3", "REJECT", -0.1)) is frapiz


def test_segments_belong_to_the_speaker_who_overlaps_them_longest() -> None:
    turns = [Turn(0, 4, "speaker-1"), Turn(4, 15, "speaker-2"), Turn(15, 20, "speaker-1")]

    assert attribute(0, 20, turns) == [("speaker-2", 11), ("speaker-1", 9)]
    assert attribute(21, 25, turns) == []


class ScriptedRecognizer:
    def __init__(self, texts: list[str]) -> None:
        self.texts = texts
        self.prompts: list[str] = []

    def transcribe(self, wav: Path, language: str, prompt: str = "") -> Recognition:
        self.prompts.append(prompt)
        return Recognition(self.texts.pop(0), -0.2, 0.0, 0.9)

    def identify_language(self, wav: Path) -> dict[str, float]:
        return {"ro": 0.9}


class FixedSpeakers:
    def turns(self, wav: Path) -> list[Turn]:
        return [Turn(0, 18, "speaker-1"), Turn(18, 45, "speaker-2")]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs FFmpeg")
def test_transcribe_recording_trims_overlap_and_attributes_speakers(tmp_path: Path) -> None:
    recording = tmp_path / "meeting.m4a"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=45",
         "-c:a", "aac", str(recording)],
        check=True,
    )
    frapiz = ScriptedRecognizer(["Bună ziua, colegi, începem", "colegi, începem cu cazul unu"])
    settings = dataclasses.replace(get_asr_settings(), lexicon_mode="assisted")

    body = transcribe_recording(
        settings,
        frapiz,
        ScriptedRecognizer([]),
        source=recording,
        workdir=tmp_path,
        pipeline_job_id="job-1",
        lexicon=Lexicon(rows=(), prompt="metamizol, glicemie"),
        diarizer=FixedSpeakers(),
    )

    result = TranscriptionResult.model_validate_json(body)
    assert [(s.id, s.text, s.speaker_id) for s in result.transcript.segments] == [
        ("segment-1", "Bună ziua, colegi, începem", "speaker-1"),
        ("segment-2", "cu cazul unu", "speaker-2"),
    ]
    assert [s.id for s in result.speakers] == ["speaker-1", "speaker-2"]
    assert frapiz.prompts == ["metamizol, glicemie"] * 2
    assert 44_500 <= result.audio_metadata.duration_ms <= 45_500
    records = json.loads((tmp_path / "segments.json").read_text())
    assert records[1]["attempts"][0]["raw"] == "colegi, începem cu cazul unu"


def test_diarizer_switches_off_pyannote_telemetry_before_loading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # pyannote.audio 4 otherwise sends usage traces to otel.pyannote.ai.
    monkeypatch.delenv("PYANNOTE_METRICS_ENABLED", raising=False)
    with pytest.raises(DiarizationError):
        Diarizer(tmp_path / "missing-model", "cpu").ensure_ready()

    assert os.environ["PYANNOTE_METRICS_ENABLED"] == "false"
    assert os.environ["HF_HUB_OFFLINE"] == "1"
