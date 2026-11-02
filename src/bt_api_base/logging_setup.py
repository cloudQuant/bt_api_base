"""Shared explicit process-logging configuration for SDK consumers."""

from __future__ import annotations

import logging
from pathlib import Path

LOG_LEVELS = {
    "CRITICAL": logging.CRITICAL,
    "FATAL": logging.FATAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
    "NOTSET": logging.NOTSET,
}


def resolve_log_level(level: object) -> int:
    if not isinstance(level, str):
        raise ValueError("log_level must be a valid logging level name")

    normalized_level = level.strip().upper()
    if normalized_level not in LOG_LEVELS:
        valid_levels = ", ".join(sorted(LOG_LEVELS))
        raise ValueError(f"log_level must be one of: {valid_levels}")

    return LOG_LEVELS[normalized_level]


def setup_logging_for_production(log_file: str, level: str = "INFO") -> None:
    """Configure process logging for monitoring setup."""
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(log_path),
        level=resolve_log_level(level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


__all__ = ("LOG_LEVELS", "resolve_log_level", "setup_logging_for_production")
