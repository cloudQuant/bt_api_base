"""Module documentation"""

from __future__ import annotations

import logging
from dataclasses import replace
from importlib import metadata as importlib_metadata
from typing import Any

from packaging.specifiers import SpecifierSet
from packaging.version import Version

from bt_api_base._version import __version__
from bt_api_base.plugins.errors import (
    PluginOptionalDependencyError,
    PluginRegistrationError,
    PluginVersionMismatchError,
)
from bt_api_base.plugins.protocol import PluginInfo

LOG_PREFIX = "[bt_api_base.plugins]"
logger = logging.getLogger(__name__)


class PluginLoader:
    """Class PluginLoader"""

    def __init__(self, registry: Any) -> None:
        """__init__ method"""
        self.registry = registry
        self.loaded: dict[str, PluginInfo] = {}
        self.failed: dict[str, Exception] = {}
        self.skipped: dict[str, Exception] = {}

    @staticmethod
    def _failure_key(entry_name: str, info: Any) -> str:
        if isinstance(info, PluginInfo):
            return info.name
        return entry_name

    def load_all(self, group: str = "bt_api.plugins") -> None:
        """load_all method"""
        entry_points = list(self._discover_entry_points(group))
        if not entry_points:
            logger.info("%s discovered 0 entry points in group '%s'", LOG_PREFIX, group)
            return

        logger.info(
            "%s discovered %d entry points in group '%s'",
            LOG_PREFIX,
            len(entry_points),
            group,
        )
        for entry_point in entry_points:
            self._load_one(entry_point)

    def _discover_entry_points(self, group: str) -> list[Any]:
        try:
            discovered: Any = importlib_metadata.entry_points()
        except Exception as exc:
            # A malformed, unrelated installed distribution can make the stdlib
            # aggregate entry-point index fail before it reaches this group.  Scan
            # distributions independently so valid exchange plugins remain usable.
            logger.warning(
                "%s aggregate entry-point discovery failed (%s); scanning distributions",
                LOG_PREFIX,
                type(exc).__name__,
            )
            return self._discover_entry_points_from_distributions(group)
        if hasattr(discovered, "select"):
            return list(discovered.select(group=group))
        if isinstance(discovered, dict):
            return list(discovered.get(group, ()))
        return [ep for ep in discovered if getattr(ep, "group", None) == group]

    @staticmethod
    def _discover_entry_points_from_distributions(group: str) -> list[Any]:
        entry_points: list[Any] = []
        seen: set[tuple[str, str]] = set()
        for distribution in importlib_metadata.distributions():
            try:
                for entry_point in distribution.entry_points:
                    if getattr(entry_point, "group", None) != group:
                        continue
                    value = str(getattr(entry_point, "value", ""))
                    identity = (value,) if value else (str(getattr(entry_point, "name", "")),)
                    if identity in seen:
                        continue
                    seen.add(identity)
                    entry_points.append(entry_point)
            except Exception as exc:
                logger.warning(
                    "%s skipped malformed distribution entry points (%s)",
                    LOG_PREFIX,
                    type(exc).__name__,
                )
        return entry_points

    def _load_one(self, entry_point: Any) -> None:
        entry_name = str(getattr(entry_point, "name", "<unknown>"))
        entry_module = self._entry_point_module(entry_point)
        if entry_name in self.failed or entry_name in self.loaded:
            return
        logger.info(
            "%s loading plugin: %s (module=%s)",
            LOG_PREFIX,
            entry_name,
            entry_module,
        )
        try:
            register_plugin = entry_point.load()
        except PluginOptionalDependencyError as exc:
            logger.info("%s plugin %s skipped: %s", LOG_PREFIX, entry_name, exc)
            self.skipped[entry_name] = exc
            return
        except ImportError as exc:
            logger.warning(
                "%s plugin %s import failed: %s: %s",
                LOG_PREFIX,
                entry_name,
                type(exc).__name__,
                exc,
            )
            self.failed[entry_name] = exc
            return
        except Exception as exc:
            logger.exception("%s plugin %s load failed", LOG_PREFIX, entry_name)
            self.failed[entry_name] = exc
            return

        isolated_registry = self._create_isolated_registry()
        info: PluginInfo | None = None
        try:
            info = register_plugin(isolated_registry)
            if not isinstance(info, PluginInfo):
                raise PluginRegistrationError(
                    f"plugin {entry_name} returned invalid plugin metadata: {type(info).__name__}"
                )
            if not info.plugin_module:
                info = replace(info, plugin_module=entry_module)
            self._check_core_compatibility(info)
            self._check_registry_contract(info, isolated_registry)
            self._check_duplicate_registration(info)
            self._commit_registry(isolated_registry)
        except PluginOptionalDependencyError as exc:
            failure_key = self._failure_key(entry_name, info)
            logger.info("%s plugin %s skipped: %s", LOG_PREFIX, entry_name, exc)
            self.skipped[failure_key] = exc
            return
        except PluginRegistrationError as exc:
            failure_key = self._failure_key(entry_name, info)
            log_fn = (
                logger.warning if "duplicate registration skipped:" in str(exc) else logger.error
            )
            log_fn("%s plugin %s failed: %s", LOG_PREFIX, entry_name, exc)
            self.failed[failure_key] = exc
            return
        except PluginVersionMismatchError as exc:
            failure_key = self._failure_key(entry_name, info)
            logger.error("%s plugin %s failed: %s", LOG_PREFIX, entry_name, exc)
            self.failed[failure_key] = exc
            return
        except Exception as exc:
            failure_key = self._failure_key(entry_name, info)
            logger.exception("%s plugin %s failed unexpectedly", LOG_PREFIX, entry_name)
            self.failed[failure_key] = exc
            return

        if info.name in self.loaded:
            return
        self.loaded[info.name] = info
        logger.info(
            "%s registered plugin %s v%s (exchanges=%s)",
            LOG_PREFIX,
            info.name,
            info.version,
            ", ".join(info.supported_exchanges),
        )

    def _create_isolated_registry(self) -> Any:
        create_isolated = getattr(self.registry, "create_isolated", None)
        if create_isolated is None:
            raise PluginRegistrationError("registry does not support isolated plugin loading")
        return create_isolated()

    def _check_core_compatibility(self, info: PluginInfo) -> None:
        specifier = SpecifierSet(info.core_requires)
        current = Version(__version__)
        if current not in specifier:
            raise PluginVersionMismatchError(
                f"plugin {info.name} requires core {info.core_requires}, current={__version__}"
            )

    def _check_duplicate_registration(self, info: PluginInfo) -> None:
        duplicate_exchanges = [
            exchange_name
            for exchange_name in info.supported_exchanges
            if self.registry.has_exchange(exchange_name)
        ]
        if duplicate_exchanges:
            detail = f"duplicate exchanges: {', '.join(sorted(duplicate_exchanges))}"
            logger.warning(
                "%s plugin %s skipped due to duplicate registration: %s",
                LOG_PREFIX,
                info.name,
                detail,
            )
            raise PluginRegistrationError(f"duplicate registration skipped: {detail}")

    @staticmethod
    def _check_registry_contract(info: PluginInfo, isolated_registry: Any) -> None:
        declared = info.supported_exchanges
        if (
            type(declared) is not tuple
            or any(type(name) is not str or not name.strip() for name in declared)
            or len(set(declared)) != len(declared)
        ):
            raise PluginRegistrationError(
                f"plugin {info.name} has invalid supported-exchange metadata"
            )
        registered = tuple(isolated_registry.list_exchanges())
        registered_set = set(registered)
        declared_set = set(declared)
        if not declared_set:
            raise PluginRegistrationError(
                f"plugin {info.name} is unavailable: it declares no supported exchanges"
            )
        if registered_set != declared_set:
            missing = sorted(declared_set - registered_set)
            undeclared = sorted(registered_set - declared_set)
            detail_parts = []
            if missing:
                detail_parts.append(f"declared exchanges without feeds: {', '.join(missing)}")
            if undeclared:
                detail_parts.append(f"unlisted registered exchanges: {', '.join(undeclared)}")
            detail = "; ".join(detail_parts) or "duplicate registered exchanges"
            raise PluginRegistrationError(
                f"plugin {info.name} registry does not match its supported-exchange metadata: "
                f"{detail}"
            )

    def _commit_registry(self, isolated_registry: Any) -> None:
        for exchange_name in isolated_registry.list_exchanges():
            feed_class = isolated_registry.get_feed_class(exchange_name)
            if feed_class is not None:
                self.registry.register_feed(exchange_name, feed_class)

            exchange_data_class = isolated_registry.get_exchange_data_class(exchange_name)
            if exchange_data_class is not None:
                self.registry.register_exchange_data(exchange_name, exchange_data_class)

            balance_handler = isolated_registry.get_balance_handler(exchange_name)
            if balance_handler is not None:
                self.registry.register_balance_handler(exchange_name, balance_handler)

            for stream_type, stream_class in isolated_registry.get_stream_classes(
                exchange_name
            ).items():
                self.registry.register_stream(exchange_name, stream_type, stream_class)

    @staticmethod
    def _entry_point_module(entry_point: Any) -> str:
        module = getattr(entry_point, "module", "")
        if isinstance(module, str) and module:
            return module
        value = getattr(entry_point, "value", "")
        if isinstance(value, str) and ":" in value:
            return value.split(":", 1)[0]
        return ""
