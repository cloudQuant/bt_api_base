"""
 —  logger
 SpdLogManager(...).create_logger()

:
    from bt_api_base.logging_factory import get_logger
    logger = get_logger("feed")          # -> logs/feed.log
    logger = get_logger("event_bus")     # -> logs/event_bus.log
    logger = get_logger("api", print_info=True)  #
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

from bt_api_base.functions.log_message import SpdLogManager

__all__ = ["get_logger", "_LoggerProxy"]

# : module_key -> (file_name, logger_name)
_MODULE_LOG_MAP = {
    "api": ("bt_api.log", "api"),
    "registry": ("bt_api_registry.log", "registry"),
    "feed": ("feed_data.log", "base_feed"),
    "event_bus": ("event_bus.log", "event_bus"),
    "http_client": ("http_client.log", "http_client"),
    "websocket": ("websocket.log", "websocket"),
}

#  logger，
_logger_cache: dict[tuple[str, bool], _LoggerProxy] = {}
_logger_cache_lock = threading.Lock()


class _LoggerProxy:
    """Expose stdlib-style formatting over spdlog's one-string methods."""

    def __init__(self, logger: object) -> None:
        """__init__ method"""
        self._logger = logger
        self._sink_failure_count = 0
        self._sink_failure_lock = threading.Lock()

    @property
    def sink_failure_count(self) -> int:
        """Return the number of formatting or sink failures suppressed by this proxy."""
        try:
            with self._sink_failure_lock:
                return self._sink_failure_count
        except Exception:
            return 0

    def _record_sink_failure(self) -> None:
        """Record a logging failure without invoking another logger."""
        try:
            with self._sink_failure_lock:
                self._sink_failure_count += 1
        except Exception:
            return

    @staticmethod
    def _format_message(args: tuple[Any, ...]) -> str:
        """Render stdlib logging arguments for spdlog's one-string methods."""
        if not args:
            return ""
        message = args[0]
        if len(args) == 1:
            return str(message)
        if not isinstance(message, str):
            return str(message)
        values: object = args[1:]
        if len(args) == 2 and isinstance(args[1], dict):
            values = args[1]
        try:
            return message % values
        except Exception:
            # Logging must never replace the application exception being
            # reported. Keep the template if a caller supplied invalid args.
            return message

    def _emit(
        self, method_name: str, fallback_name: str | None, args: tuple[Any, ...]
    ) -> None:
        try:
            method = getattr(self._logger, method_name, None)
            if method is None and fallback_name is not None:
                method = getattr(self._logger, fallback_name, None)
            if method is not None:
                method(self._format_message(args))
        except Exception:
            # A broken sink must not replace an exchange response or interrupt
            # an authenticated websocket callback. Do not log recursively here.
            self._record_sink_failure()
            return

    def debug(self, *args: Any, **_kwargs: Any) -> None:
        """Log a debug message without leaking formatting args to spdlog."""
        self._emit("debug", None, args)

    def info(self, *args: Any, **_kwargs: Any) -> None:
        """Log an info message without leaking formatting args to spdlog."""
        self._emit("info", None, args)

    def warning(self, *args: Any, **_kwargs: Any) -> None:
        """warning method"""
        self._emit("warning", "warn", args)

    def warn(self, *args: Any, **_kwargs: Any) -> None:
        """warn method"""
        self._emit("warn", "warning", args)

    def error(self, *args: Any, **_kwargs: Any) -> None:
        """Log an error message without leaking formatting args to spdlog."""
        self._emit("error", None, args)

    def critical(self, *args: Any, **_kwargs: Any) -> None:
        """Log a critical message without leaking formatting args to spdlog."""
        self._emit("critical", "error", args)

    def exception(self, *args: Any, **_kwargs: Any) -> None:
        """Use the logger's exception method when available, otherwise error."""
        self._emit("exception", "error", args)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._logger, name)


def _resolve_log_file_name(file_name: str) -> str:
    """Resolve a log file name with optional environment-based log directory."""
    log_dir = os.getenv("BT_API_LOG_DIR")
    if not log_dir or os.path.isabs(file_name):
        return file_name

    return str(Path(log_dir).expanduser() / file_name)


def _build_custom_log_file_name(module: str) -> str:
    """Build a safe log file name for custom module keys."""
    sanitized = "".join(
        ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in module
    )
    sanitized = sanitized.strip("._") or "bt_api"
    return f"{sanitized}.log"


def get_logger(module: str, print_info: bool = False) -> _LoggerProxy:
    """logger

    :param module: ， "api", "feed", "event_bus"，
                   （ {module}.log）
    :param print_info:
    :return: spdlog logger （ _LoggerProxy ）
    """
    cache_key = (module, print_info)
    with _logger_cache_lock:
        cached_logger: _LoggerProxy | None = _logger_cache.get(cache_key)
        if cached_logger is not None:
            return cached_logger
        if module in _MODULE_LOG_MAP:
            file_name, logger_name = _MODULE_LOG_MAP[module]
        else:
            file_name = _build_custom_log_file_name(module)
            logger_name = module

        logger = _LoggerProxy(
            SpdLogManager(
                file_name=_resolve_log_file_name(file_name),
                logger_name=logger_name,
                print_info=print_info,
            ).create_logger()
        )
        _logger_cache[cache_key] = logger
        return logger
