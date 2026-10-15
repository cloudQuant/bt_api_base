"""—  spdlog  logging"""

from __future__ import annotations

import logging
from importlib import import_module
from pathlib import Path
from typing import Any, Optional

__all__ = ["SpdLogManager", "_HAS_SPDLOG"]

_HAS_SPDLOG = False
_spdlog_module: Optional[Any] = None


def _load_spdlog(*, require_stdout: bool = False) -> Any:
    """Import and validate the optional native logger on explicit request only."""
    global _HAS_SPDLOG, _spdlog_module
    module = _spdlog_module
    if module is None:
        try:
            module = import_module("spdlog")
        except ImportError as exc:
            raise ImportError(
                "The spdlog logging backend is optional; install "
                "bt_api_base[spdlog] or bt_api_py[spdlog] to enable it."
            ) from exc

    required = ["daily_file_sink_st", "SinkLogger"]
    if require_stdout:
        required.append("stdout_sink_st")
    missing = [name for name in required if not hasattr(module, name)]
    if missing:
        raise ImportError(
            "The installed spdlog package does not provide required logger "
            f"API member(s): {', '.join(missing)}."
        )

    _spdlog_module = module
    _HAS_SPDLOG = True
    return module


def _get_project_logs_dir() -> str:
    """logs/ 。
    = bt_api_base 。
    """
    try:
        import bt_api_base

        pkg_path = Path(bt_api_base.__file__).resolve().parent
        return str(pkg_path.parent / "logs")
    except Exception as e:
        # Fallback when package context unavailable (e.g. during early import)
        logging.getLogger(__name__).debug("Using cwd for logs dir: %s", e)
        return str(Path.cwd() / "logs")


class SpdLogManager:
    """Class SpdLogManager"""

    _logger_cache: dict[tuple[str, str, int, int, bool, str], object] = {}
    _project_logs_dir = _get_project_logs_dir()

    def __init__(
        self,
        file_name: str = "log_strategy_info.log",
        logger_name: str = "hello",
        rotation_hour: int = 0,
        rotation_minute: int = 0,
        print_info: bool = False,
        backend: str = "stdlib",
    ) -> None:
        """Create a logger configuration.

        The default backend is Python's standard logger and does not probe or
        import the optional native ``spdlog`` extension. Select ``backend="spdlog"``
        explicitly to use that extension.
        """
        if backend not in {"stdlib", "spdlog"}:
            raise ValueError("backend must be 'stdlib' or 'spdlog'")
        self.file_name = self._normalize_file_name(file_name)
        self.logger_name = logger_name
        self.rotation_hour = rotation_hour
        self.rotation_minute = rotation_minute
        self.print_info = print_info
        self.backend = backend

    @classmethod
    def _normalize_file_name(cls, file_name: str) -> str:
        """Normalize relative log file names into the project logs directory."""
        path = Path(file_name)
        if path.is_absolute():
            return file_name

        name = file_name
        if file_name.startswith("./logs/"):
            name = file_name[len("./logs/") :]
        elif file_name.startswith("./"):
            name = file_name[len("./") :]

        return str(Path(cls._project_logs_dir) / name)

    def create_logger(self) -> Any:
        #
        """create_logger method"""
        key = (
            self.file_name,
            self.logger_name,
            self.rotation_hour,
            self.rotation_minute,
            self.print_info,
            self.backend,
        )
        # ，logger
        if key in SpdLogManager._logger_cache:
            return SpdLogManager._logger_cache[key]

        #
        log_dir = Path(self.file_name).parent
        if str(log_dir):
            log_dir.mkdir(parents=True, exist_ok=True)

        if self.backend == "stdlib":
            # Keep each sink/console configuration isolated. A named global
            # logger would make the first print_info setting silently win for
            # later configurations with the same public logger name.
            logger = logging.Logger(self.logger_name, level=logging.DEBUG)
            formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
            fh = logging.FileHandler(self.file_name, encoding="utf-8")
            fh.setFormatter(formatter)
            logger.addHandler(fh)
            if self.print_info:
                stream_handler = logging.StreamHandler()
                stream_handler.setFormatter(formatter)
                logger.addHandler(stream_handler)
            logger.propagate = False
            SpdLogManager._logger_cache[key] = logger
            return logger

        spdlog = _load_spdlog(require_stdout=self.print_info)
        # sinks
        if self.print_info:
            sinks = [
                spdlog.stdout_sink_st(),
                spdlog.daily_file_sink_st(self.file_name, self.rotation_hour, self.rotation_minute),
            ]
        else:
            sinks = [
                spdlog.daily_file_sink_st(self.file_name, self.rotation_hour, self.rotation_minute)
            ]

        # logger
        logger = spdlog.SinkLogger(self.logger_name, sinks)
        SpdLogManager._logger_cache[key] = logger
        return logger
