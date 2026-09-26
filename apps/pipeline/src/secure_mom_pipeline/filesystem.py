"""Small caller-directed services for byte and UTF-8 text files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class UnsafeRelativePathError(ValueError):
    """Raised when a caller tries to address a file outside the service root."""


@dataclass(frozen=True, slots=True)
class _RootedFileService:
    root: Path

    def _resolve(self, relative_path: str | Path) -> Path:
        candidate_input = Path(relative_path)
        if candidate_input.is_absolute():
            raise UnsafeRelativePathError("An absolute file path is not allowed")

        root = self.root.resolve()
        candidate = (root / candidate_input).resolve()
        if not candidate.is_relative_to(root):
            raise UnsafeRelativePathError("The file path escapes the configured root")
        return candidate


class BinaryFileService(_RootedFileService):
    """Read and write unmodified bytes, including uploaded audio bytes."""

    def write(self, relative_path: str | Path, data: bytes) -> None:
        target = self._resolve(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def read(self, relative_path: str | Path) -> bytes:
        return self._resolve(relative_path).read_bytes()


class TextFileService(_RootedFileService):
    """Read and write UTF-8 text without imposing an artifact schema."""

    def write(self, relative_path: str | Path, text: str) -> None:
        target = self._resolve(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def read(self, relative_path: str | Path) -> str:
        return self._resolve(relative_path).read_text(encoding="utf-8")
