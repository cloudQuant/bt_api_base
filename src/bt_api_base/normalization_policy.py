"""Shared legacy defaults for explicitly declared provider normalization."""


class LegacyNormalizationPolicy:
    """Defaults do not establish provider, account or execution authority."""

    quantity_unit = "base"
    default_multiplier = None
    zero_balance_currency = None
    funding_time_fields = ("nextFundingTime", "fundingTime")
    position_mode_ack_code = "200"
    trade_authority = False
    event_id_fields = ("event_id", "trade_id", "tradeId", "fill_id", "order_id", "orderId", "ordId")
    event_audit_fields = (
        "sequence", "sequence_id", "previous_sequence", "prevSeqId", "pu", "U", "u",
        "checksum", "action", "ts", "E", "T",
    )
    orderbook_sequence_fields = ("sequence", "sequence_id", "update_id", "lastUpdateId", "u")
    orderbook_previous_fields = ("previous_sequence", "prev_sequence", "prevSeqId", "pu")
    orderbook_delta_predecessor_fields = ("pu",)
    tick_bid_fields = ("bid_price", "bid", "BidPrice1")
    tick_ask_fields = ("ask_price", "ask", "AskPrice1")
    tick_price_fields = ("price", "last_price", "last", "LastPrice")
    tick_volume_fields = ("volume", "last_volume", "Volume")
    tick_cumulative_fields = ("cum_volume", "cumulative_volume", "Volume")

    def order_average(self, row, average, *, pick, number):
        return average

    def apply_cancel_result(self, normalized, result, request):
        return None


def legacy_normalization_policy(exchange_name):
    """Return the legacy defaults explicitly selected by one provider route."""
    return LegacyNormalizationPolicy()


__all__ = ("LegacyNormalizationPolicy", "legacy_normalization_policy")
