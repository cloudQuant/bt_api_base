"""Neutral contracts for exact-route provider configuration composition."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

from bt_api_base.market_protocol import MarketInstrumentKey


_CONFIGURATION_ERROR_CODES = frozenset(
    {
        "PROVIDER_CONFIGURATION_ROUTE_INVALID",
        "PROVIDER_CONFIGURATION_CAPABILITY_UNAVAILABLE",
        "PROVIDER_CONFIGURATION_ENTRY_POINT_CONFLICT",
        "PROVIDER_CONFIGURATION_ENTRY_POINT_INVALID",
        "PROVIDER_CONFIGURATION_IMPORT_FAILED",
        "PROVIDER_CONFIGURATION_REGISTRATION_FAILED",
        "PROVIDER_CONFIGURATION_REGISTRATION_SCOPE_INVALID",
        "PROVIDER_CONFIGURATION_CAPABILITY_CONFLICT",
        "PROVIDER_CONFIGURATION_REQUEST_INVALID",
        "PROVIDER_CONFIGURATION_INPUT_UNAVAILABLE",
        "PROVIDER_CONFIGURATION_RESULT_INVALID",
        "PROVIDER_CONFIGURATION_FAILED",
    }
)
_ENVIRONMENT_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}\Z", re.ASCII)


class ProviderConfigurationError(RuntimeError):
    """Finite configuration-contract error without provider values."""

    def __init__(self, code: str) -> None:
        self.code = (
            code
            if type(code) is str and code in _CONFIGURATION_ERROR_CODES
            else "PROVIDER_CONFIGURATION_FAILED"
        )
        super().__init__(self.code)


class ProviderConfigurationHandle:
    """Opaque identity for provider-owned configuration and sealed secrets.

    The handle carries no configuration values and has no public resolver.
    A provider may keep a one-use, private association with it while composing
    its own runtime.  Framework code receives the handle only as part of the
    neutral configuration DTO and must not inspect it.
    """

    __slots__ = ("__weakref__",)

    def __repr__(self) -> str:
        return "<opaque provider configuration handle>"


@dataclass(frozen=True)
class ProviderConfigurationSelection:
    """Explicit neutral route facts for provider-owned profile selection.

    The DTO validates its shape only. The opaque handle is not proof of an
    issuer, profile trust, session readiness, or write permission. The selected
    provider must validate these facts and endpoints against its own profile
    source. With no input handle, it may issue a new provider-owned handle;
    with an input handle, it must preserve that exact identity.
    """

    exchange_name: str
    environment: str
    instrument: MarketInstrumentKey
    profile_ref: str
    provider_profile_handle: ProviderConfigurationHandle | None = field(
        default=None, repr=False
    )

    def __post_init__(self) -> None:
        _require_route(self.exchange_name)
        _require_text(self.environment)
        _require_text(self.profile_ref)
        if (
            type(self.instrument) is not MarketInstrumentKey
            or self.instrument.environment != self.environment
            or (
                self.provider_profile_handle is not None
                and type(self.provider_profile_handle) is not ProviderConfigurationHandle
            )
        ):
            raise ProviderConfigurationError("PROVIDER_CONFIGURATION_REQUEST_INVALID")

    def __repr__(self) -> str:
        return (
            "ProviderConfigurationSelection(exchange_name={!r}, environment={!r}, "
            "instrument={!r}, profile_ref={!r}, profile_handle={})"
        ).format(
            self.exchange_name,
            self.environment,
            self.instrument,
            self.profile_ref,
            "<opaque>" if self.provider_profile_handle is not None else "None",
        )


@dataclass(frozen=True)
class ProviderConfigurationRequest:
    """Bounded input to a provider-owned configuration normalizer."""

    exchange_name: str
    config_path: Path | None = None
    selection: ProviderConfigurationSelection | None = field(default=None, repr=False)
    credential_values: Mapping[str, str] = field(default_factory=dict, repr=False)
    credential_names: Mapping[str, str] = field(default_factory=dict, repr=False)
    credential_env_file: Path | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        _require_route(self.exchange_name)
        # ``Path`` is a factory; on Windows this produces ``WindowsPath`` and
        # on POSIX it produces ``PosixPath``.  Accept those concrete Path
        # implementations while rejecting arbitrary path-like proxies.
        if self.config_path is not None and not isinstance(self.config_path, Path):
            raise ProviderConfigurationError("PROVIDER_CONFIGURATION_REQUEST_INVALID")
        if self.selection is not None and type(self.selection) is not ProviderConfigurationSelection:
            raise ProviderConfigurationError("PROVIDER_CONFIGURATION_REQUEST_INVALID")
        if self.selection is not None and self.selection.exchange_name != self.exchange_name:
            raise ProviderConfigurationError("PROVIDER_CONFIGURATION_REQUEST_INVALID")
        if self.config_path is None and self.selection is None:
            raise ProviderConfigurationError("PROVIDER_CONFIGURATION_INPUT_UNAVAILABLE")
        if self.credential_env_file is not None and not isinstance(
            self.credential_env_file, Path
        ):
            raise ProviderConfigurationError("PROVIDER_CONFIGURATION_REQUEST_INVALID")
        for name in ("credential_values", "credential_names"):
            value = getattr(self, name)
            if not isinstance(value, Mapping) or any(
                type(key) is not str
                or not _ENVIRONMENT_NAME.fullmatch(key)
                or type(item) is not str
                or not item
                or len(item.encode("utf-8", errors="strict")) > 4096
                for key, item in value.items()
            ):
                raise ProviderConfigurationError("PROVIDER_CONFIGURATION_REQUEST_INVALID")
        # Keep the caller's absolute path spelling without resolving links;
        # the provider performs its own bounded regular-file/reparse checks.
        if self.config_path is not None:
            object.__setattr__(self, "config_path", self.config_path.expanduser().absolute())
        if self.credential_env_file is not None:
            object.__setattr__(
                self,
                "credential_env_file",
                self.credential_env_file.expanduser().absolute(),
            )
        object.__setattr__(
            self, "credential_values", MappingProxyType(dict(self.credential_values))
        )
        object.__setattr__(
            self, "credential_names", MappingProxyType(dict(self.credential_names))
        )

    def __repr__(self) -> str:
        return (
            "ProviderConfigurationRequest(exchange_name={!r}, config_path=<redacted>, "
            "selection={}, "
            "credential_values=<redacted>, credential_names=<redacted>, "
            "credential_env_file=<redacted>)"
        ).format(self.exchange_name, "<present>" if self.selection is not None else "None")


@dataclass(frozen=True)
class ProviderConfiguration:
    """Provider-neutral route identity with an opaque provider-owned handle.

    Credential values, environment-variable names, and native provider options
    stay in the provider's private configuration vault.  The handle is only a
    one-use identity for a provider-owned runtime composer.
    """

    exchange_name: str
    environment: str
    profile_ref: str
    instrument: MarketInstrumentKey
    selection_receipt: Mapping[str, Any]
    provider_configuration_handle: ProviderConfigurationHandle = field(
        repr=False, compare=False
    )

    def __post_init__(self) -> None:
        _require_route(self.exchange_name)
        _require_text(self.environment)
        _require_text(self.profile_ref)
        if type(self.instrument) is not MarketInstrumentKey:
            raise ProviderConfigurationError("PROVIDER_CONFIGURATION_RESULT_INVALID")
        if self.instrument.environment != self.environment:
            raise ProviderConfigurationError("PROVIDER_CONFIGURATION_RESULT_INVALID")
        if type(self.provider_configuration_handle) is not ProviderConfigurationHandle:
            raise ProviderConfigurationError("PROVIDER_CONFIGURATION_RESULT_INVALID")
        if not isinstance(self.selection_receipt, Mapping):
            raise ProviderConfigurationError("PROVIDER_CONFIGURATION_RESULT_INVALID")
        object.__setattr__(self, "selection_receipt", _freeze_public_mapping(self.selection_receipt))

    def to_public_dict(self) -> dict[str, Any]:
        """Return route/profile facts without secrets or provider options."""

        return {
            "exchange_name": self.exchange_name,
            "environment": self.environment,
            "profile_ref": self.profile_ref,
            "instrument": self.instrument.to_dict(),
            "front_selection": _plain(self.selection_receipt),
        }

    def __repr__(self) -> str:
        return (
            "ProviderConfiguration(exchange_name={!r}, environment={!r}, "
            "profile_ref={!r}, instrument={!r}, provider_configuration=<opaque>)"
        ).format(self.exchange_name, self.environment, self.profile_ref, self.instrument)


@runtime_checkable
class ProviderConfigurationFactory(Protocol):
    """Provider-owned exact-route configuration normalizer."""

    def __call__(
        self, request: ProviderConfigurationRequest
    ) -> ProviderConfiguration: ...


@runtime_checkable
class ProviderConfigurationRegistryPort(Protocol):
    """Registration port implemented by the parent SDK configuration router."""

    def register(
        self,
        exchange_name: str,
        factory: ProviderConfigurationFactory,
    ) -> None: ...


def _require_route(value: object) -> None:
    _require_text(value)


def _require_text(value: object) -> None:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or not value.isprintable()
        or len(value.encode("utf-8", errors="strict")) > 256
    ):
        raise ProviderConfigurationError("PROVIDER_CONFIGURATION_ROUTE_INVALID")


def _freeze_public_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    frozen: dict[str, Any] = {}
    for key, item in value.items():
        if type(key) is not str or not key or key != key.strip():
            raise ProviderConfigurationError("PROVIDER_CONFIGURATION_RESULT_INVALID")
        frozen[key] = _freeze_public_value(item)
    return MappingProxyType(frozen)


def _freeze_public_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _freeze_public_mapping(value)
    if type(value) in (tuple, list):
        return tuple(_freeze_public_value(item) for item in value)
    if type(value) in (str, int, float, bool) or value is None:
        return value
    raise ProviderConfigurationError("PROVIDER_CONFIGURATION_RESULT_INVALID")


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


__all__ = [
    "ProviderConfiguration",
    "ProviderConfigurationError",
    "ProviderConfigurationHandle",
    "ProviderConfigurationSelection",
    "ProviderConfigurationRequest",
    "ProviderConfigurationFactory",
    "ProviderConfigurationRegistryPort",
]
