"""Neutral Gateway execution-return facts; values grant no authority or provenance."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar

from bt_api_base.direct_write_protocol import (
    DirectExecutionEventKind,
    DirectOrderStatus,
    NativeOrderIdentity,
)
from bt_api_base.gateway_direct_protocol import (
    canonical_gateway_payload,
    validate_gateway_native_identity,
)
from bt_api_base.market_protocol import MarketInstrumentKey


class GatewayExecutionProtocolError(ValueError):
    """Finite value-free validation failure for a return fact."""

    def __init__(self, code: str) -> None:
        self.code = (
            code
            if type(code) is str and code in {"INVALID_RETURN_FACT", "INVALID_RETURN_MAPPING"}
            else "INVALID_RETURN_FACT"
        )
        super().__init__(self.code)


def _fail() -> None:
    raise GatewayExecutionProtocolError("INVALID_RETURN_FACT")


def _text(value: object) -> bool:
    if (
        type(value) is not str
        or not value
        or len(value) > 256
        or value != value.strip()
        or not value.isprintable()
    ):
        return False
    try:
        return len(value.encode("utf-8", errors="strict")) <= 256
    except UnicodeError:
        return False


_DECIMAL = re.compile(r"(?:0|[1-9][0-9]{0,35})(?:\.[0-9]{0,17}[1-9])?\Z", re.ASCII)
_ERROR_CODE = re.compile(r"[A-Za-z0-9_.:-]{1,256}\Z", re.ASCII)


def _decimal(value: object, *, positive: bool) -> bool:
    return value is None or (
        type(value) is str
        and len(value) <= 128
        and _DECIMAL.fullmatch(value) is not None
        and (not positive or value != "0")
    )


def _date(value: object) -> bool:
    if type(value) is not str or len(value) != 8 or not value.isascii() or not value.isdigit():
        return False
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return False
    return True


def _key_tuple(value: object, *, min_size: int, max_size: int, sorted_unique: bool) -> bool:
    return (
        type(value) is tuple
        and min_size <= len(value) <= max_size
        and all(_text(item) for item in value)
        and (not sorted_unique or value == tuple(sorted(set(value))))
    )


def _digest(value: dict[str, Any]) -> str:
    try:
        canonical = canonical_gateway_payload(value)
    except Exception:
        _fail()
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


@dataclass(frozen=True, slots=True)
class GatewayReturnFact:
    """Immutable normalized account return, not an authenticated venue fact."""

    account_scope: str
    route: str
    instrument: MarketInstrumentKey
    trading_day: str
    kind: DirectExecutionEventKind
    source_ref: str
    identity: NativeOrderIdentity | None = None
    identity_keys: tuple[str, ...] = ()
    binding_keys: tuple[str, ...] = ()
    venue_key: str | None = None
    trade_key: tuple[str, ...] | None = None
    status: DirectOrderStatus | None = None
    side: str | None = None
    offset: str | None = None
    order_quantity: str | None = None
    filled_quantity: str | None = None
    remaining_quantity: str | None = None
    limit_price: str | None = None
    trade_quantity: str | None = None
    trade_price: str | None = None
    trade_time: str | None = None
    error_code: str | None = None
    session_generation: int | None = None
    schema_version: int = 1
    cancel_request_key: str | None = None
    place_request_key: str | None = None
    trade_date: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema_version",
            "account_scope",
            "route",
            "instrument",
            "trading_day",
            "kind",
            "identity",
            "identity_keys",
            "binding_keys",
            "venue_key",
            "trade_key",
            "status",
            "side",
            "offset",
            "order_quantity",
            "filled_quantity",
            "remaining_quantity",
            "limit_price",
            "trade_quantity",
            "trade_price",
            "trade_time",
            "error_code",
            "source_ref",
            "session_generation",
        }
    )

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not int
            or self.schema_version not in (1, 2, 3, 4)
            or not all(_text(value) for value in (self.account_scope, self.route, self.source_ref))
            or type(self.instrument) is not MarketInstrumentKey
            or type(self.kind) is not DirectExecutionEventKind
            or (self.status is not None and type(self.status) is not DirectOrderStatus)
            or (
                self.session_generation is not None
                and (
                    type(self.session_generation) is not int
                    or not 0 <= self.session_generation < 2**63
                )
            )
        ):
            _fail()
        self._validate_version()
        if not _date(self.trading_day):
            _fail()
        try:
            instrument = MarketInstrumentKey.from_dict(self.instrument.to_dict())
        except Exception:
            _fail()
        object.__setattr__(self, "instrument", instrument)
        if not _key_tuple(self.identity_keys, min_size=0, max_size=16, sorted_unique=True):
            _fail()
        if not _key_tuple(self.binding_keys, min_size=0, max_size=16, sorted_unique=True):
            _fail()
        if not set(self.binding_keys).issubset(self.identity_keys):
            _fail()
        if self.venue_key is not None and (
            not _text(self.venue_key) or self.venue_key not in self.identity_keys
        ):
            _fail()
        if self.identity is None:
            if self.identity_keys:
                _fail()
        else:
            if type(self.identity) is not NativeOrderIdentity:
                _fail()
            try:
                validate_gateway_native_identity(self.identity)
                copied = NativeOrderIdentity(
                    self.identity.exchange_name,
                    self.identity.client_order_id,
                    dict(self.identity.fields),
                    self.identity.session_generation,
                )
                validate_gateway_native_identity(copied)
            except Exception:
                _fail()
            if copied.exchange_name != self.route or (
                "trading_day" in copied.fields and copied.fields["trading_day"] != self.trading_day
            ):
                _fail()
            object.__setattr__(self, "identity", copied)
        if self.trade_key is not None and not _key_tuple(
            self.trade_key, min_size=2, max_size=8, sorted_unique=False
        ):
            _fail()
        if self.kind is DirectExecutionEventKind.TRADE:
            if self.status is not None:
                _fail()
        elif any(
            value is not None
            for value in (self.trade_key, self.trade_quantity, self.trade_price, self.trade_time)
        ):
            _fail()
        if self.side is not None and (
            type(self.side) is not str or self.side not in {"buy", "sell"}
        ):
            _fail()
        if self.offset is not None and (
            type(self.offset) is not str
            or self.offset not in {"open", "close", "close_today", "close_yesterday"}
        ):
            _fail()
        if not all(
            _decimal(value, positive=True)
            for value in (
                self.order_quantity,
                self.limit_price,
                self.trade_quantity,
                self.trade_price,
            )
        ):
            _fail()
        if not all(
            _decimal(value, positive=False)
            for value in (self.filled_quantity, self.remaining_quantity)
        ):
            _fail()
        if self.trade_time is not None and not _text(self.trade_time):
            _fail()
        if self.error_code is not None and (
            type(self.error_code) is not str or _ERROR_CODE.fullmatch(self.error_code) is None
        ):
            _fail()
        _digest(self.to_mapping())  # Enforce the shared canonical payload size bound.

    def _validate_version(self) -> None:
        if (
            type(self.schema_version) is not int
            or self.schema_version not in (1, 2, 3, 4)
            or (self.schema_version != 2 and self.cancel_request_key is not None)
            or (self.schema_version != 3 and self.place_request_key is not None)
            or (self.schema_version != 4 and self.trade_date is not None)
            or (
                self.schema_version == 4
                and (
                    self.kind is not DirectExecutionEventKind.TRADE
                    or (self.trade_date is not None and not _date(self.trade_date))
                )
            )
            or (
                self.schema_version == 2
                and (
                    self.kind is not DirectExecutionEventKind.CANCEL_ERROR
                    or not _text(self.cancel_request_key)
                )
            )
            or (
                self.schema_version == 3
                and (
                    self.kind is not DirectExecutionEventKind.ORDER_ERROR
                    or self.status is not None
                    or not _text(self.place_request_key)
                )
            )
        ):
            _fail()

    def to_mapping(self) -> dict[str, Any]:
        """Return a detached JSON-compatible mapping in its explicit version."""
        self._validate_version()
        result = {
            "schema_version": self.schema_version,
            "account_scope": self.account_scope,
            "route": self.route,
            "instrument": self.instrument.to_dict(),
            "trading_day": self.trading_day,
            "kind": self.kind.value,
            "identity": None if self.identity is None else self.identity.to_dict(),
            "identity_keys": list(self.identity_keys),
            "binding_keys": list(self.binding_keys),
            "venue_key": self.venue_key,
            "trade_key": None if self.trade_key is None else list(self.trade_key),
            "status": None if self.status is None else self.status.value,
            "side": self.side,
            "offset": self.offset,
            "order_quantity": self.order_quantity,
            "filled_quantity": self.filled_quantity,
            "remaining_quantity": self.remaining_quantity,
            "limit_price": self.limit_price,
            "trade_quantity": self.trade_quantity,
            "trade_price": self.trade_price,
            "trade_time": self.trade_time,
            "error_code": self.error_code,
            "source_ref": self.source_ref,
            "session_generation": self.session_generation,
        }
        if self.schema_version == 2:
            result["cancel_request_key"] = self.cancel_request_key
        if self.schema_version == 3:
            result["place_request_key"] = self.place_request_key
        if self.schema_version == 4:
            result["trade_date"] = self.trade_date
        return result

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> GatewayReturnFact:
        """Decode complete, exact versioned mappings; errors omit input values."""
        try:
            if (
                not isinstance(raw, Mapping)
                or any(type(k) is not str for k in raw)
                or type(raw.get("schema_version")) is not int
                or raw["schema_version"] not in (1, 2, 3, 4)
                or set(raw)
                != (
                    cls._FIELDS
                    if raw["schema_version"] == 1
                    else cls._FIELDS
                    | {
                        {2: "cancel_request_key", 3: "place_request_key", 4: "trade_date"}[
                            raw["schema_version"]
                        ]
                    }
                )
            ):
                raise ValueError
            data = dict(raw)
            if type(data["kind"]) is not str or (
                data["status"] is not None and type(data["status"]) is not str
            ):
                raise ValueError
            data["kind"] = DirectExecutionEventKind(data["kind"])
            if data["status"] is not None:
                data["status"] = DirectOrderStatus(data["status"])
            data["instrument"] = MarketInstrumentKey.from_dict(data["instrument"])
            identity = data["identity"]
            if identity is not None:
                if (
                    not isinstance(identity, Mapping)
                    or any(type(key) is not str for key in identity)
                    or set(identity)
                    != {"exchange_name", "client_order_id", "fields", "session_generation"}
                    or not isinstance(identity["fields"], Mapping)
                ):
                    raise ValueError
                data["identity"] = NativeOrderIdentity.from_dict(identity)
            for key in ("identity_keys", "binding_keys"):
                if type(data[key]) is not list:
                    raise ValueError
                data[key] = tuple(data[key])
            if data["trade_key"] is not None:
                if type(data["trade_key"]) is not list:
                    raise ValueError
                data["trade_key"] = tuple(data["trade_key"])
            return cls(**data)
        except GatewayExecutionProtocolError:
            raise
        except Exception:
            raise GatewayExecutionProtocolError("INVALID_RETURN_MAPPING") from None

    def fact_digest(self) -> str:
        data = self.to_mapping()
        del data["source_ref"], data["session_generation"]
        return _digest(data)

    def trade_content_digest(self) -> str | None:
        if self.kind is not DirectExecutionEventKind.TRADE:
            return None
        data = self.to_mapping()
        return _digest(
            {
                key: data[key]
                for key in (
                    "account_scope",
                    "route",
                    "instrument",
                    "trading_day",
                    "trade_key",
                    "venue_key",
                    "side",
                    "offset",
                    "trade_quantity",
                    "trade_price",
                )
            }
        )
