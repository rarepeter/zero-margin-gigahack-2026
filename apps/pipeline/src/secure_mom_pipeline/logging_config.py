"""Local operational logging without meeting-derived content."""

from __future__ import annotations

import logging
from pathlib import Path


LOGGER_NAME = "secure_mom_pipeline"


def configure_logging(log_file: Path) -> logging.Logger:
    """Configure one process-local file logger and return it."""
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return logger

    # TODO(discovery, TD-029): confirm log format, rotation, and content policy.
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(process)d %(name)s %(message)s"
        )
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger
