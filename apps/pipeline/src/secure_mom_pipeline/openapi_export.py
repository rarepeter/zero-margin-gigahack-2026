"""Export the FastAPI-generated contract to a caller-selected file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .api import app


def export_openapi(output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def run() -> None:
    parser = argparse.ArgumentParser(description="Export pipeline OpenAPI JSON")
    parser.add_argument(
        "output",
        type=Path,
        help="Caller-selected output path; no runtime path is assumed",
    )
    args = parser.parse_args()
    export_openapi(args.output)


if __name__ == "__main__":
    run()
