"""Configuration for the local speech-to-text service, read once from the environment."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast


LexiconMode = Literal["strict", "assisted"]


def _path(name: str) -> Path | None:
    value = os.getenv(name)
    return Path(value).expanduser() if value else None


def _binary(name: str, fallback: str) -> str:
    return os.getenv(name) or shutil.which(fallback) or fallback


@dataclass(frozen=True, slots=True)
class Segmentation:
    """Silence-aware segmentation with the MedSpeech defaults."""

    pause_seconds: float = 0.8
    silence_db: float = -35.0
    target_min_seconds: float = 6.0
    target_max_seconds: float = 20.0
    absolute_max_seconds: float = 30.0
    min_segment_seconds: float = 1.5
    padding_seconds: float = 0.4
    # Previous audio decoded in front of every later segment; the words it
    # repeats are removed after decoding.
    overlap_seconds: float = 2.0


@dataclass(frozen=True, slots=True)
class AsrSettings:
    host: str
    port: int
    storage_root: Path
    log_file: Path

    whisper_server_bin: str
    ffmpeg_bin: str
    ffprobe_bin: str
    # FraPiz (Moldovan Romanian) and the multilingual fallback, both converted
    # to whisper.cpp's ggml format.
    frapiz_model_path: Path | None
    fallback_model_path: Path | None
    threads: int

    segmentation: Segmentation

    # Moldova Medical Speech Lexicon. `strict` (the default) only records
    # matches; `assisted` also primes FraPiz with medical hotwords.
    lexicon_path: Path | None
    lexicon_mode: LexiconMode

    # Local pyannote speaker-diarization-community-1 folder; unset disables
    # diarization.
    diarization_model_path: Path | None
    diarization_device: str


def get_asr_settings() -> AsrSettings:
    lexicon_mode = os.getenv("ASR_LEXICON_MODE", "strict")
    if lexicon_mode not in ("strict", "assisted"):
        raise ValueError("ASR_LEXICON_MODE must be strict or assisted")
    return AsrSettings(
        host=os.getenv("ASR_HOST", "127.0.0.1"),
        port=int(os.getenv("ASR_PORT", "8101")),
        storage_root=Path(os.getenv("ASR_STORAGE_ROOT", "runtime/asr")).expanduser(),
        log_file=Path(os.getenv("ASR_LOG_FILE", "runtime/logs/asr.log")).expanduser(),
        whisper_server_bin=_binary("ASR_WHISPER_SERVER_BIN", "whisper-server"),
        ffmpeg_bin=_binary("ASR_FFMPEG_BIN", "ffmpeg"),
        ffprobe_bin=_binary("ASR_FFPROBE_BIN", "ffprobe"),
        frapiz_model_path=_path("ASR_FRAPIZ_MODEL_PATH"),
        fallback_model_path=_path("ASR_FALLBACK_MODEL_PATH"),
        threads=int(os.getenv("ASR_THREADS", "8")),
        # Recordings with a noisy room need a higher (less negative) threshold.
        segmentation=Segmentation(
            silence_db=float(os.getenv("ASR_SILENCE_DB", "-35")),
            overlap_seconds=float(os.getenv("ASR_OVERLAP_SECONDS", "2.0")),
        ),
        lexicon_path=_path("ASR_LEXICON_PATH"),
        lexicon_mode=cast(LexiconMode, lexicon_mode),
        diarization_model_path=_path("ASR_DIARIZATION_MODEL_PATH"),
        diarization_device=os.getenv("ASR_DIARIZATION_DEVICE", "mps"),
    )
