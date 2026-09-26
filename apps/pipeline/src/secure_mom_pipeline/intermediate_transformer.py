"""Structured transcription-result to plain-text MoM input boundary."""

from __future__ import annotations

from typing import Protocol

from pydantic import ValidationError

from .models import TextDocument, TranscriptionResult, TranscriptionSource


class IntermediateTransformationError(ValueError):
    """Raised when a transcription source cannot become valid text."""


class IntermediateTransformer(Protocol):
    def transform(self, source: TranscriptionSource) -> TextDocument: ...


class StructuredTranscriptionTransformer:
    """Validate transcription.v1alpha1 and extract its complete transcript text."""

    def transform(self, source: TranscriptionSource) -> TextDocument:
        if source.media_type.split(";", 1)[0].strip().lower() != "application/json":
            raise IntermediateTransformationError(
                "The transcription source must use application/json"
            )
        try:
            result = TranscriptionResult.model_validate_json(source.data)
        except (ValidationError, ValueError) as exc:
            raise IntermediateTransformationError(
                "The transcription does not match transcription.v1alpha1"
            ) from exc
        return TextDocument(text=result.transcript.text)
