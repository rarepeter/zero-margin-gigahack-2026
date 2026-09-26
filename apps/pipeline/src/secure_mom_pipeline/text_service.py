"""Replaceable HTTP boundary for the text/MoM ML service."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from pathlib import Path
from threading import Lock, Timer
from typing import Final
from uuid import uuid4

import httpx
from pydantic import ValidationError

from .callback_transport import CallbackSender
from .models import TextSubmission


logger = logging.getLogger("secure_mom_pipeline")
MOCK_MOM_DOCUMENT: Final = {
    # This fixture deliberately exercises the same document sections and
    # uncertainty UI as the portal's richer multilingual demo. It is served by
    # the pipeline mock so live-mode integration is meaningful as well.
    "schemaVersion": 1,
    "quality": {"momConfidence": 0.86, "confidenceScale": "ZERO_TO_ONE"},
    "document": {
        "header": {
            "subject": "Revizuirea profilaxiei antibiotice perioperatorii",
            "meeting_type": "medical",
            "meeting_type_confidence": "high",
            "date": "2026-09-25",
            "date_source": "recording",
            "duration_min": 52,
            "languages": {"ro": 0.71, "ru": 0.21, "en": 0.08},
            "participants_mentioned": [
                {"name": "Participant 1", "role": None, "role_stated": False},
                {"name": "Participant 2", "role": None, "role_stated": False},
                {"name": "Participant 3", "role": None, "role_stated": False},
                {"name": "Participant 4", "role": None, "role_stated": False},
            ],
        },
        "summary": (
            "A fost analizat momentul administrării profilaxiei antibiotice și "
            "datele privind infecțiile postoperatorii. Două decizii, trei acțiuni."
        ),
        "decisions": [
            {
                "id": "D1",
                "text": "Cefazolină 2 g i.v., cu 30–60 min înainte de incizie, devine prima linie în chirurgia generală electivă.",
                "status": "decided",
                "evidence": {"quote": "Deci, решили — cefazolina două grame, 30–60 minute înainte de incizie.", "lang": "mixed", "segment_id": "segment-4", "t": "00:41:12", "speaker": "Participant 1"},
                "flags": [],
            },
            {
                "id": "D2",
                "text": "Momentul administrării se înregistrează în lista de verificare, înainte de time-out.",
                "status": "decided",
                "evidence": {"quote": "OK, agreed — timpul administrării intră în checklist, înainte de time-out.", "lang": "mixed", "segment_id": "segment-5", "t": "00:44:30", "speaker": "Participant 4"},
                "flags": [],
            },
            {
                "id": "D3",
                "text": "Redozare la intervențiile de peste 4 ore, cu avizul farmaciei.",
                "status": "proposed",
                "evidence": {"quote": "Poate facem redosing la patru ore? — Да, но надо проверить с фармацией.", "lang": "mixed", "segment_id": "segment-6", "t": "00:46:05", "speaker": "Participant 2"},
                "flags": [{"type": "decision_status", "reason": "A fost decis sau doar propus?", "blocking": True, "candidates": ["decided", "proposed"]}],
            },
        ],
        "actions": [
            {
                "id": "A1", "text": "Actualizarea protocolului de profilaxie", "decision_ids": ["D1"], "owner": "Participant 3",
                "deadline": {"spoken": "până vineri viitoare", "resolved": "2026-10-02"},
                "evidence": {"quote": "Protocolul actualizat — până vineri viitoare.", "lang": "ro", "segment_id": "segment-4", "t": "00:43:10", "speaker": "Participant 1"},
                "flags": [{"type": "deadline", "reason": "„Până vineri viitoare” a fost calculat ca 02.10.2026. Corect?", "blocking": True, "candidates": ["2026-10-02", "2026-10-09"]}],
            },
            {
                "id": "A2", "text": "Instruirea asistentelor din blocul operator", "decision_ids": ["D1", "D2"], "owner": "Participant 4",
                "deadline": {"spoken": "до первого октября", "resolved": "2026-09-30"},
                "evidence": {"quote": "Instruirea asistentelor o fac eu, до первого октября.", "lang": "mixed", "segment_id": "segment-5", "t": "00:44:52", "speaker": "Participant 4"},
                "flags": [],
            },
            {
                "id": "A3", "text": "Extragerea datelor pentru auditul T4", "owner": None,
                "deadline": {"spoken": None, "resolved": None},
                "evidence": {"quote": "Datele pentru auditul pe T4 trebuie scoase din sistem… cineva de la statistică.", "lang": "ro", "segment_id": "segment-6", "t": "00:47:03", "speaker": "Participant 1"},
                "flags": [{"type": "owner", "reason": "Nimeni nu a fost desemnat. Cine răspunde?", "blocking": True, "candidates": ["Participant 2", "Participant 4"]}],
            },
        ],
        "findings": [
            {
                "text": "Rata infecțiilor de plagă postoperatorie în T3: 4,2%, față de 2,9% în T2.",
                "evidence": {"quote": "Patru virgulă doi la sută, față de doi virgulă nouă.", "lang": "ro", "segment_id": "segment-2", "t": "00:12:40", "speaker": "Participant 1"},
                "flags": [{"type": "number", "reason": "S-a auzit „4,2%” sau „4,7%”?", "blocking": True, "candidates": ["4,2%", "4,7%"]}],
            },
            {
                "text": "Antibioticul este administrat după incizie în 37% din cazuri.",
                "evidence": {"quote": "в тридцати семи процентах случаев antibioticul se face după incizie", "lang": "mixed", "segment_id": "segment-3", "t": "00:14:05", "speaker": "Participant 4"},
                "flags": [],
            },
        ],
        "topics": [{"title": "Momentul administrării", "text": "Profilaxia este administrată prea târziu într-o parte semnificativă a cazurilor."}],
        "risks": [{"text": "Pacienții alergici la beta-lactamine: alternativa nu a fost stabilită.", "category": "clinical", "raised_by": "Participant 2", "evidence": {"quote": "alergia la beta-lactamine trebuie clarificată separat", "lang": "ro", "segment_id": "segment-6", "t": "00:50:18", "speaker": "Participant 2"}}],
        "open_questions": [{"text": "Schema alternativă pentru alergia la beta-lactamine.", "raised_by": "Participant 2"}],
    },
}


class TextSubmissionError(RuntimeError):
    """Base class for safe text-service submission failures."""

    retryable = False


class TextConnectionError(TextSubmissionError):
    retryable = True


class TextProtocolError(TextSubmissionError):
    retryable = False


class HttpTextService:
    def __init__(
        self,
        base_url: str,
        jobs_route: str,
        timeout_seconds: float,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.url = f"{base_url.rstrip('/')}/{jobs_route.lstrip('/')}"
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def submit(
        self,
        pipeline_job_id: str,
        text_path: Path,
        idempotency_key: str,
    ) -> TextSubmission:
        if not text_path.is_absolute():
            raise TextProtocolError("The text input path must be absolute")
        if not text_path.is_file() or not os.access(text_path, os.R_OK):
            raise TextProtocolError("The text input is not readable")

        try:
            stream = text_path.open("rb")
        except OSError as exc:
            raise TextProtocolError("The text input could not be read") from exc

        try:
            with stream:
                with httpx.Client(
                    timeout=self.timeout_seconds,
                    transport=self.transport,
                ) as client:
                    response = client.post(
                        self.url,
                        headers={
                            "X-Pipeline-Job-Id": pipeline_job_id,
                            "Idempotency-Key": idempotency_key,
                        },
                        files={
                            "transcript": (
                                "transcript.txt",
                                stream,
                                "text/plain; charset=utf-8",
                            )
                        },
                    )
        except httpx.TransportError as exc:
            raise TextConnectionError("The text service could not be reached") from exc

        if response.status_code != 202:
            raise TextProtocolError("The text service rejected the transcription")
        try:
            return TextSubmission.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise TextProtocolError(
                "The text service returned an invalid acknowledgement"
            ) from exc


class MockTextService:
    """Acknowledge UTF-8 text, then push a deterministic mock MoM document."""

    def __init__(
        self,
        callback_url_template: str | None = None,
        callback_delay_seconds: float = 5.0,
        *,
        transport: httpx.BaseTransport | None = None,
        callback_sender: CallbackSender | None = None,
    ) -> None:
        self.callback_url_template = callback_url_template
        self.callback_delay_seconds = callback_delay_seconds
        self.transport = transport
        self.callback_sender = callback_sender
        self._scheduled: set[tuple[str, str]] = set()
        self._schedule_lock = Lock()

    def submit(
        self,
        pipeline_job_id: str,
        text_path: Path,
        idempotency_key: str,
    ) -> TextSubmission:
        del idempotency_key
        if not text_path.is_absolute() or not text_path.is_file():
            raise TextProtocolError("The text input is not readable")
        try:
            text_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise TextProtocolError("The text input is not valid UTF-8") from exc
        submission = TextSubmission(
            model_job_id=f"mock-text-{uuid4()}",
            status="accepted",
        )
        self.ensure_callback(pipeline_job_id, submission.model_job_id)
        return submission

    def ensure_callback(self, pipeline_job_id: str, model_job_id: str) -> None:
        if self.callback_url_template is None:
            return
        key = (pipeline_job_id, model_job_id)
        with self._schedule_lock:
            if key in self._scheduled:
                return
            self._scheduled.add(key)

        timer = Timer(
            self.callback_delay_seconds,
            self._send_callback,
            args=(pipeline_job_id, model_job_id),
        )
        timer.daemon = True
        timer.start()
        logger.info(
            "event=mock_text_callback_scheduled job_id=%s model_job_id=%s delay_seconds=%s",
            pipeline_job_id,
            model_job_id,
            self.callback_delay_seconds,
        )

    def _send_callback(self, pipeline_job_id: str, model_job_id: str) -> None:
        callback_succeeded = False
        try:
            callback_url = self.callback_url_template.format(job_id=pipeline_job_id)
            payload = json.dumps(
                MOCK_MOM_DOCUMENT,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            headers: Mapping[str, str] = {
                "Content-Type": "application/json",
                "X-Text-Model-Job-Id": model_job_id,
            }
            if self.callback_sender is not None:
                status_code = self.callback_sender(callback_url, payload, headers)
            else:
                with httpx.Client(timeout=5.0, transport=self.transport) as client:
                    response = client.post(
                        callback_url,
                        content=payload,
                        headers=headers,
                    )
                status_code = response.status_code
            callback_succeeded = 200 <= status_code < 300
            if callback_succeeded:
                logger.info(
                    "event=mock_text_callback_accepted job_id=%s model_job_id=%s status_code=%d",
                    pipeline_job_id,
                    model_job_id,
                    status_code,
                )
            else:
                logger.error(
                    "event=mock_text_callback_rejected job_id=%s model_job_id=%s status_code=%d",
                    pipeline_job_id,
                    model_job_id,
                    status_code,
                )
        except (httpx.TransportError, RuntimeError, ValueError) as exc:
            logger.error(
                "event=mock_text_callback_failed job_id=%s model_job_id=%s "
                "error_type=%s",
                pipeline_job_id,
                model_job_id,
                type(exc).__name__,
            )
        finally:
            if not callback_succeeded:
                with self._schedule_lock:
                    self._scheduled.discard((pipeline_job_id, model_job_id))
