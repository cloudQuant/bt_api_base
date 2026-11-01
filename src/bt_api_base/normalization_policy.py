"""Shared legacy defaults for explicitly declared provider normalization."""

from types import MappingProxyType


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
    instrument_fields = MappingProxyType({
        "multiplier": ("multiplier", "contract_size", "VolumeMultiple", "ctVal"),
        "step": ("lot_size", "order_size_step", "volume_step", "lotSz", "stepSize"),
        "min_size": ("min_size", "volume_min", "minSz", "MinLimitOrderVolume"),
        "max_size": ("max_size", "volume_max", "maxLmtSz", "MaxLimitOrderVolume"),
        "tick_size": ("tick_size", "price_tick", "tickSz", "PriceTick"),
        "settlement_currency": ("settlement_currency", "settleCcy", "marginAsset", "currency"),
        "base_currency": ("base_currency", "baseAsset", "ctValCcy", "baseCcy"),
        "margin_rate": ("margin_rate", "LongMarginRatio", "long_margin_rate"),
        "commission_rate": ("commission_rate", "taker_commission_rate"),
        "exchange_id": ("exchange_id", "ExchangeID"),
    })
    instrument_uses_filters = True
    instrument_contract_value_field = "ctVal"
    instrument_contract_multiplier_field = "ctMult"
    instrument_linear_type_field = "ctType"
    instrument_perpetual_type_field = "contractType"
    balance_nested_fields = ("details", "assets", "balances")
    balance_fields = MappingProxyType({
        "currency": (
            "CurrencyID", "currency", "ccy", "asset", "account_type", "symbol_name", "symbol",
        ),
        "cash": (
            "available_cash", "availEq", "availBal", "availableBalance", "available", "cash",
            "available_margin", "Available", "margin_free", "free_margin", "free",
        ),
        "value": ("Balance", "equity", "eq", "marginBalance", "value"),
        "wallet": ("balance", "walletBalance", "cashBal", "margin", "total_wallet_balance"),
        "unrealized": ("crossUnPnl", "unrealizedProfit", "unrealized_profit"),
        "margin_used": ("margin_used", "used_margin", "initialMargin", "CurrMargin"),
        "account_id": ("account_id", "AccountID"),
    })
    position_fields = MappingProxyType({
        "quantity": (
            "quantity", "position_volume", "volume", "size", "pos", "positionAmt", "Position",
            "trade_volume",
        ),
        "side": (
            "position_side", "direction", "position_direction", "posSide", "positionSide", "side",
        ),
        "position_id": ("position_id", "ticket"),
        "price": ("average_price", "avg_price", "price", "avgPx", "entryPrice", "price_open"),
        "today": ("today", "today_position", "today_volume", "TodayPosition"),
        "yesterday": ("yesterday", "yesterday_position", "yd_position", "YdPosition"),
        "multiplier": ("multiplier", "contract_size", "volume_multiple", "VolumeMultiple"),
        "exchange_id": ("exchange_id", "ExchangeID"),
    })
    order_fields = MappingProxyType({
        "order_id": ("order_id", "external_order_id", "ordId", "orderId", "order_sys_id", "OrderSysID"),
        "client_id": ("client_order_id", "clOrdId", "clientOrderId", "order_ref", "OrderRef"),
        "filled": ("filled", "filled_quantity", "executed_qty", "accFillSz", "executedQty", "VolumeTraded"),
        "average": ("avg_price", "average_price", "order_avg_price", "avgPx", "avgPrice"),
        "cum_quote": ("cum_quote", "cumQuote", "cummulativeQuoteQty"),
        "size": ("quantity", "size", "order_size", "sz", "origQty", "VolumeTotalOriginal"),
        "order_ref": ("order_ref", "OrderRef"),
        "exchange_id": ("exchange_id", "ExchangeID"),
        "front_id": ("front_id", "FrontID"),
        "session_id": ("session_id", "SessionID"),
        "account_id": ("account_id", "AccountID", "InvestorID"),
        "trading_day": ("trading_day", "TradingDay"),
        "fee_currency": ("fee_currency", "feeCcy", "commissionAsset"),
        "commission_currency": ("commission_currency", "fee_currency", "feeCcy", "commissionAsset"),
    })
    trade_fields = MappingProxyType({
        "trade_id": ("trade_id", "fill_id", "deal_id", "tradeId", "id", "TradeID"),
        "order_id": ("order_id", "external_order_id", "orderId", "ordId", "OrderSysID"),
        "client_id": ("client_order_id", "clOrdId", "OrderRef"),
        "size": ("quantity", "size", "trade_volume", "qty", "fillSz", "volume", "Volume"),
        "price": ("trade_price", "price", "fillPx", "Price"),
        "exchange_id": ("exchange_id", "ExchangeID"),
        "account_id": ("account_id", "AccountID", "InvestorID"),
        "trading_day": ("trading_day", "TradingDay"),
        "fee_currency": ("fee_currency", "trade_fee_symbol", "commissionAsset", "feeCcy"),
    })
    signed_fee_currency_field = "feeCcy"

    def order_average(self, row, average, *, pick, number):
        return average

    def apply_cancel_result(self, normalized, result, request):
        return None


def legacy_normalization_policy(exchange_name):
    """Return the legacy defaults explicitly selected by one provider route."""
    return LegacyNormalizationPolicy()


__all__ = ("LegacyNormalizationPolicy", "legacy_normalization_policy")
