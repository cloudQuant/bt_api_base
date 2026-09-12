"""Module-level docstring."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


@dataclass
class GatewayTick:
    """Class GatewayTick"""

    timestamp: float
    symbol: str
    exchange: str = ""
    asset_type: str = ""
    local_time: float | None = None
    price: float = 0.0
    volume: float = 0.0
    direction: str = "buy"
    trade_id: str = ""
    bid_price: float | None = None
    ask_price: float | None = None
    bid_volume: float | None = None
    ask_volume: float | None = None
    openinterest: float = 0.0
    turnover: float = 0.0
    datetime: datetime | None = None
    instrument_id: str = ""
    exchange_id: str = ""
    trading_day: str = ""
    action_day: str = ""
    update_time: str = ""
    update_millisec: int = 0
    high_price: float | None = None
    low_price: float | None = None
    open_price: float | None = None
    prev_close: float | None = None
    # Quote V2 is additive so legacy gateway consumers can continue to read
    # the compact tick fields above.  These fields are deliberately declared
    # here (rather than attached dynamically by an adapter): both ``to_dict``
    # and the remote protocol serialize dataclass fields only.
    schema_version: str = ""
    volume_semantics: str = ""
    cum_volume: float | None = None
    cumulative_volume: float | None = None
    delta_volume: float | None = None
    volume_complete: bool = False
    volume_quality: str = "unknown"
    continuity_status: str = "unverified"
    quality_flags: tuple[str, ...] = ()
    last_price: float | None = None
    lower_limit_price: float | None = None
    upper_limit_price: float | None = None
    event_time_utc: datetime | None = None
    recv_time_utc: datetime | None = None
    recv_monotonic_ns: int = 0
    connection_generation: int = 0
    ingest_seq: int = 0
    subscription_epoch: int = 0
    rules_hash: str = ""
    clock_domain_id: str = ""
    source: str = "unknown"
    event_time_source: str = "unresolved"
    source_clock_quality: str = "unknown"
    receive_clock_quality: str = "unknown"
    source_clock_error_ms: float | None = None
    receive_clock_error_ms: float | None = None
    freshness_verified: bool = False
    execution_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        """to_dict method"""
        payload = asdict(self)
        for name in ("datetime", "event_time_utc", "recv_time_utc"):
            value = getattr(self, name)
            if value is not None:
                payload[name] = value.isoformat()
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> GatewayTick:
        """from_dict method"""
        data = dict(payload)
        dt_value = data.get("datetime")
        if isinstance(dt_value, str) and dt_value:
            data["datetime"] = datetime.fromisoformat(dt_value)
        else:
            data["datetime"] = None
        for name in ("event_time_utc", "recv_time_utc"):
            value = data.get(name)
            if isinstance(value, str) and value:
                data[name] = datetime.fromisoformat(value)
            elif value is None:
                data[name] = None
        quality_flags = data.get("quality_flags")
        if isinstance(quality_flags, list):
            data["quality_flags"] = tuple(str(flag) for flag in quality_flags)
        known = {f.name for f in cls.__dataclass_fields__.values()}
        data = {k: v for k, v in data.items() if k in known}
        return cls(**data)
