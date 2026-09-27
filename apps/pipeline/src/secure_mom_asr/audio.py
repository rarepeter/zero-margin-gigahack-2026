"""FFmpeg audio preparation: normalisation, pause detection and segment cutting."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import Segmentation


class AudioPreparationError(Exception):
    """The recording could not be decoded or cut."""


@dataclass(frozen=True, slots=True)
class Span:
    start: float
    end: float


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            command, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=1800
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AudioPreparationError(f"{Path(command[0]).name} could not run") from exc
    if completed.returncode != 0:
        raise AudioPreparationError(f"{Path(command[0]).name} exited with {completed.returncode}")
    return completed


def normalize(ffmpeg: str, source: Path, target: Path) -> None:
    """Convert the first audio track to 16 kHz, mono, PCM16 WAV."""
    _run([
        ffmpeg, "-nostdin", "-v", "error", "-y", "-i", str(source),
        "-map", "0:a:0", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(target),
    ])


def probe(ffprobe: str, source: Path) -> tuple[float, datetime | None]:
    """Return the duration in seconds and the container's creation time, if any."""
    output = _run([
        ffprobe, "-v", "error", "-print_format", "json", "-show_format", str(source),
    ]).stdout
    fmt = json.loads(output).get("format", {})
    recorded_at = None
    created = fmt.get("tags", {}).get("creation_time")
    if created:
        try:
            recorded_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except ValueError:
            recorded_at = None
    return float(fmt["duration"]), recorded_at


def detect_pauses(ffmpeg: str, wav: Path, settings: Segmentation) -> list[Span]:
    """Silences of at least `pause_seconds` below `silence_db`."""
    log = _run([
        ffmpeg, "-nostdin", "-hide_banner", "-i", str(wav),
        "-af", f"silencedetect=noise={settings.silence_db}dB:d={settings.pause_seconds}",
        "-f", "null", "-",
    ]).stderr
    starts = [float(v) for v in re.findall(r"silence_start: (-?[\d.]+)", log)]
    ends = [float(v) for v in re.findall(r"silence_end: ([\d.]+)", log)]
    # Silence that lasts to the end of the file has no silence_end.
    ends += [float("inf")] * (len(starts) - len(ends))
    return [Span(max(0.0, start), end) for start, end in zip(starts, ends)]


def plan_segments(duration: float, pauses: list[Span], settings: Segmentation) -> list[Span]:
    """MedSpeech segmentation: contiguous segments cut at pause midpoints.

    While more than the absolute maximum remains, a segment ends at the
    latest pause midpoint between the target minimum and maximum; failing
    that, at the midpoint closest to the target maximum up to the absolute
    maximum; failing that, at the target maximum. A final segment shorter than
    the minimum joins the previous one when that stays within the maximum.
    """
    points = sorted((p.start + p.end) / 2 for p in pauses if p.end != float("inf"))
    bounds: list[Span] = []
    start = 0.0
    while duration - start > settings.absolute_max_seconds:
        low = start + settings.target_min_seconds
        preferred = [x for x in points if low <= x <= start + settings.target_max_seconds]
        if preferred:
            end = max(preferred)
        else:
            fallback = [x for x in points if low <= x <= start + settings.absolute_max_seconds]
            target = start + settings.target_max_seconds
            end = min(fallback, key=lambda x: abs(x - target)) if fallback else min(target, duration)
        bounds.append(Span(start, end))
        start = end
    if duration > start:
        bounds.append(Span(start, duration))
    if len(bounds) > 1 and bounds[-1].end - bounds[-1].start < settings.min_segment_seconds:
        merged = Span(bounds[-2].start, bounds[-1].end)
        if merged.end - merged.start <= settings.absolute_max_seconds:
            bounds[-2:] = [merged]
    return bounds


def cut(
    ffmpeg: str,
    wav: Path,
    span: Span,
    duration: float,
    settings: Segmentation,
    target: Path,
    *,
    first: bool,
) -> None:
    """Write one segment with previous-content overlap and context padding."""
    overlap = 0.0 if first else settings.overlap_seconds
    start = max(0.0, span.start - overlap - settings.padding_seconds)
    end = min(duration, span.end + settings.padding_seconds)
    _run([
        ffmpeg, "-nostdin", "-v", "error", "-y", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}",
        "-i", str(wav), "-c:a", "pcm_s16le", str(target),
    ])
