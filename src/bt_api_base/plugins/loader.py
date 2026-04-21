from __future__ import annotations

from dataclasses import replace
import logging
from importlib import metadata as importlib_metadata
from typing import Any

from packaging.specifiers import SpecifierSet
from packaging.version import Version

from bt_api_base._version import __version__
from bt_api_base.plugins.errors import PluginRegistrationError, PluginVersionMismatchError
from bt_api_base.plugins.protocol import PluginInfo

LOG_PREFIX = "[bt_api_base.plugins]"
logger = logging.getLogger(__name__)


class _IsolatedRuntimeRegistrar:
    def __init__(self) -> None:
        self._adapters: dict[str, type[Any]] = {}

    def register_adapter(self, exchange_type: str, adapter_cls: type[Any]) -> None:
        normalized = str(exchange_type).strip().upper()
        existing = self._adapters.get(normalized)
        if existing is not None and existing is not adapter_cls:
            raise PluginRegistrationError(
                f"duplicate adapter registration inside plugin: {normalized}"
            )
        self._adapters[normalized] = adapter_cls

    def get_adapter(self, exchange_type: str) -> type[Any] | None:
        normalized = str(exchange_type).strip().upper()
        return self._adapters.get(normalized)

    def list_adapters(self) -> list[str]:
        return list(self._adapters.keys())

    def items(self) -> list[tuple[str, type[Any]]]:
        return list(self._adapters.items())


class PluginLoader:
    def __init__(self, registry: Any, runtime_registrar: Any) -> None:
        self.registry = registry
        self.runtime_registrar = runtime_registrar
        self.loaded: dict[str, PluginInfo] = {}
        self.failed: dict[str, Exception] = {}

    @staticmethod
    def _failure_key(entry_name: str, info: Any) -> str:
        if isinstance(info, PluginInfo):
            return info.name
        return entry_name

    def load_all(self, group: str = "bt_api.plugins") -> None:
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
        discovered: Any = importlib_metadata.entry_points()
        if hasattr(discovered, "select"):
            return list(discovered.select(group=group))
        if isinstance(discovered, dict):
            return list(discovered.get(group, ()))
        return [ep for ep in discovered if getattr(ep, "group", None) == group]

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
        isolated_runtime = _IsolatedRuntimeRegistrar()
        info: PluginInfo | None = None
        try:
            info = register_plugin(isolated_registry, isolated_runtime)
            if not isinstance(info, PluginInfo):
                raise PluginRegistrationError(
                    f"plugin {entry_name} returned invalid plugin metadata: {type(info).__name__}"
                )
            if not info.plugin_module:
                info = replace(info, plugin_module=entry_module)
            self._check_core_compatibility(info)
            self._check_duplicate_registration(info, isolated_runtime)
            self._commit_registry(isolated_registry)
            self._commit_runtime(isolated_runtime)
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

    def _check_duplicate_registration(
        self,
        info: PluginInfo,
        isolated_runtime: _IsolatedRuntimeRegistrar,
    ) -> None:
        duplicate_exchanges = [
            exchange_name
            for exchange_name in info.supported_exchanges
            if self.registry.has_exchange(exchange_name)
        ]
        duplicate_adapters = [
            exchange_type
            for exchange_type in isolated_runtime.list_adapters()
            if self.runtime_registrar.get_adapter(exchange_type) is not None
        ]
        if duplicate_exchanges or duplicate_adapters:
            detail_parts: list[str] = []
            if duplicate_exchanges:
                detail_parts.append(
                    f"duplicate exchanges: {', '.join(sorted(duplicate_exchanges))}"
                )
            if duplicate_adapters:
                detail_parts.append(f"duplicate adapters: {', '.join(sorted(duplicate_adapters))}")
            detail = "; ".join(detail_parts)
            logger.warning(
                "%s plugin %s skipped due to duplicate registration: %s",
                LOG_PREFIX,
                info.name,
                detail,
            )
            raise PluginRegistrationError(f"duplicate registration skipped: {detail}")

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

    def _commit_runtime(self, isolated_runtime: _IsolatedRuntimeRegistrar) -> None:
        for exchange_type, adapter_cls in isolated_runtime.items():
            self.runtime_registrar.register_adapter(exchange_type, adapter_cls)

    @staticmethod
    def _entry_point_module(entry_point: Any) -> str:
        module = getattr(entry_point, "module", "")
        if isinstance(module, str) and module:
            return module
        value = getattr(entry_point, "value", "")
        if isinstance(value, str) and ":" in value:
            return value.split(":", 1)[0]
        return ""
