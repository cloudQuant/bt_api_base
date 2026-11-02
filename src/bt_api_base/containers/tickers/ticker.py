"""Ticker class for defining ticker attributes and methods."""

from __future__ import annotations

from typing import Any

from bt_api_base.containers.auto_init_mixin import AutoInitMixin
from bt_api_base.containers.semantics import VOLUME_UNKNOWN


class TickerData(AutoInitMixin):
    """ticker."""

    def __init__(self, ticker_info: Any, has_been_json_encoded: bool = False) -> None:
        """__init__ method"""
        self.event = "TickerEvent"
        self.ticker_info = ticker_info
        self.has_been_json_encoded = has_been_json_encoded

    def init_data(self) -> TickerData:
        """Initialize ticker data from raw response.

        Returns: Self instance for method chaining.

        """
        raise NotImplementedError

    def get_all_data(self) -> dict[str, Any]:
        """Get all ticker data as dictionary.

        Returns: Dictionary containing all ticker data.

        """
        raise NotImplementedError

    def get_event(self) -> str:
        """Get event type.

        Returns: Event type string.

        """
        return self.event

    def get_exchange_name(self) -> str:
        """Get exchange name.

        Returns: Exchange name string.

        """
        raise NotImplementedError

    def get_local_update_time(self) -> float:
        """Get local update time.

        Returns: Local update timestamp.

        """
        raise NotImplementedError

    def get_symbol_name(self) -> str:
        """Get symbol name.

        Returns: Symbol name string.

        """
        raise NotImplementedError

    def get_ticker_symbol_name(self) -> str | None:
        """Get ticker symbol name from response.

        Returns: Ticker symbol name or None.

        """
        raise NotImplementedError

    def get_asset_type(self) -> str:
        """Get asset type.

        Returns: Asset type string.

        """
        raise NotImplementedError

    def get_server_time(self) -> float | None:
        """Get server time.

        Returns: Server timestamp or None.

        """
        raise NotImplementedError

    def get_bid_price(self) -> float | None:
        """Get bid price.

        Returns: Bid price or None.

        """
        raise NotImplementedError

    def get_ask_price(self) -> float | None:
        """Get ask price.

        Returns: Ask price or None.

        """
        raise NotImplementedError

    def get_bid_volume(self) -> float | None:
        """Get bid volume.

        Returns: Bid volume or None.

        """
        raise NotImplementedError

    def get_ask_volume(self) -> float | None:
        """Get ask volume.

        Returns: Ask volume or None.

        """
        raise NotImplementedError

    def get_last_price(self) -> float | None:
        """Get last price.

        Returns: Last price or None.

        """
        raise NotImplementedError

    def get_last_volume(self) -> float | None:
        """Get last volume.

        The meaning of this value is provider specific; see
        :meth:`get_volume_semantics`.

        Returns: Last volume or None.

        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Contract v1 semantic getters (iteration 60, D60-11).
    #
    # These have safe "unknown" defaults so every provider container answers
    # them. Providers override them when the native feed supplies the fact.
    # An unknown fact is None (or VOLUME_UNKNOWN), never zero or True.
    # ------------------------------------------------------------------

    def get_volume_semantics(self) -> str:
        """Return what :meth:`get_last_volume` reports.

        One of ``bt_api_base.containers.semantics.VOLUME_SEMANTICS``:
        ``delta``, ``cumulative``, ``last_trade``, ``rolling_24h`` or
        ``unknown`` (default).
        """
        return VOLUME_UNKNOWN

    def get_cumulative_volume(self) -> float | None:
        """Session/trading-day cumulative volume, or None when unknown."""
        return None

    def get_delta_volume(self) -> float | None:
        """Volume traded since the previous tick of the same stream, or None."""
        return None

    def get_volume_complete(self) -> bool | None:
        """Whether the delta volume is known to be gap free; None when unknown."""
        return None

    def get_continuity_status(self) -> str | None:
        """Provider stream continuity (e.g. ``continuous``/``gap``); None when unknown."""
        return None

    def get_execution_eligible(self) -> bool | None:
        """Provider/SDK decision that this quote may drive orders; None when unknown.

        A container must never self-promote this to True without the evidence
        required by its provider; the default is unknown.
        """
        return None

    def get_quality_flags(self) -> tuple[str, ...]:
        """Data-quality flags raised while parsing; empty when none were raised."""
        return ()

    def get_event_time_source(self) -> str | None:
        """How the event time was derived (e.g. ``action_day``); None when unknown."""
        return None

    def __str__(self) -> str:
        """String representation.

        Returns: String representation of ticker data.

        """
        raise NotImplementedError

    def __repr__(self) -> str:
        """Repr representation.

        Returns: String representation of ticker data.

        """
        raise NotImplementedError
