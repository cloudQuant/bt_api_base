"""Shared legacy defaults for explicitly declared provider normalization."""

from types import MappingProxyType

from bt_api_base.order_identity_fields import LEGACY_ORDER_IDENTITY_FIELDS

from bt_api_base.order_provenance_fields import ORDER_ENVELOPE_FIELDS


class LegacyNormalizationPolicy:
    """Defaults do not establish provider, account or execution authority."""

    # No implicit venue-field contract; each route must select one explicitly.
    order_provenance_schemas = None
    order_provenance_source_fields = None
    order_provenance_envelope_fields = ORDER_ENVELOPE_FIELDS
    risk_order_source_aliases = None
    group_order_source_aliases = None
    group_fill_source_aliases = None

    # The selected provider must declare its status and fee field candidates.
    order_status_fields = None
    trade_fee_fields = None
    trade_id_fields = None

    # Every route explicitly chooses whether placements require the mode fence.
    position_mode_placement_guard_required = None

    # Each provider declares whether non-default risk position dimensions
    # require a source projection and, if needed, supplies that projection.
    risk_position_dimensions_require_projection = None
    risk_position_dimensions_projector = None

    # Provider-owned protected quote schema, if supported.
    quote_v2_schema = None
    quantity_unit = "base"
    default_multiplier = None
    zero_balance_currency = None
    funding_rate_fields = ("funding_rate", "rate")
    funding_time_fields = ()
    funding_interval_hours_fields = ()
    funding_interval_start_fields = ()
    funding_interval_end_fields = ()
    funding_raw_fields = (
        "funding_rate", "rate", "next_funding_time", "settlement_interval_seconds",
        "funding_interval_seconds",
    )
    fee_maker_fields = ("maker_rate", "maker")
    fee_taker_fields = ("taker_rate", "taker")
    fee_currency_fields = ("currency",)
    reconcile_terminal_order_commission = False
    # A provider must declare response item fields, including an empty tuple.
    response_error_item_fields = None
    # Result collection keys are provider-declared; this is the neutral default.
    result_collection_fields = ("data",)
    # Native acknowledgement codes must be selected by the provider.
    position_mode_ack_code = None
    trade_authority = False
    # Retain legacy candidates until each provider declares its own source
    # fields; this selection does not establish instrument identity.
    base_asset_type_fields = ("asset_type", "market_type")
    base_symbol_fields = (
        "symbol", "symbol_name", "instrument", "instrument_id", "data_name",
        "trade_symbol",
    )
    order_statuses = MappingProxyType(
        {
            "new": "accepted",
            "open": "accepted",
            "live": "accepted",
            "working": "accepted",
            "submitted": "submitted",
            "accepted": "accepted",
            "pending": "submitted",
            "partial": "partial",
            "partially_filled": "partial",
            "partial_filled": "partial",
            "filled": "completed",
            "completed": "completed",
            "cancelled": "canceled",
            "canceled": "canceled",
            "expired": "expired",
            "rejected": "rejected",
            "unknown": "unknown",
            "local_pending": "submitted",
        }
    )
    position_mode_boolean_field = None
    permission_fields = ("trading_permissions",)
    can_trade_fields = ("can_trade",)
    # A route must explicitly select its own or the historical identity fields.
    identity_nested_field = None
    identity_fields = None
    nested_identity_fields = MappingProxyType({})
    position_mode_fields = ("position_mode",)
    position_mode_aliases = MappingProxyType(
        {"oneway": "net", "one_way": "net", "hedge": "dual_side", "hedge_mode": "dual_side"}
    )
    event_id_fields = ("event_id", "trade_id", "fill_id", "order_id")
    exchange_time_fields = (
        "exchange_time", "timestamp", "server_time", "event_time", "event_time_utc",
        "timestamp_ms",
    )
    event_audit_fields = ("sequence", "sequence_id", "previous_sequence", "checksum", "action")
    orderbook_sequence_fields = ("sequence", "sequence_id", "update_id")
    orderbook_previous_fields = ("previous_sequence", "prev_sequence")
    orderbook_delta_predecessor_fields = ()
    tick_bid_fields = ("bid_price", "bid")
    tick_ask_fields = ("ask_price", "ask")
    tick_price_fields = ("price", "last_price", "last")
    tick_volume_fields = ("volume", "last_volume")
    tick_cumulative_fields = ("cum_volume", "cumulative_volume")
    tick_trading_day_fields = None
    tick_action_day_fields = None
    instrument_spec_fields = MappingProxyType({
        "symbol": ("symbol", "symbol_name"),
        "base_currency": ("base_currency",),
        "quote_currency": ("quote_currency",),
        "asset_type": ("asset_type",),
        "contract_type": ("contract_type",),
    })
    instrument_spec_linear_type_field = None
    instrument_fields = MappingProxyType({
        "multiplier": ("multiplier", "contract_size"),
        "step": ("lot_size", "order_size_step", "volume_step"),
        "min_size": ("min_size", "volume_min"),
        "max_size": ("max_size", "volume_max"),
        "tick_size": ("tick_size", "price_tick"),
        "settlement_currency": ("settlement_currency", "currency"),
        "base_currency": ("base_currency",),
        "margin_rate": ("margin_rate", "long_margin_rate"),
        "commission_rate": ("commission_rate", "taker_commission_rate"),
        "exchange_id": ("exchange_id",),
    })
    instrument_contract_value_field = None
    instrument_contract_multiplier_field = None
    instrument_linear_type_field = None
    instrument_perpetual_type_field = None
    balance_nested_fields = ("assets", "balances")
    balance_fields = MappingProxyType(
        {
            "currency": ("currency", "asset", "account_type", "symbol_name", "symbol"),
            "cash": (
                "available_cash",
                "available",
                "cash",
                "available_margin",
                "margin_free",
                "free_margin",
                "free",
            ),
            "value": ("equity", "value"),
            "wallet": ("balance", "margin", "total_wallet_balance"),
            "unrealized": ("unrealized_profit",),
            "margin_used": ("margin_used", "used_margin"),
            "account_id": ("account_id",),
        }
    )
    position_fields = MappingProxyType(
        {
            "quantity": ("quantity", "position_volume", "volume", "size", "trade_volume"),
            "side": ("position_side", "direction", "position_direction", "side"),
            "position_id": ("position_id", "ticket"),
            "price": ("average_price", "avg_price", "price", "price_open"),
            "today": ("today", "today_position", "today_volume"),
            "yesterday": ("yesterday", "yesterday_position"),
            "multiplier": ("multiplier", "contract_size"),
            "exchange_id": ("exchange_id",),
        }
    )
    order_fields = MappingProxyType(
        {
            "order_id": ("order_id", "external_order_id"),
            "client_id": ("client_order_id", "order_ref"),
            "filled": ("filled", "filled_quantity", "executed_qty"),
            "average": ("avg_price", "average_price", "order_avg_price"),
            "cum_quote": ("cum_quote",),
            "size": ("quantity", "size", "order_size"),
            "order_ref": ("order_ref",),
            "exchange_id": ("exchange_id",),
            "front_id": ("front_id",),
            "session_id": ("session_id",),
            "account_id": ("account_id",),
            "trading_day": ("trading_day",),
            "fee_currency": ("fee_currency",),
            "commission_currency": ("commission_currency", "fee_currency"),
        }
    )
    trade_fields = MappingProxyType(
        {
            "order_id": ("order_id", "external_order_id"),
            "client_id": ("client_order_id",),
            "size": ("quantity", "size", "trade_volume", "qty", "volume"),
            "price": ("trade_price", "price"),
            "exchange_id": ("exchange_id",),
            "account_id": ("account_id",),
            "trading_day": ("trading_day",),
            "fee_currency": ("fee_currency",),
        }
    )
    signed_fee_currency_field = None

    def instrument_metadata_defaults(self, row, *, pick):
        """Return optional neutral defaults selected by a provider."""
        return {}

    def order_average(self, row, average, *, pick, number):
        return average

    def apply_cancel_result(self, normalized, result, request):
        return None


class LegacyOrderProvenancePolicy(LegacyNormalizationPolicy):
    """Explicit opt-in to historical cross-venue normalization defaults."""

    risk_position_dimensions_require_projection = False
    position_mode_ack_code = "200"

    # Preserve the former non-OKX/Binance behavior pending provider review.
    # Explicit pre-migration field candidates for providers not yet reviewed.
    order_statuses = MappingProxyType({
        "new": "accepted", "open": "accepted", "live": "accepted", "working": "accepted",
        "submitted": "submitted", "accepted": "accepted", "pending": "submitted",
        "partial": "partial", "partially_filled": "partial", "partial_filled": "partial",
        "filled": "completed", "completed": "completed", "all_traded": "completed",
        "cancelled": "canceled", "canceled": "canceled",
        "expired": "expired", "expired_in_match": "expired", "rejected": "rejected",
        "unknown": "unknown", "local_pending": "submitted",
    })
    position_mode_aliases = MappingProxyType({
        "net_mode": "net", "oneway": "net", "one_way": "net",
        "long_short_mode": "dual_side", "hedge": "dual_side", "hedge_mode": "dual_side",
    })
    balance_nested_fields = ("details", "assets", "balances")
    balance_fields = MappingProxyType({
        "currency": (
            "currency", "ccy", "asset", "account_type", "symbol_name", "symbol",
        ),
        "cash": (
            "available_cash", "availableBalance", "available", "cash",
            "available_margin", "margin_free", "free_margin", "free",
        ),
        "value": ("equity", "eq", "value"),
        "wallet": ("balance", "walletBalance", "margin", "total_wallet_balance"),
        "unrealized": ("unrealizedProfit", "unrealized_profit"),
        "margin_used": ("margin_used", "used_margin"),
        "account_id": ("account_id",),
    })
    position_fields = MappingProxyType({
        "quantity": (
            "quantity", "position_volume", "volume", "size", "pos",
            "trade_volume",
        ),
        "side": (
            "position_side", "direction", "position_direction", "positionSide", "side",
        ),
        "position_id": ("position_id", "ticket"),
        "price": ("average_price", "avg_price", "price", "entryPrice", "price_open"),
        "today": ("today", "today_position", "today_volume"),
        "yesterday": ("yesterday", "yesterday_position", "yd_position"),
        "multiplier": ("multiplier", "contract_size", "volume_multiple"),
        "exchange_id": ("exchange_id",),
    })
    order_fields = MappingProxyType({
        "order_id": ("order_id", "external_order_id", "orderId", "order_sys_id"),
        "client_id": ("client_order_id", "order_ref"),
        "filled": ("filled", "filled_quantity", "executed_qty"),
        "average": ("avg_price", "average_price", "order_avg_price", "avgPrice"),
        "cum_quote": ("cum_quote", "cumQuote"),
        "size": ("quantity", "size", "order_size", "sz", "origQty"),
        "order_ref": ("order_ref",),
        "exchange_id": ("exchange_id",),
        "front_id": ("front_id",),
        "session_id": ("session_id",),
        "account_id": ("account_id",),
        "trading_day": ("trading_day",),
        "fee_currency": ("fee_currency",),
        "commission_currency": ("commission_currency", "fee_currency"),
    })
    trade_fields = MappingProxyType({
        "order_id": ("order_id", "external_order_id", "orderId"),
        "client_id": ("client_order_id",),
        "size": ("quantity", "size", "trade_volume", "qty", "volume"),
        "price": ("trade_price", "price"),
        "exchange_id": ("exchange_id",),
        "account_id": ("account_id",),
        "trading_day": ("trading_day",),
        "fee_currency": ("fee_currency", "trade_fee_symbol"),
    })
    position_mode_placement_guard_required = False
    # Transitional historical candidates; do not infer venue completeness.
    trade_fee_fields = ("fee_amount", "fee", "trade_fee", "commission")
    can_trade_fields = ("can_trade", "canTrade")
    position_mode_fields = ("position_mode", "positionMode")
    event_id_fields = ("event_id", "trade_id", "tradeId", "fill_id", "order_id", "orderId")
    instrument_spec_fields = MappingProxyType({
        "symbol": ("symbol", "symbol_name", "instId"),
        "base_currency": ("base_currency",),
        "quote_currency": ("quote_currency",),
        "asset_type": ("asset_type",),
        "contract_type": ("contract_type",),
    })
    event_audit_fields = (
        "sequence", "sequence_id", "previous_sequence", "pu", "U", "u",
        "checksum", "action", "ts", "E", "T",
    )
    orderbook_sequence_fields = ("sequence", "sequence_id", "update_id", "u")
    orderbook_previous_fields = ("previous_sequence", "prev_sequence", "pu")
    orderbook_delta_predecessor_fields = ("pu",)
    identity_fields = LEGACY_ORDER_IDENTITY_FIELDS


__all__ = ("LegacyNormalizationPolicy", "LegacyOrderProvenancePolicy")
