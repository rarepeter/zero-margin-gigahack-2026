"""Speaker diarization with pyannote `speaker-diarization-community-1`.

The model is loaded from a local folder; no Hugging Face token or network is
used at runtime. pyannote.audio 4 sends usage telemetry to otel.pyannote.ai by
default, which would break the offline requirement, so it is switched off
before pyannote is imported. Attribution follows MedSpeech: each ASR segment belongs to
the speaker whose turns overlap it longest. This is attribution, not source
separation, so overlapping speech is recorded but not split.
"""

from __future__ import annotations

import logging
import os
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any


logger = logging.getLogger("secure_mom_asr")


class DiarizationError(Exception):
    """The diarization model could not be loaded or run."""


@dataclass(frozen=True, slots=True)
class Turn:
    start: float
    end: float
    speaker: str


class Diarizer:
    def __init__(self, model_dir: Path, device: str) -> None:
        self.model_dir = model_dir
        self.device = device
        self._pipeline: Any = None

    def ensure_ready(self) -> Any:
        """Load the pipeline once; later calls return it."""
        if self._pipeline is None:
            os.environ["PYANNOTE_METRICS_ENABLED"] = "false"
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
            try:
                import torch
                from pyannote.audio import Pipeline

                pipeline = Pipeline.from_pretrained(str(self.model_dir))
                pipeline.to(torch.device(self.device))
            except Exception as exc:  # pyannote raises many types while loading
                raise DiarizationError(f"diarization model could not be loaded: {exc}") from exc
            self._pipeline = pipeline
        return self._pipeline

    def turns(self, wav: Path) -> list[Turn]:
        """Speaker turns of a 16 kHz mono PCM16 WAV, labelled speaker-1, speaker-2, …"""
        import numpy as np
        import torch

        pipeline = self.ensure_ready()
        started = time.monotonic()
        with wave.open(str(wav), "rb") as audio:
            samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2")
            rate = audio.getframerate()
        # Passing the waveform avoids pyannote's own audio decoding.
        waveform = torch.from_numpy(samples.astype(np.float32) / 32768.0).unsqueeze(0)
        try:
            output = pipeline({"waveform": waveform, "sample_rate": rate})
        except Exception as exc:
            raise DiarizationError(f"diarization failed: {exc}") from exc
        annotation = getattr(output, "speaker_diarization", output)
        raw = sorted(
            (float(segment.start), float(segment.end), str(label))
            for segment, _, label in annotation.itertracks(yield_label=True)
        )
        # Stable, anonymous IDs in order of first appearance.
        names: dict[str, str] = {}
        for _, _, label in raw:
            names.setdefault(label, f"speaker-{len(names) + 1}")
        turns = [Turn(start, end, names[label]) for start, end, label in raw]
        logger.info(
            "event=diarization_done speakers=%d turns=%d elapsed_s=%.0f",
            len(names),
            len(turns),
            time.monotonic() - started,
        )
        return turns


def attribute(start: float, end: float, turns: list[Turn]) -> list[tuple[str, float]]:
    """Speakers overlapping [start, end] with their overlap seconds, longest first."""
    overlap: dict[str, float] = {}
    for turn in turns:
        seconds = min(end, turn.end) - max(start, turn.start)
        if seconds > 0:
            overlap[turn.speaker] = overlap.get(turn.speaker, 0.0) + seconds
    return sorted(overlap.items(), key=lambda item: item[1], reverse=True)
