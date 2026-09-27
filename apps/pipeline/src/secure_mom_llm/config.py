"""Configuration for the local MoM service, read once from the environment."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast


OutputLanguage = Literal["ro", "ru", "en"]
ReasoningStrength = Literal["low", "medium", "high"]


def _choice[T: str](name: str, fallback: T, allowed: tuple[T, ...]) -> T:
    value = os.getenv(name, fallback)
    if value not in allowed:
        raise ValueError(f"{name} must be one of {', '.join(allowed)}")
    return cast(T, value)


@dataclass(frozen=True, slots=True)
class LlmSettings:
    host: str
    port: int
    storage_root: Path
    log_file: Path

    # Where finished drafts and failures are pushed. Routes match the pipeline
    # defaults; `{job_id}` is the pipeline job ID.
    callback_base_url: str
    result_route: str
    failure_route: str

    llama_server_bin: str
    model_path: Path | None
    # Muse Glimmer 30B was trained on 131,072 tokens. Only 13 of its 52 layers
    # use full attention, so a long context costs little memory.
    context_tokens: int
    reasoning_strength: ReasoningStrength
    # Token budgets. Reasoning that reaches its budget is cut short and the
    # model is asked for the answer; an answer that reaches its budget fails.
    reasoning_max_tokens: int
    answer_max_tokens: int

    output_language: OutputLanguage


def get_llm_settings() -> LlmSettings:
    model_path = os.getenv("MOM_LLM_MODEL_PATH")
    return LlmSettings(
        host=os.getenv("MOM_LLM_HOST", "127.0.0.1"),
        port=int(os.getenv("MOM_LLM_PORT", "8102")),
        storage_root=Path(
            os.getenv("MOM_LLM_STORAGE_ROOT", "runtime/mom-llm")
        ).expanduser(),
        log_file=Path(
            os.getenv("MOM_LLM_LOG_FILE", "runtime/logs/mom-llm.log")
        ).expanduser(),
        callback_base_url=os.getenv(
            "MOM_LLM_CALLBACK_BASE_URL", "http://127.0.0.1:8000"
        ),
        result_route=os.getenv(
            "MOM_LLM_RESULT_ROUTE", "/api/v1/integrations/text/jobs/{job_id}/mom"
        ),
        failure_route=os.getenv(
            "MOM_LLM_FAILURE_ROUTE",
            "/api/v1/integrations/text/jobs/{job_id}/failure",
        ),
        llama_server_bin=os.getenv("MOM_LLM_LLAMA_SERVER_BIN")
        or shutil.which("llama-server")
        or "llama-server",
        model_path=Path(model_path).expanduser() if model_path else None,
        context_tokens=int(os.getenv("MOM_LLM_CONTEXT_TOKENS", "65536")),
        reasoning_strength=_choice(
            "MOM_LLM_REASONING_STRENGTH", "medium", ("low", "medium", "high")
        ),
        reasoning_max_tokens=int(os.getenv("MOM_LLM_REASONING_MAX_TOKENS", "8192")),
        answer_max_tokens=int(os.getenv("MOM_LLM_ANSWER_MAX_TOKENS", "16384")),
        output_language=_choice("MOM_LLM_OUTPUT_LANGUAGE", "ro", ("ro", "ru", "en")),
    )
