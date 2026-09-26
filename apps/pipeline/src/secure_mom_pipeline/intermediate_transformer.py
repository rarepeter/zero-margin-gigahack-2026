"""Replaceable transcription-bytes to UTF-8 text boundary."""

from __future__ import annotations

from typing import Protocol

from .models import TextDocument, TranscriptionSource


class IntermediateTransformationError(ValueError):
    """Raised when a transcription source cannot become valid text."""


class IntermediateTransformer(Protocol):
    def transform(self, source: TranscriptionSource) -> TextDocument: ...


class Utf8IntermediateTransformer:
    """Decode UTF-8 while preserving every decoded character unchanged."""

    def transform(self, source: TranscriptionSource) -> TextDocument:
        try:
            text = source.data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise IntermediateTransformationError(
                "The transcription is not valid UTF-8"
            ) from exc
        return TextDocument(text=text)
