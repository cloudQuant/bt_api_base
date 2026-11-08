"""Bounded prepared native cancel values; no authority or source is implied."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any

from bt_api_base.direct_write_protocol import NativeOrderIdentity
from bt_api_base.gateway_direct_protocol import (
    canonical_gateway_payload,
    validate_gateway_native_identity,
)


class PreparedCancelError(ValueError):
    """Finite, value-free prepared-cancel contract error."""

    def __init__(self) -> None:
        super().__init__("invalid_prepared_cancel")


def _text(value: object, limit: int = 256) -> bool:
    if type(value) is not str or not value or value != value.strip() or not value.isprintable():
        return False
    try:
        return len(value.encode("utf-8", errors="strict")) <= limit
    except UnicodeError:
        return False


def _identity_data(identity: NativeOrderIdentity) -> dict[str, Any]:
    validate_gateway_native_identity(identity)
    return identity.to_dict()


def _freeze_fields(
    value: object, *, nonempty: bool = False
) -> Mapping[str, str | int | bool | None]:
    if (
        type(value) not in (dict, type(MappingProxyType({})))
        or len(value) > 128
        or (nonempty and not value)
    ):
        raise ValueError
    copied = {}
    for key, item in value.items():
        if (
            type(key) is not str
            or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", key, re.ASCII) is None
            or type(item) not in (str, int, bool, type(None))
            or (type(item) is str and len(item.encode("utf-8", "strict")) > 256)
            or (type(item) is int and not -(2**63) <= item < 2**63)
        ):
            raise ValueError
        copied[key] = item
    return MappingProxyType(copied)


@dataclass(frozen=True, slots=True, eq=False)
class PreparedCancelRequest:
    """Immutable provider preparation; source labels do not establish authority."""

    reservation_id: str
    target_identity: NativeOrderIdentity
    symbol: str
    trading_day: str
    session_generation: int
    request_fields: Mapping[str, str | int | bool | None]
    request_keys: tuple[str, ...]
    source_binding: Mapping[str, str | int | bool | None] | None = None
    _seal_digest: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        try:
            if (
                not _text(self.reservation_id)
                or not _text(self.symbol)
                or type(self.target_identity) is not NativeOrderIdentity
                or type(self.trading_day) is not str
                or len(self.trading_day) != 8
                or not self.trading_day.isascii()
                or not self.trading_day.isdigit()
                or type(self.session_generation) is not int
                or not 0 < self.session_generation < 2**63
            ):
                raise ValueError
            datetime.strptime(self.trading_day, "%Y%m%d")
            raw_identity = _identity_data(self.target_identity)
            identity = NativeOrderIdentity.from_dict(raw_identity)
            _identity_data(identity)
            copied = _freeze_fields(self.request_fields)
            source = (
                None
                if self.source_binding is None
                else _freeze_fields(self.source_binding, nonempty=True)
            )
            if (
                type(self.request_keys) is not tuple
                or not 1 <= len(self.request_keys) <= 16
                or any(not _text(key) for key in self.request_keys)
                or self.request_keys != tuple(sorted(set(self.request_keys)))
            ):
                raise ValueError
            object.__setattr__(self, "target_identity", identity)
            object.__setattr__(self, "request_fields", copied)
            object.__setattr__(self, "source_binding", source)
            object.__setattr__(self, "_seal_digest", self._calculate_digest())
        except Exception:
            raise PreparedCancelError() from None

    def _mapping(self) -> dict[str, Any]:
        result = {
            "schema_version": 1 if self.source_binding is None else 2,
            "reservation_id": self.reservation_id,
            "target_identity": self.target_identity.to_dict(),
            "symbol": self.symbol,
            "trading_day": self.trading_day,
            "session_generation": self.session_generation,
            "request_fields": dict(self.request_fields),
            "request_keys": list(self.request_keys),
        }
        if self.source_binding is not None:
            result["source_binding"] = dict(self.source_binding)
        return result

    def _calculate_digest(self) -> str:
        return hashlib.sha256(
            canonical_gateway_payload(self._mapping()).encode("ascii")
        ).hexdigest()

    def to_mapping(self) -> dict[str, Any]:
        try:
            if (
                type(self.request_fields) is not type(MappingProxyType({}))
                or type(self.request_keys) is not tuple
                or (
                    self.source_binding is not None
                    and type(self.source_binding) is not type(MappingProxyType({}))
                )
                or self._calculate_digest() != self._seal_digest
            ):
                raise ValueError
            return self._mapping()
        except Exception:
            raise PreparedCancelError() from None

    def digest(self) -> str:
        self.to_mapping()
        return self._seal_digest

    def __eq__(self, other: object) -> bool:
        if type(other) is not PreparedCancelRequest:
            return NotImplemented
        return canonical_gateway_payload(self.to_mapping()) == canonical_gateway_payload(
            other.to_mapping()
        )

    __hash__ = None

    @classmethod
    def from_mapping(cls, raw: object) -> PreparedCancelRequest:
        try:
            names = {
                "schema_version",
                "reservation_id",
                "target_identity",
                "symbol",
                "trading_day",
                "session_generation",
                "request_fields",
                "request_keys",
            }
            if type(raw) is not dict or type(raw.get("schema_version")) is not int:
                raise ValueError
            version = raw["schema_version"]
            if (
                version not in (1, 2)
                or set(raw) != (names if version == 1 else names | {"source_binding"})
                or (version == 2 and type(raw["source_binding"]) is not dict)
            ):
                raise ValueError
            identity = raw["target_identity"]
            if (
                type(identity) is not dict
                or set(identity)
                != {"exchange_name", "client_order_id", "fields", "session_generation"}
                or type(identity["fields"]) is not dict
                or type(raw["request_fields"]) is not dict
                or type(raw["request_keys"]) is not list
            ):
                raise ValueError
            return cls(
                raw["reservation_id"],
                NativeOrderIdentity.from_dict(identity),
                raw["symbol"],
                raw["trading_day"],
                raw["session_generation"],
                raw["request_fields"],
                tuple(raw["request_keys"]),
                source_binding=None if version == 1 else raw["source_binding"],
            )
        except Exception:
            raise PreparedCancelError() from None
