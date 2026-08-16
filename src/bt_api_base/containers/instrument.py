"""
 Instrument 

（、、、、、），
 ↔ 。
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import unique
from typing import Any

from bt_api_base._compat import StrEnum


@unique
class AssetType(StrEnum):
    """"""

    SPOT = "spot"
    SWAP = "swap"
    FUTURE = "future"
    OPTION = "option"
    STK = "stk"
    FUND = "fund"
    BOND = "bond"
    FX = "fx"
    INDEX = "index"


@dataclass(frozen=True)
class Instrument:
    """（，）"""

    # ===  ===
    internal: str  # ， BTC-USDT, IF2506, AAPL
    venue: str  # BINANCE___SWAP, CTP___FUTURE, IB___STK
    venue_symbol: str  # /， BTCUSDT, IF2506, AAPL
    asset_type: AssetType  # 

    # ===  ===
    underlying: str | None = None  # ：BTC、300、Apple
    base_currency: str | None = None  # （/）
    quote_currency: str | None = None  # 

    # === （FUTURE/OPTION） ===
    expiry: datetime | None = None
    strike: Decimal | None = None
    contract_size: Decimal | None = None
    option_type: str | None = None  # CALL / PUT

    # ===  ===
    tick_size: Decimal | None = None
    min_qty: Decimal | None = None
    max_qty: Decimal | None = None
    qty_step: Decimal | None = None
    min_notional: Decimal | None = None

    # ===  ===
    status: str = "active"  # active / suspend / expire / delist
    list_time: datetime | None = None
    delist_time: datetime | None = None

    # ===  ===
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        """is_expired method"""
        if self.expiry is None:
            return False
        return datetime.now() > self.expiry

    @property
    def is_listed(self) -> bool:
        """is_listed method"""
        if self.status != "active":
            return False
        return not (self.delist_time and datetime.now() > self.delist_time)

    def with_params(self, **kwargs: Any) -> Instrument:
        """Create a copy with updated parameters.

        Args: **kwargs: Field names and values to update.

        Returns: A new Instrument instance with updated fields.
        """
        return dataclasses.replace(self, **kwargs)


# ── InstrumentFactory ─────────────────────────────────────────

#  quote （，）
KNOWN_QUOTES = [
    "USDT",
    "USDC",
    "BUSD",
    "TUSD",
    "FDUSD",
    "USD",
    "BTC",
    "ETH",
    "BNB",
    "EUR",
    "GBP",
    "AUD",
    "TRY",
    "BRL",
]


class InstrumentFactory:
    """Instrument """

    @staticmethod
    def from_venue(
        venue: str,
        venue_symbol: str,
        asset_type: AssetType,
        **kwargs: Any,
    ) -> Instrument:
        """Create an Instrument from exchange symbol.

        Args: venue: Exchange identifier (e.g., "BINANCE___SPOT", "CTP___FUTURE").
            venue_symbol: Original exchange symbol (e.g., "BTCUSDT", "IF2506").
            asset_type: Type of asset (spot, swap, future, etc.).
            **kwargs: Additional instrument attributes.

        Returns: A new Instrument instance.
        """
        internal = InstrumentFactory._make_internal(venue, venue_symbol, asset_type)
        return Instrument(
            internal=internal,
            venue=venue,
            venue_symbol=venue_symbol,
            asset_type=asset_type,
            **kwargs,
        )

    @staticmethod
    def _make_internal(venue: str, venue_symbol: str, asset_type: AssetType) -> str:
        """Generate internal unified symbol.

        Parsing strategy:
        1. If symbol contains separators (-/_.), split by separator and join with '-'.
        2. Otherwise, match known quote currencies from the end.
        3. Return original symbol if matching fails.

        Args: venue: Exchange identifier.
            venue_symbol: Original exchange symbol.
            asset_type: Type of asset.

        Returns: Internal unified symbol (e.g., "BTC-USDT").
        """
        # （OKX, Bitget, KuCoin ）
        for sep in ["-", "/", "_", "."]:
            if sep in venue_symbol:
                parts = venue_symbol.split(sep)
                return "-".join(parts)

        # （Binance: BTCUSDT, DOGEUSDT, SHIBUSDT）
        upper = venue_symbol.upper()
        for quote in KNOWN_QUOTES:
            if upper.endswith(quote) and len(upper) > len(quote):
                base = upper[: -len(quote)]
                return f"{base}-{quote}"

        #  crypto （CTP: IF2506, IB: AAPL）
        return venue_symbol
