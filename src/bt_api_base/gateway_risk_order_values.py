"""Compare a canonical Gateway order's values with an independent Risk view.

This is only a value check, not an attestation, authorization, or evidence of
provider/account identity. In particular, route, strategy, origin, full
instrument identity, hedge fields and native broker identity remain unproved.
The wire shape and scalar checks follow the SDK Gateway decoder, but this
comparison deliberately accepts a narrower set: the view and venue must
match, and Risk's decimal encoding guard must succeed. It is not an equivalent
replacement for the SDK decoder. Keep the shared checks in sync with it.
"""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from typing import NamedTuple

from bt_api_base.gateway_direct_protocol import canonical_gateway_payload
from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.risk_service_protocol import RiskOrderView

_REQUIRED = frozenset({"symbol", "side", "order_type", "quantity", "account_id",
                       "client_order_id", "time_in_force", "idempotency_key", "quantity_unit"})
_OPTIONAL = frozenset({"price", "position_side", "offset", "position_id", "position_mode",
                       "exchange_id", "hedge_flag", "hedge_class"})
_FORBIDDEN = frozenset({"instrument", "ctp_order_identity", "execution_cycle_id", "execution_role",
                        "strategy_identity_sha256", "managed_intent_id", "runtime_order_id"})
_FIELDS = _REQUIRED | _OPTIONAL | _FORBIDDEN | {"reduce_only"}
_FIXED = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")


class GatewayRiskOrderValuesError(ValueError):
    """Finite failure without exposing submitted values."""

    def __init__(self) -> None:
        self.code = "GATEWAY_RISK_ORDER_VALUES_INVALID"
        super().__init__(self.code)


class GatewayRiskOrderValues(NamedTuple):
    """Immutable checked bytes and digests; they do not establish authority."""

    canonical_payload: str
    payload_digest: str
    view_digest: str


def _view_snapshot(view: RiskOrderView) -> RiskOrderView:
    # Read only exact built-in immutable values before constructing a fresh
    # view. A frozen dataclass can still be altered using object.__setattr__.
    names = (
        "account_scope", "route", "strategy_ref", "origin", "request_key", "instrument",
        "side", "offset", "position_side", "quantity", "quantity_unit", "order_type",
        "limit_price", "time_in_force", "trading_day", "session_epoch", "parent_ref",
        "child_id", "schema_version",
    )
    values = {name: object.__getattribute__(view, name) for name in names}
    for name in ("account_scope", "route", "strategy_ref", "origin", "request_key", "side",
                 "position_side", "quantity_unit", "order_type"):
        if type(values[name]) is not str:
            raise GatewayRiskOrderValuesError()
    for name in ("offset", "time_in_force", "trading_day", "session_epoch", "parent_ref",
                 "child_id"):
        if values[name] is not None and type(values[name]) is not str:
            raise GatewayRiskOrderValuesError()
    if (type(values["schema_version"]) is not int or type(values["quantity"]) is not Decimal
            or (values["limit_price"] is not None and type(values["limit_price"]) is not Decimal)):
        raise GatewayRiskOrderValuesError()
    instrument = values["instrument"]
    if type(instrument) is not MarketInstrumentKey:
        raise GatewayRiskOrderValuesError()
    instrument_values = {name: object.__getattribute__(instrument, name)
                         for name in MarketInstrumentKey._FIELDS}
    if any(type(value) is not str for value in instrument_values.values()):
        raise GatewayRiskOrderValuesError()
    values["instrument"] = MarketInstrumentKey(**instrument_values)
    return RiskOrderView(**values)


def _decimal(text: str) -> Decimal:
    # SDK's Decimal -> format(..., 'f') roundtrip accepts precisely this fixed
    # positive representation. Check shape first to avoid expanding exponents.
    if _FIXED.fullmatch(text) is None:
        raise GatewayRiskOrderValuesError()
    try:
        value = Decimal(text)
        if not value.is_finite() or value <= 0 or format(value, "f") != text:
            raise GatewayRiskOrderValuesError()
        return value
    except InvalidOperation:
        raise GatewayRiskOrderValuesError() from None


def validate_gateway_risk_order_values(
    payload: object, view: object, payload_digest: object
) -> GatewayRiskOrderValues:
    """Validate comparable values and return the checked immutable snapshots.

    This checks the 25-field scalar wire shape accepted by the SDK direct
    decoder and additionally requires a matching view and venue. It may refuse
    SDK-decodable values, including values blocked by Risk's decimal guard.
    The digest covers even fields that the view cannot compare. An exact venue
    and native symbol comparison does not establish full instrument identity.
    Downstream consumers must use the returned canonical payload, not the
    mutable input. The captured view digest is not a later transaction fence.
    """
    try:
        if type(payload) is not dict or type(view) is not RiskOrderView:
            raise GatewayRiskOrderValuesError()
        # Exact dict.copy is callback-free. Reject non-built-in scalars before
        # sorting, hashing, equality checks, or any other user-defined method.
        snapshot = dict.copy(payload)
        if any(type(key) is not str or type(value) not in (str, bool, type(None))
               for key, value in snapshot.items()):
            raise GatewayRiskOrderValuesError()
        checked_view = _view_snapshot(view)
        canonical = canonical_gateway_payload(snapshot)
        digest = hashlib.sha256(canonical.encode("ascii")).hexdigest()
        payload = json.loads(canonical)
        if (set(payload) != _FIELDS
                or any(type(payload[k]) is not str for k in _REQUIRED)
                or any(payload[k] is not None and type(payload[k]) is not str for k in _OPTIONAL)
                or any(payload[k] is not None for k in _FORBIDDEN)
                or type(payload["reduce_only"]) is not bool):
            raise GatewayRiskOrderValuesError()
        if type(payload_digest) is not str or payload_digest != digest:
            raise GatewayRiskOrderValuesError()
        if (not payload["symbol"] or not payload["account_id"] or not payload["client_order_id"]
                or payload["side"] not in {"buy", "sell"}
                or payload["order_type"] not in {"limit", "market"}
                or payload["quantity_unit"] not in {"base", "contracts", "lots", "native"}
                or payload["offset"] not in {None, "open", "close", "close_today", "close_yesterday"}
                or payload["position_mode"] not in {None, "net", "dual_side"}
                or payload["hedge_flag"] not in {None, "1", "2", "3", "5", "6", "7"}
                or payload["hedge_class"] not in {None, "speculation", "arbitrage", "hedge"}):
            raise GatewayRiskOrderValuesError()
        quantity = _decimal(payload["quantity"])
        price = None if payload["price"] is None else _decimal(payload["price"])
        if (payload["order_type"] == "market") != (price is None):
            raise GatewayRiskOrderValuesError()
        # This exercises the existing exact Risk-view encoding guard as well.
        view_digest = checked_view.digest()
        view = checked_view
        if (payload["account_id"] != view.account_scope
                or payload["idempotency_key"] != view.request_key
                or payload["symbol"] != view.instrument.native_symbol
                or payload["exchange_id"] != view.instrument.venue
                or quantity != view.quantity or price != view.limit_price
                or payload["side"].upper() != view.side
                or payload["order_type"].upper() != view.order_type
                or (None if payload["offset"] is None else payload["offset"].upper()) != view.offset
                or ("NET" if payload["position_side"] is None
                    else payload["position_side"].upper()) != view.position_side
                or payload["quantity_unit"] != view.quantity_unit
                or payload["time_in_force"] != view.time_in_force):
            raise GatewayRiskOrderValuesError()
        return GatewayRiskOrderValues(canonical, digest, view_digest)
    except Exception:
        raise GatewayRiskOrderValuesError() from None
