"""Bounded prepared native cancel values; no authority or source is implied."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Mapping

from bt_api_base.direct_write_protocol import NativeOrderIdentity
from bt_api_base.gateway_direct_protocol import canonical_gateway_payload, validate_gateway_native_identity


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


@dataclass(frozen=True, slots=True)
class PreparedCancelRequest:
    """One immutable native cancellation attempt; reservation is provider-owned."""

    reservation_id: str
    target_identity: NativeOrderIdentity
    symbol: str
    trading_day: str
    session_generation: int
    request_fields: Mapping[str, str | int | bool | None]
    request_keys: tuple[str, ...]
    _seal_digest: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        try:
            if (not _text(self.reservation_id) or not _text(self.symbol)
                    or type(self.target_identity) is not NativeOrderIdentity
                    or type(self.trading_day) is not str or len(self.trading_day) != 8
                    or not self.trading_day.isascii() or not self.trading_day.isdigit()
                    or type(self.session_generation) is not int
                    or not 0 < self.session_generation < 2**63):
                raise ValueError
            datetime.strptime(self.trading_day, "%Y%m%d")
            raw_identity = _identity_data(self.target_identity)
            identity = NativeOrderIdentity.from_dict(raw_identity)
            _identity_data(identity)
            if type(self.request_fields) not in (dict, type(MappingProxyType({}))) or len(self.request_fields) > 128:
                raise ValueError
            copied = {}
            for key, value in self.request_fields.items():
                if (type(key) is not str or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", key, re.ASCII) is None
                        or (type(value) not in (str, int, bool, type(None)))
                        or (type(value) is str and (len(value.encode("utf-8", "strict")) > 256))
                        or (type(value) is int and not -(2**63) <= value < 2**63)):
                    raise ValueError
                copied[key] = value
            if (type(self.request_keys) is not tuple or not 1 <= len(self.request_keys) <= 16
                    or any(not _text(key) for key in self.request_keys)
                    or self.request_keys != tuple(sorted(set(self.request_keys)))):
                raise ValueError
            object.__setattr__(self, "target_identity", identity)
            object.__setattr__(self, "request_fields", MappingProxyType(copied))
            object.__setattr__(self, "_seal_digest", self._calculate_digest())
        except Exception:
            raise PreparedCancelError() from None

    def _mapping(self) -> dict[str, Any]:
        return {"schema_version": 1, "reservation_id": self.reservation_id,
                "target_identity": self.target_identity.to_dict(), "symbol": self.symbol,
                "trading_day": self.trading_day, "session_generation": self.session_generation,
                "request_fields": dict(self.request_fields), "request_keys": list(self.request_keys)}

    def _calculate_digest(self) -> str:
        return hashlib.sha256(canonical_gateway_payload(self._mapping()).encode("ascii")).hexdigest()

    def to_mapping(self) -> dict[str, Any]:
        try:
            if (type(self.request_fields) is not type(MappingProxyType({}))
                    or type(self.request_keys) is not tuple
                    or self._calculate_digest() != self._seal_digest):
                raise ValueError
            return self._mapping()
        except Exception:
            raise PreparedCancelError() from None

    def digest(self) -> str:
        self.to_mapping()
        return self._seal_digest

    @classmethod
    def from_mapping(cls, raw: object) -> PreparedCancelRequest:
        try:
            names = {"schema_version", "reservation_id", "target_identity", "symbol", "trading_day",
                     "session_generation", "request_fields", "request_keys"}
            if type(raw) is not dict or set(raw) != names or type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
                raise ValueError
            identity = raw["target_identity"]
            if (type(identity) is not dict or set(identity) != {"exchange_name", "client_order_id", "fields", "session_generation"}
                    or type(identity["fields"]) is not dict or type(raw["request_fields"]) is not dict
                    or type(raw["request_keys"]) is not list):
                raise ValueError
            return cls(raw["reservation_id"], NativeOrderIdentity.from_dict(identity), raw["symbol"],
                       raw["trading_day"], raw["session_generation"], raw["request_fields"], tuple(raw["request_keys"]))
        except Exception:
            raise PreparedCancelError() from None
