"""Tests for the logger factory."""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from bt_api_base import logging_factory
from bt_api_base.functions import log_message


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
    cache_key = ("folder/custom logger", False, "stdlib")
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
    for cache_key in [("cache-check", False, "stdlib"), ("cache-check", True, "stdlib")]:
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


def test_stdlib_logger_instances_keep_console_setting_isolated(
    monkeypatch, tmp_path, capsys
) -> None:
    monkeypatch.setenv("BT_API_LOG_DIR", str(tmp_path))
    module = f"print-setting-{tmp_path.name}"
    log_file = tmp_path / f"{module}.log"
    factory_keys = [(module, False, "stdlib"), (module, True, "stdlib")]
    manager_keys = [
        (str(log_file), module, 0, 0, print_info, "stdlib")
        for print_info in (False, True)
    ]
    for key in factory_keys:
        logging_factory._logger_cache.pop(key, None)
    for key in manager_keys:
        log_message.SpdLogManager._logger_cache.pop(key, None)

    loggers: list[logging.Logger] = []
    try:
        quiet = logging_factory.get_logger(module, print_info=False)._logger
        loud = logging_factory.get_logger(module, print_info=True)._logger
        assert isinstance(quiet, logging.Logger)
        assert isinstance(loud, logging.Logger)
        assert quiet is not loud
        loggers.extend((quiet, loud))

        quiet.info("quiet message")
        loud.info("visible message")
        for logger in loggers:
            for handler in logger.handlers:
                handler.flush()

        assert "quiet message" in log_file.read_text(encoding="utf-8")
        assert "visible message" in log_file.read_text(encoding="utf-8")
        console = capsys.readouterr().err
        assert "quiet message" not in console
        assert "visible message" in console
    finally:
        for logger in loggers:
            for handler in logger.handlers:
                logger.removeHandler(handler)
                handler.close()
        for key in factory_keys:
            logging_factory._logger_cache.pop(key, None)
        for key in manager_keys:
            log_message.SpdLogManager._logger_cache.pop(key, None)


def test_default_stdlib_backend_keeps_file_and_console_logging(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(log_message, "_HAS_SPDLOG", False)
    log_file = tmp_path / "fallback.log"
    logger_name = "fallback-" + tmp_path.name
    cache_key = (str(log_file), logger_name, 0, 0, True, "stdlib")
    logger = None

    try:
        logger = log_message.SpdLogManager(
            file_name=str(log_file),
            logger_name=logger_name,
            print_info=True,
        ).create_logger()

        assert isinstance(logger, logging.Logger)
        logger.info("fallback message")
        for handler in logger.handlers:
            handler.flush()

        assert "fallback message" in log_file.read_text(encoding="utf-8")
        assert "fallback message" in capsys.readouterr().err
    finally:
        if logger is not None:
            for handler in logger.handlers:
                logger.removeHandler(handler)
                handler.close()
        log_message.SpdLogManager._logger_cache.pop(cache_key, None)


def test_spdlog_backend_is_loaded_only_when_explicitly_selected(
    monkeypatch, tmp_path
) -> None:
    imports: list[str] = []
    messages: list[str] = []

    class _NativeLogger:
        def __init__(self, logger_name: str, sinks: list[object]) -> None:
            self.logger_name = logger_name
            self.sinks = sinks

        def info(self, message: str) -> None:
            messages.append(message)

    native_module = SimpleNamespace(
        daily_file_sink_st=lambda file_name, hour, minute: (file_name, hour, minute),
        stdout_sink_st=lambda: "stdout",
        SinkLogger=_NativeLogger,
    )

    def import_native(name: str) -> object:
        imports.append(name)
        assert name == "spdlog"
        return native_module

    monkeypatch.setattr(log_message, "_spdlog_module", None)
    monkeypatch.setattr(log_message, "_HAS_SPDLOG", False)
    monkeypatch.setattr(log_message, "import_module", import_native)
    monkeypatch.setenv("BT_API_LOG_DIR", str(tmp_path))

    logger_name = f"backend-selection-{tmp_path.name}"
    stdlib_key = (logger_name, False, "stdlib")
    spdlog_key = (logger_name, False, "spdlog")
    manager_keys = [
        (str(tmp_path / f"{logger_name}.log"), logger_name, 0, 0, False, backend)
        for backend in ("stdlib", "spdlog")
    ]
    logging_factory._logger_cache.pop(stdlib_key, None)
    logging_factory._logger_cache.pop(spdlog_key, None)
    for key in manager_keys:
        log_message.SpdLogManager._logger_cache.pop(key, None)
    stdlib_proxy = None
    try:
        stdlib_proxy = logging_factory.get_logger(logger_name)
        assert isinstance(stdlib_proxy._logger, logging.Logger)
        assert imports == []

        spdlog_proxy = logging_factory.get_logger(logger_name, backend="spdlog")
    finally:
        if stdlib_proxy is not None:
            for handler in stdlib_proxy._logger.handlers:
                stdlib_proxy._logger.removeHandler(handler)
                handler.close()
        logging_factory._logger_cache.pop(stdlib_key, None)
        logging_factory._logger_cache.pop(spdlog_key, None)
        for key in manager_keys:
            log_message.SpdLogManager._logger_cache.pop(key, None)

    spdlog_proxy.info("explicit backend %s", "loaded")

    assert isinstance(spdlog_proxy, logging_factory._LoggerProxy)
    assert isinstance(spdlog_proxy._logger, _NativeLogger)
    assert spdlog_proxy._logger.logger_name == logger_name
    assert imports == ["spdlog"]
    assert messages == ["explicit backend loaded"]
    assert stdlib_proxy is not spdlog_proxy


def test_spdlog_console_api_is_checked_after_non_console_load(monkeypatch, tmp_path) -> None:
    imports: list[str] = []

    class _NativeLogger:
        def __init__(self, _logger_name: str, _sinks: list[object]) -> None:
            pass

    native_module = SimpleNamespace(
        daily_file_sink_st=lambda *_args: "file-sink",
        SinkLogger=_NativeLogger,
    )

    def import_native(name: str) -> object:
        imports.append(name)
        return native_module

    monkeypatch.setattr(log_message, "_spdlog_module", None)
    monkeypatch.setattr(log_message, "_HAS_SPDLOG", False)
    monkeypatch.setattr(log_message, "import_module", import_native)
    keys = [
        (str(tmp_path / "conditional-api.log"), "conditional-api", 0, 0, print_info, "spdlog")
        for print_info in (False, True)
    ]
    for key in keys:
        log_message.SpdLogManager._logger_cache.pop(key, None)

    try:
        file_only = log_message.SpdLogManager(
            file_name=str(tmp_path / "conditional-api.log"),
            logger_name="conditional-api",
            backend="spdlog",
        ).create_logger()
        assert isinstance(file_only, _NativeLogger)

        console = log_message.SpdLogManager(
            file_name=str(tmp_path / "conditional-api.log"),
            logger_name="conditional-api",
            print_info=True,
            backend="spdlog",
        )
        with pytest.raises(ImportError, match="stdout_sink_st"):
            console.create_logger()
        assert imports == ["spdlog"]
    finally:
        for key in keys:
            log_message.SpdLogManager._logger_cache.pop(key, None)
