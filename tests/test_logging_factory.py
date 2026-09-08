"""Tests for the logger factory."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from bt_api_base import logging_factory


class _FakeLogger:
    def __init__(self) -> None:
        """__init__ method"""
        self.messages: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def warning(self, *args: object, **kwargs: object) -> None:
        """warning method"""
        self.messages.append(("warning", args, kwargs))

    def warn(self, *args: object, **kwargs: object) -> None:
        """warn method"""
        self.messages.append(("warn", args, kwargs))


def test_resolve_log_file_name_uses_env_dir(monkeypatch) -> None:
    """test_resolve_log_file_name_uses_env_dir function"""
    monkeypatch.setenv("BT_API_LOG_DIR", "~/bt-api-logs")

    resolved = logging_factory._resolve_log_file_name("feed.log")

    assert resolved == str(Path("~/bt-api-logs").expanduser() / "feed.log")


def test_get_logger_sanitizes_custom_file_names(monkeypatch) -> None:
    """test_get_logger_sanitizes_custom_file_names function"""
    created_kwargs: dict[str, object] = {}
    cache_key = ("folder/custom logger", False)
    logging_factory._logger_cache.pop(cache_key, None)

    class _FakeManager:
        def __init__(
            self, *, file_name: str, logger_name: str, print_info: bool
        ) -> None:
            """__init__ method"""
            created_kwargs["file_name"] = file_name
            created_kwargs["logger_name"] = logger_name
            created_kwargs["print_info"] = print_info

        def create_logger(self) -> _FakeLogger:
            """create_logger method"""
            return _FakeLogger()

    monkeypatch.setenv("BT_API_LOG_DIR", "/tmp/bt-api-tests")

    with patch.object(logging_factory, "SpdLogManager", _FakeManager):
        logger = logging_factory.get_logger("folder/custom logger")

    assert isinstance(logger, logging_factory._LoggerProxy)
    # Use Path for cross-platform path comparison
    expected_path = str(Path("/tmp/bt-api-tests") / "folder_custom_logger.log")
    assert created_kwargs["file_name"] == expected_path
    assert created_kwargs["logger_name"] == "folder/custom logger"


def test_logger_proxy_supports_warn_and_warning() -> None:
    """test_logger_proxy_supports_warn_and_warning function"""
    fake_logger = _FakeLogger()
    proxy = logging_factory._LoggerProxy(fake_logger)

    proxy.warning("first")
    proxy.warn("second")

    assert fake_logger.messages == [
        ("warning", ("first",), {}),
        ("warn", ("second",), {}),
    ]


def test_logger_proxy_formats_stdlib_arguments_for_one_string_spdlog_methods() -> None:
    """HTTP error logging must not hide the original exchange response."""
    messages: list[tuple[str, str]] = []

    class _StrictSpdLogger:
        def info(self, message: str) -> None:
            messages.append(("info", message))

        def warn(self, message: str) -> None:
            messages.append(("warn", message))

        def error(self, message: str) -> None:
            messages.append(("error", message))

    proxy = logging_factory._LoggerProxy(_StrictSpdLogger())

    proxy.info("connected to %s", "demo")
    proxy.warning("HTTP %s response from %s", 401, "https://example.invalid")
    proxy.exception("request %s failed", "account")

    assert messages == [
        ("info", "connected to demo"),
        ("warn", "HTTP 401 response from https://example.invalid"),
        ("error", "request account failed"),
    ]


def test_logger_proxy_handles_mapping_and_invalid_format_without_raising() -> None:
    fake_logger = _FakeLogger()
    proxy = logging_factory._LoggerProxy(fake_logger)

    class BrokenString:
        def __str__(self) -> str:
            raise RuntimeError("formatting failed")

    proxy.warning("venue=%(venue)s", {"venue": "okx"})
    proxy.warning("missing %s %s", "one")
    proxy.warning("broken %s", BrokenString())

    assert fake_logger.messages == [
        ("warning", ("venue=okx",), {}),
        ("warning", ("missing %s %s",), {}),
        ("warning", ("broken %s",), {}),
    ]


def test_logger_proxy_does_not_propagate_sink_failures() -> None:
    class _FailingSink:
        @staticmethod
        def warning(_message: str) -> None:
            raise OSError("log volume unavailable")

    proxy = logging_factory._LoggerProxy(_FailingSink())

    proxy.warning("exchange rejected order: %s", -2015)

    assert proxy.sink_failure_count == 1


def test_get_logger_cache_separates_print_info(monkeypatch) -> None:
    """test_get_logger_cache_separates_print_info function"""
    created: list[str] = []
    for cache_key in [("cache-check", False), ("cache-check", True)]:
        logging_factory._logger_cache.pop(cache_key, None)

    class _FakeManager:
        def __init__(
            self, *, file_name: str, logger_name: str, print_info: bool
        ) -> None:
            """__init__ method"""
            created.append(f"{logger_name}:{print_info}")

        def create_logger(self) -> _FakeLogger:
            """create_logger method"""
            return _FakeLogger()

    with patch.object(logging_factory, "SpdLogManager", _FakeManager):
        logger_a = logging_factory.get_logger("cache-check", print_info=False)
        logger_b = logging_factory.get_logger("cache-check", print_info=False)
        logger_c = logging_factory.get_logger("cache-check", print_info=True)

    assert logger_a is logger_b
    assert logger_a is not logger_c
    assert created == ["cache-check:False", "cache-check:True"]
