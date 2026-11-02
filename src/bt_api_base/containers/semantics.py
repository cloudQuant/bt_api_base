"""Shared semantic vocabulary for Base containers (contract v1).

Iteration 60 (opts line), step 60.02. These constants define what the
standard container getters mean across providers, so CTP, OKX and Binance
containers can be compared field by field. They describe semantics only; they
do not prove data provenance, freshness or trading eligibility.

Unknown facts are returned as ``None`` (or the ``*_UNKNOWN`` constant for
enumerations). A standard getter must never raise ``NotImplementedError`` on a
provider container: a fact the provider does not supply is unknown, not an
error, and must not be reported as zero.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "CONTAINER_CONTRACT_VERSION",
    "POSITION_SIDE_LONG",
    "POSITION_SIDE_NET",
    "POSITION_SIDE_SHORT",
    "POSITION_SIDES",
    "VOLUME_CUMULATIVE",
    "VOLUME_DELTA",
    "VOLUME_LAST_TRADE",
    "VOLUME_ROLLING_24H",
    "VOLUME_SEMANTICS",
    "VOLUME_UNKNOWN",
    "normalize_position_side",
]

CONTAINER_CONTRACT_VERSION = "bt_api_base.containers.v1"

# What TickerData.get_last_volume() reports (TickerData.get_volume_semantics()).
VOLUME_DELTA = "delta"  # traded volume since the previous tick of the same stream
VOLUME_CUMULATIVE = "cumulative"  # session/trading-day cumulative volume (CTP Volume)
VOLUME_LAST_TRADE = "last_trade"  # size of the most recent trade (OKX lastSz, Binance Q)
VOLUME_ROLLING_24H = "rolling_24h"  # rolling 24-hour volume
VOLUME_UNKNOWN = "unknown"
VOLUME_SEMANTICS = frozenset(
    {VOLUME_DELTA, VOLUME_CUMULATIVE, VOLUME_LAST_TRADE, VOLUME_ROLLING_24H, VOLUME_UNKNOWN}
)

# Normalized position side. Provider getters keep their native spelling for
# compatibility; use normalize_position_side() to compare across providers.
POSITION_SIDE_LONG = "long"
POSITION_SIDE_SHORT = "short"
POSITION_SIDE_NET = "net"
POSITION_SIDES = frozenset({POSITION_SIDE_LONG, POSITION_SIDE_SHORT, POSITION_SIDE_NET})

_POSITION_SIDE_ALIASES = {
    "long": POSITION_SIDE_LONG,
    "buy": POSITION_SIDE_LONG,
    "short": POSITION_SIDE_SHORT,
    "sell": POSITION_SIDE_SHORT,
    "net": POSITION_SIDE_NET,
    "both": POSITION_SIDE_NET,  # Binance one-way mode
}


def normalize_position_side(value: Any) -> str | None:
    """Map a provider position side to ``long``/``short``/``net``; else ``None``."""
    if not isinstance(value, str):
        return None
    return _POSITION_SIDE_ALIASES.get(value.strip().lower())
