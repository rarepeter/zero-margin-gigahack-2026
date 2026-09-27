"""Run a converted Whisper model through whisper.cpp's whisper-server.

Each model gets one child process on a free loopback port and stays loaded
between segments and jobs. Requests carry the decoding options, so the same
process serves forced-language transcription and language identification.
"""

from __future__ import annotations

import logging
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx


logger = logging.getLogger("secure_mom_asr")

ModelState = Literal["stopped", "loading", "ready", "failed"]


class ModelUnavailableError(Exception):
    """whisper-server or the model file could not be started."""


class RecognitionError(Exception):
    """whisper-server failed while decoding a segment."""


@dataclass(frozen=True, slots=True)
class Recognition:
    text: str
    avg_logprob: float
    no_speech_prob: float
    # Mean token probability; the segment confidence reported to the pipeline.
    confidence: float | None


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class WhisperServer:
    """One whisper-server child process for one ggml model."""

    def __init__(
        self, name: str, binary: str, model_path: Path | None, threads: int, log_dir: Path
    ) -> None:
        self.name = name
        self.binary = binary
        self.model_path = model_path
        self.threads = threads
        self.log_path = log_dir / f"whisper-server-{name}.log"
        self.state: ModelState = "stopped"
        self._process: subprocess.Popen[bytes] | None = None
        self._client: httpx.Client | None = None

    def ensure_ready(self) -> None:
        """Start whisper-server unless it is already running, then wait for it."""
        if self._process is not None and self._process.poll() is None:
            return
        self.stop()
        self.state = "loading"
        try:
            self._start()
        except ModelUnavailableError:
            self.state = "failed"
            self.stop(keep_state=True)
            raise
        self.state = "ready"

    def _start(self) -> None:
        if self.model_path is None or not self.model_path.is_file():
            raise ModelUnavailableError(f"the {self.name} model file is missing")
        port = _free_port()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            self.binary,
            "--model", str(self.model_path),
            "--host", "127.0.0.1",
            "--port", str(port),
            "--threads", str(self.threads),
        ]
        started = time.monotonic()
        try:
            with self.log_path.open("ab") as log:
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
        except OSError as exc:
            raise ModelUnavailableError("whisper-server could not be started") from exc
        client = httpx.Client(
            base_url=f"http://127.0.0.1:{port}", timeout=httpx.Timeout(30.0, read=600.0)
        )
        self._process, self._client = process, client
        while True:
            if process.poll() is not None:
                raise ModelUnavailableError(
                    f"whisper-server ({self.name}) exited while loading; see {self.log_path}"
                )
            try:
                if client.get("/").status_code == 200:
                    break
            except (httpx.HTTPError, RuntimeError):
                pass
            time.sleep(0.25)
        logger.info("event=whisper_ready model=%s load_s=%.1f", self.name, time.monotonic() - started)

    def stop(self, *, keep_state: bool = False) -> None:
        process, client = self._process, self._client
        self._process, self._client = None, None
        if not keep_state:
            self.state = "stopped"
        if client is not None:
            client.close()
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    def _inference(self, wav: Path, fields: dict[str, str]) -> dict:
        self.ensure_ready()
        assert self._client is not None
        try:
            with wav.open("rb") as audio:
                response = self._client.post(
                    "/inference",
                    files={"file": (wav.name, audio, "audio/wav")},
                    data={"response_format": "verbose_json", **fields},
                )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, OSError, ValueError) as exc:
            raise RecognitionError(f"whisper-server ({self.name}) failed") from exc

    def transcribe(self, wav: Path, language: str, prompt: str = "") -> Recognition:
        """Greedy decoding in one forced language, without previous-text context.

        whisper.cpp retries at a higher temperature only when its entropy check
        detects a repetition loop. Timestamp tokens are off: FraPiz skips audio
        when it has to predict them. `prompt` is the lexicon-assisted mode's
        hotword list; strict mode sends none.
        """
        fields = {
            "language": language,
            "temperature": "0",
            "temperature_inc": "0.2",
            "no_timestamps": "true",
            "no_language_probabilities": "true",
        }
        if prompt:
            fields["prompt"] = prompt
        body = self._inference(wav, fields)
        segments = body.get("segments", [])
        tokens = [word for segment in segments for word in segment.get("words", [])]
        weights = [max(1, len(segment.get("words", []))) for segment in segments]
        total = sum(weights)
        avg_logprob = (
            sum(s.get("avg_logprob", 0.0) * w for s, w in zip(segments, weights)) / total
            if total else 0.0
        )
        no_speech = max((s.get("no_speech_prob", 0.0) for s in segments), default=1.0)
        probabilities = [word["probability"] for word in tokens if "probability" in word]
        return Recognition(
            text=" ".join(body.get("text", "").split()),
            avg_logprob=avg_logprob,
            no_speech_prob=no_speech,
            confidence=sum(probabilities) / len(probabilities) if probabilities else None,
        )

    def identify_language(self, wav: Path) -> dict[str, float]:
        """Language probabilities for the segment, keyed by ISO code."""
        body = self._inference(wav, {"detect_language": "true"})
        return {code: float(p) for code, p in body.get("language_probabilities", {}).items()}
