"""Run the local model through llama.cpp's llama-server and generate a draft.

The service starts llama-server as a child process on a free loopback port and
keeps the model loaded between jobs. Generation takes two streamed phases,
because llama.cpp cannot combine this model's reasoning channel with a JSON
grammar in one chat request:

1. The model reasons freely on its `to=self` channel, up to a token budget.
2. The prompt is extended with that reasoning and the header of the answer
   channel, and the answer is generated under the draft's JSON-schema grammar.

No read timeout applies. A long meeting takes many minutes, most of it with a
steady token stream; the stream ends when the model finishes or the child
process exits.
"""

from __future__ import annotations

import json
import logging
import socket
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from .config import LlmSettings


logger = logging.getLogger("secure_mom_llm")

# Muse Glimmer's chat format. The generation prompt ends with
# "<|start|>assistant"; the model continues with its recipient.
REASONING_HEADER = " to=self<|message|>"
ANSWER_HEADER = "<|start|>assistant to=user<|message|>"
REASONING_STOPS = ["<|start|>", "<|eom|>", "<|eot|>"]
# Published defaults from meta-models/Muse-Glimmer-30B generation_config.json,
# the settings the MoM benchmark evaluated.
SAMPLING = {"temperature": 1.0, "top_p": 0.95, "top_k": 64}
PROGRESS_LOG_SECONDS = 30.0

ModelState = Literal["stopped", "loading", "ready", "failed"]


class ModelUnavailableError(Exception):
    """llama-server or the model file could not be started."""


class TranscriptTooLongError(Exception):
    """The prompt and token budgets exceed the configured context."""


class GenerationError(Exception):
    """llama-server failed or stopped before the answer was complete."""


@dataclass(frozen=True, slots=True)
class Generation:
    text: str
    prompt_tokens: int
    reasoning_tokens: int
    answer_tokens: int


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class LlamaServer:
    """One llama-server child process serving one generation at a time."""

    def __init__(self, settings: LlmSettings) -> None:
        self.settings = settings
        self.state: ModelState = "stopped"
        self._process: subprocess.Popen[bytes] | None = None
        self._client: httpx.Client | None = None

    def ensure_ready(self) -> None:
        """Start llama-server unless it is already running, then wait for it."""
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
        model = self.settings.model_path
        if model is None:
            raise ModelUnavailableError("MOM_LLM_MODEL_PATH is not set")
        if not model.is_file():
            raise ModelUnavailableError("MOM_LLM_MODEL_PATH does not point to a file")
        port = _free_port()
        log_path = self.settings.log_file.parent / "llama-server.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            self.settings.llama_server_bin,
            "--model", str(model),
            "--host", "127.0.0.1",
            "--port", str(port),
            "--ctx-size", str(self.settings.context_tokens),
            "--parallel", "1",
            "--n-gpu-layers", "999",
            "--flash-attn", "on",
            "--jinja",
            "--no-webui",
            # The HTTP read/write timeout; generous so a slow request never
            # trips it.
            "--timeout", "86400",
        ]
        started = time.monotonic()
        try:
            with log_path.open("ab") as log:
                process = subprocess.Popen(
                    command, stdin=subprocess.DEVNULL, stdout=log, stderr=log
                )
        except OSError as exc:
            raise ModelUnavailableError("llama-server could not be started") from exc
        client = httpx.Client(
            base_url=f"http://127.0.0.1:{port}",
            timeout=httpx.Timeout(30.0, read=None),
        )
        self._process, self._client = process, client
        logger.info("event=llama_loading port=%d", port)
        # Loading reads the whole model from disk; wait for as long as the
        # process lives rather than guessing a deadline. stop() from another
        # thread ends the wait by terminating the process.
        while True:
            if process.poll() is not None:
                raise ModelUnavailableError(
                    f"llama-server exited while loading; see {log_path}"
                )
            try:
                if client.get("/health").status_code == 200:
                    break
            except (httpx.HTTPError, RuntimeError):
                pass
            time.sleep(0.5)
        logger.info("event=llama_ready load_s=%.1f", time.monotonic() - started)

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

    def generate(self, system: str, user: str, schema: dict[str, Any]) -> Generation:
        client = self._client
        if client is None or self.state != "ready":
            raise GenerationError("llama-server is not running")
        try:
            prompt = client.post(
                "/apply-template",
                json={
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "chat_template_kwargs": {
                        "reasoning_strength": self.settings.reasoning_strength
                    },
                },
            ).raise_for_status().json()["prompt"] + REASONING_HEADER
            prompt_tokens = len(
                client.post("/tokenize", json={"content": prompt})
                .raise_for_status()
                .json()["tokens"]
            )
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise GenerationError("llama-server could not prepare the prompt") from exc

        budget = (
            prompt_tokens
            + self.settings.reasoning_max_tokens
            + self.settings.answer_max_tokens
        )
        if budget > self.settings.context_tokens:
            raise TranscriptTooLongError(
                f"{budget} tokens needed, {self.settings.context_tokens} configured"
            )
        logger.info("event=llama_prompt prompt_tokens=%d", prompt_tokens)

        reasoning, reasoning_end = self._complete(
            client,
            "reasoning",
            {
                "prompt": prompt,
                "n_predict": self.settings.reasoning_max_tokens,
                "stop": REASONING_STOPS,
            },
        )
        answer, answer_end = self._complete(
            client,
            "answer",
            {
                "prompt": f"{prompt}{reasoning.rstrip()}\n\n{ANSWER_HEADER}",
                "n_predict": self.settings.answer_max_tokens,
                "json_schema": schema,
            },
        )
        if answer_end.get("stop_type") == "limit":
            raise GenerationError("The answer reached MOM_LLM_ANSWER_MAX_TOKENS")
        return Generation(
            text=answer,
            prompt_tokens=prompt_tokens,
            reasoning_tokens=int(reasoning_end.get("tokens_predicted", 0)),
            answer_tokens=int(answer_end.get("tokens_predicted", 0)),
        )

    def _complete(
        self, client: httpx.Client, phase: str, body: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        """Stream one /completion request; return its text and final chunk."""
        parts: list[str] = []
        tokens = 0
        started = last_log = time.monotonic()
        request = {**body, **SAMPLING, "cache_prompt": True, "stream": True}
        try:
            with client.stream("POST", "/completion", json=request) as response:
                if response.status_code != 200:
                    raise GenerationError(
                        f"llama-server answered {response.status_code} in {phase}"
                    )
                for line in response.iter_lines():
                    if line.startswith("error:"):
                        raise GenerationError(f"llama-server reported an error in {phase}")
                    if not line.startswith("data: "):
                        continue
                    chunk = json.loads(line.removeprefix("data: "))
                    parts.append(chunk.get("content", ""))
                    if chunk.get("stop"):
                        timings = chunk.get("timings", {})
                        logger.info(
                            "event=llama_phase_done phase=%s stop_type=%s tokens=%s "
                            "prompt_tokens=%s prompt_tok_s=%.1f gen_tok_s=%.1f elapsed_s=%.1f",
                            phase,
                            chunk.get("stop_type"),
                            chunk.get("tokens_predicted"),
                            timings.get("prompt_n"),
                            timings.get("prompt_per_second", 0.0),
                            timings.get("predicted_per_second", 0.0),
                            time.monotonic() - started,
                        )
                        return "".join(parts), chunk
                    tokens += 1
                    now = time.monotonic()
                    if now - last_log >= PROGRESS_LOG_SECONDS:
                        last_log = now
                        logger.info(
                            "event=llama_progress phase=%s tokens=%d elapsed_s=%.0f",
                            phase,
                            tokens,
                            now - started,
                        )
        except (httpx.HTTPError, ValueError, RuntimeError) as exc:
            raise GenerationError(f"llama-server stream failed in {phase}") from exc
        raise GenerationError(f"llama-server ended the {phase} stream early")
