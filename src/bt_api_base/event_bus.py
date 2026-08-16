"""
 — /
 Queue （） Callback （ CTP SPI / IB EWrapper  API）
"""

from __future__ import annotations

import threading
import traceback
from collections import defaultdict
from collections.abc import Callable
from enum import Enum
from typing import Any

from bt_api_base.exceptions import BtApiError
from bt_api_base.logging_factory import get_logger

__all__ = ["EventBus", "ErrorHandlerMode", "ErrorSeverity"]


class ErrorHandlerMode(Enum):
    """"""

    LOG = "log"
    RAISE = "raise"
    COLLECT = "collect"


class ErrorSeverity(Enum):
    """"""

    USER_ERROR = "user_error"
    BUSINESS_ERROR = "business_error"
    SYSTEM_ERROR = "system_error"


def _classify_error(error: Exception) -> ErrorSeverity:
    if isinstance(error, BtApiError):
        return ErrorSeverity.BUSINESS_ERROR

    user_error_types = (TypeError, ValueError, AttributeError, KeyError, IndexError)
    system_error_types = (ConnectionError, OSError, TimeoutError, RuntimeError)

    if isinstance(error, user_error_types):
        return ErrorSeverity.USER_ERROR
    if isinstance(error, system_error_types):
        return ErrorSeverity.SYSTEM_ERROR

    return ErrorSeverity.SYSTEM_ERROR


class EventBus:
    """，"""

    def __init__(
        self,
        logger: Any = None,
        error_mode: ErrorHandlerMode = ErrorHandlerMode.LOG,
    ) -> None:
        """__init__ method"""
        self._handlers: defaultdict[str, list[Callable[..., Any]]] = defaultdict(list)
        self._lock = threading.RLock()
        self.logger = logger or get_logger("event_bus")
        self.error_mode = error_mode
        self._last_errors: list[tuple[str, Callable[..., Any], Exception]] = []

    def on(self, event_type: str, handler: Callable[..., Any]) -> None:
        """on method"""
        if not event_type:
            raise ValueError("event_type must be a non-empty string")
        if not callable(handler):
            raise TypeError("handler must be callable")
        with self._lock:
            if handler not in self._handlers[event_type]:
                self._handlers[event_type].append(handler)

    def off(self, event_type: str, handler: Callable[..., Any] | None = None) -> None:
        """off method"""
        with self._lock:
            if handler is None:
                self._handlers.pop(event_type, None)
            else:
                handlers = self._handlers.get(event_type, [])
                if handler in handlers:
                    handlers.remove(handler)

    def emit(self, event_type: str, data: Any) -> list[Exception]:
        """emit method"""
        with self._lock:
            handlers = list(self._handlers.get(event_type, []))

        errors: list[Exception] = []
        self._last_errors = []

        for handler in handlers:
            try:
                handler(data)
            except Exception as e:
                handler_name = getattr(handler, "__name__", repr(handler))
                error_info = (event_type, handler, e)
                self._last_errors.append(error_info)
                errors.append(e)

                if self.error_mode == ErrorHandlerMode.RAISE:
                    raise

                severity = _classify_error(e)
                severity_label = {
                    ErrorSeverity.USER_ERROR: "handler error",
                    ErrorSeverity.BUSINESS_ERROR: "business error",
                    ErrorSeverity.SYSTEM_ERROR: "system error",
                }[severity]

                log_msg = (
                    f"EventBus {severity_label}: "
                    f"event={event_type}, handler={handler_name}, error={e}\n"
                    f"{traceback.format_exc()}"
                )

                if severity == ErrorSeverity.SYSTEM_ERROR:
                    self.logger.error(log_msg)
                else:
                    self.logger.warning(log_msg)

        return errors

    def get_last_errors(self) -> list[tuple[str, Callable[..., Any], Exception]]:
        """get_last_errors method"""
        return list(self._last_errors)

    def clear_errors(self) -> None:
        """clear_errors method"""
        self._last_errors = []

    def has_handlers(self, event_type: str) -> bool:
        """has_handlers method"""
        with self._lock:
            return len(self._handlers.get(event_type, [])) > 0

    def clear(self) -> None:
        """clear method"""
        with self._lock:
            self._handlers.clear()
            self._last_errors = []
