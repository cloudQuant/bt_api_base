"""Neutral market subscription keys shared by provider and service adapters."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

from bt_api_base.service_protocol import MAX_REFERENCE_BYTES

MARKET_EVENT_SCHEMA = "sdk.market.event"
MARKET_EVENT_SCHEMA_VERSION = 1
MARKET_EVENT_OPERATION = "market.event"

_MAX_DEPTH = 1_000_000


def _check_text(value: Any, field: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{field} must be a string")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field} must be printable UTF-8") from exc
    if (
        not encoded
        or len(encoded) > MAX_REFERENCE_BYTES
        or value != value.strip()
        or not value.isprintable()
    ):
        raise ValueError(f"{field} must be non-empty printable UTF-8 within the byte limit")
    return value


def _check_optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _check_text(value, field)


def _require_exact_mapping(value: Any, fields: frozenset[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise TypeError(f"{name} must be a string-keyed mapping")
    if set(value) != fields:
        raise ValueError(f"{name} has an invalid field set")
    return value


@dataclass(frozen=True)
class MarketInstrumentKey:
    """Canonical instrument identity plus its provider-native symbol spelling."""

    provider: str
    venue: str
    environment: str
    product_type: str
    instrument_id: str
    native_symbol: str

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "provider",
            "venue",
            "environment",
            "product_type",
            "instrument_id",
            "native_symbol",
        }
    )

    def __post_init__(self) -> None:
        for field in (
            "provider",
            "venue",
            "environment",
            "product_type",
            "instrument_id",
            "native_symbol",
        ):
            _check_text(getattr(self, field), field)

    def to_dict(self) -> dict[str, str]:
        """Return a fresh JSON-ready mapping with the complete identity."""
        return {
            "provider": self.provider,
            "venue": self.venue,
            "environment": self.environment,
            "product_type": self.product_type,
            "instrument_id": self.instrument_id,
            "native_symbol": self.native_symbol,
        }

    @classmethod
    def from_dict(cls, mapping: Mapping[str, Any]) -> MarketInstrumentKey:
        """Load the exact published field shape, rejecting missing or extra fields."""
        raw = _require_exact_mapping(mapping, cls._FIELDS, "instrument")
        return cls(
            provider=raw["provider"],
            venue=raw["venue"],
            environment=raw["environment"],
            product_type=raw["product_type"],
            instrument_id=raw["instrument_id"],
            native_symbol=raw["native_symbol"],
        )


@dataclass(frozen=True)
class MarketSubscriptionKey:
    """Immutable identity for sharing one upstream market subscription."""

    source_ref: str
    entitlement_ref: str
    instrument: MarketInstrumentKey
    channel: str
    depth: int | None = None
    timeframe: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"source_ref", "entitlement_ref", "instrument", "channel", "depth", "timeframe"}
    )

    def __post_init__(self) -> None:
        _check_text(self.source_ref, "source_ref")
        _check_text(self.entitlement_ref, "entitlement_ref")
        if type(self.instrument) is not MarketInstrumentKey:
            raise TypeError("instrument must be a MarketInstrumentKey")
        _check_text(self.channel, "channel")
        if self.depth is not None:
            if type(self.depth) is not int:
                raise TypeError("depth must be an integer or None")
            if not 1 <= self.depth <= _MAX_DEPTH:
                raise ValueError("depth is outside the supported range")
        _check_optional_text(self.timeframe, "timeframe")

    @property
    def stream_id(self) -> str:
        """Return a process-stable digest over every subscription-key dimension."""
        canonical = json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return f"market-{hashlib.sha256(canonical).hexdigest()}"

    def to_dict(self) -> dict[str, Any]:
        """Return a fresh JSON-ready mapping, including optional fields as null."""
        return {
            "source_ref": self.source_ref,
            "entitlement_ref": self.entitlement_ref,
            "instrument": self.instrument.to_dict(),
            "channel": self.channel,
            "depth": self.depth,
            "timeframe": self.timeframe,
        }

    @classmethod
    def from_dict(cls, mapping: Mapping[str, Any]) -> MarketSubscriptionKey:
        """Load only the exact published wire shape."""
        raw = _require_exact_mapping(mapping, cls._FIELDS, "subscription")
        instrument = MarketInstrumentKey.from_dict(raw["instrument"])
        return cls(
            source_ref=raw["source_ref"],
            entitlement_ref=raw["entitlement_ref"],
            instrument=instrument,
            channel=raw["channel"],
            depth=raw["depth"],
            timeframe=raw["timeframe"],
        )


__all__ = [
    "MARKET_EVENT_OPERATION",
    "MARKET_EVENT_SCHEMA",
    "MARKET_EVENT_SCHEMA_VERSION",
    "MarketInstrumentKey",
    "MarketSubscriptionKey",
]
