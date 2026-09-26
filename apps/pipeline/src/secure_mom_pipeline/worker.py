"""Separately runnable mock worker with no orchestration behavior."""

from __future__ import annotations

import argparse
import time

from .config import get_settings
from .logging_config import configure_logging


# TODO(discovery, TD-027): replace this illustrative sequence only after the
# real pipeline transition ownership and completion boundary are confirmed.
MOCK_TRANSITIONS = ("MOCK_IDLE", "MOCK_TRIGGERED", "MOCK_FINISHED")


def run_mock_cycle() -> None:
    settings = get_settings()
    logger = configure_logging(settings.log_file)
    for state in MOCK_TRANSITIONS:
        logger.info("event=mock_worker_transition state=%s", state)


def run() -> None:
    parser = argparse.ArgumentParser(description="Run the non-functional worker")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Log one mock cycle and exit (useful for smoke checks)",
    )
    args = parser.parse_args()
    settings = get_settings()

    if args.once:
        run_mock_cycle()
        return

    # TODO(discovery): replace polling with the real persisted work source.
    while True:
        run_mock_cycle()
        time.sleep(settings.mock_worker_interval_seconds)


if __name__ == "__main__":
    run()
