"""Joint-cut declarations are consistency checks, never account authority."""

from dataclasses import replace

import pytest

from bt_api_base.account_protocol import (
    AccountKey,
    AccountOpenOrder,
    AccountPosition,
    AccountResourceKey,
)
from bt_api_base.account_risk_cut_protocol import (
    AccountRiskCutClaim,
    RiskAccountSessionClaim,
    RiskCutInstrumentUnit,
    RiskCutOrder,
    RiskCutUnresolvedOrder,
    RiskOrderCutClaim,
)
from bt_api_base.account_row_observation_protocol import AccountOpenOrderObservation
from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.position_bootstrap_protocol import PositionStreamBinding, PositionStreamSnapshot

ACCOUNT = AccountKey("ctp", "simnow", "simnow", "account")
RESOURCE = AccountResourceKey("future", "margin")
INSTRUMENT = MarketInstrumentKey("ctp", "SHFE", "simnow", "future", "cu", "cu2401")
STAMP = "2026-01-01T00:00:00Z"
BINDING = PositionStreamBinding(ACCOUNT, "account-ref", "route", "session", 1, 2, "ready", 100)
SESSION = RiskAccountSessionClaim(ACCOUNT, "account-ref", "route", "session", 1)


def position(**changes):
    values = {"resource": RESOURCE, "instrument": INSTRUMENT, "side": "long", "quantity": "2",
                  "qty_unit": "lot", "average_price": None, "price_currency": None, "observed_at_utc": STAMP}
    values.update(changes)
    return AccountPosition(**values)


def order(**changes):
    values = {"resource": RESOURCE, "instrument": INSTRUMENT, "order_id": "order-1", "side": "buy",
                  "position_side": "long", "order_type": "limit", "status": "open", "quantity": "1",
                  "filled_quantity": "0", "qty_unit": "lot", "created_at_utc": STAMP, "observed_at_utc": STAMP}
    values.update(changes)
    return AccountOpenOrder(**values)


def entry(*, account=ACCOUNT, association="local", economic_ref="economic-1", **changes):
    return RiskCutOrder(AccountOpenOrderObservation(account, order(**changes)), association, economic_ref)


def position_cut(*rows, binding=BINDING, sequence=7):
    return PositionStreamSnapshot(binding, sequence, 50, "snapshot", tuple(rows))


def order_cut(*rows, session=SESSION, sequence=7, coverage="account", unresolved=(), domain="cut"):
    return RiskOrderCutClaim(session, sequence, coverage, tuple(rows), unresolved, domain)


def joint(*, snapshot=None, coverage="unknown", orders=None, session=SESSION, domain="cut"):
    return AccountRiskCutClaim(session, snapshot, coverage, orders, domain if snapshot is not None else None)


def test_consistent_claim_includes_both_sides_and_open_order():
    result = joint(snapshot=position_cut(position(), position(side="short")), coverage="account",
                   orders=order_cut(entry()))
    assert len(result.position_snapshot.positions) == 2
    assert result.order_cut.orders[0].economic_ref == "economic-1"
    # There is deliberately no usable / verified / authorization property.
    assert not hasattr(result, "usable")
    assert not hasattr(result, "verified")


def test_empty_and_unknown_batches_do_not_imply_zero_or_authority():
    result = joint(snapshot=position_cut(), coverage="unknown", orders=order_cut(coverage="unknown"))
    assert result.position_snapshot.positions == ()
    assert result.position_coverage == result.order_cut.coverage == "unknown"
    assert joint().position_snapshot is None
    with pytest.raises(ValueError, match="missing position snapshot"):
        joint(coverage="account")


@pytest.mark.parametrize("field,value", [("route_ref", "other-route"), ("session_ref", "other"),
                                         ("account_ref", "other"), ("connection_epoch", 3),
                                         ("account_key", replace(ACCOUNT, account_id="other"))])
def test_each_binding_dimension_must_match(field, value):
    other = replace(BINDING, **{field: value})
    with pytest.raises(ValueError, match="position binding"):
        joint(snapshot=position_cut(binding=other), coverage="account")
    with pytest.raises(ValueError, match="order session"):
        joint(orders=order_cut(session=replace(SESSION, **{field: value})))


def test_missing_position_subscription_is_not_invented():
    unknown = RiskAccountSessionClaim(ACCOUNT, None, "route", None, None)
    result = joint(session=unknown, orders=order_cut(session=unknown))
    assert result.position_snapshot is None
    assert result.session.session_ref is None
    # Unknown session fields do not become verified by a position declaration.
    with_snapshot = joint(session=unknown, snapshot=position_cut(), coverage="unknown")
    assert with_snapshot.session.session_ref is None
    with_order = joint(session=unknown, orders=order_cut(session=SESSION))
    assert with_order.session.session_ref is None
    with pytest.raises(ValueError, match="position binding"):
        joint(session=replace(unknown, route_ref="different"), snapshot=position_cut())
    assert joint(snapshot=position_cut(binding=replace(BINDING, subscription_epoch=4))).position_snapshot.binding.subscription_epoch == 4


@pytest.mark.parametrize("field,value", [("account_ref", "other-account-ref"),
                                         ("route_ref", "other-route"),
                                         ("session_ref", "other-session"),
                                         ("connection_epoch", 3)])
def test_inner_position_order_conflict_is_rejected_when_outer_unknown(field, value):
    unknown = RiskAccountSessionClaim(ACCOUNT, None, None, None, None)
    conflict = replace(SESSION, **{field: value})
    with pytest.raises(ValueError, match="position and order sessions conflict"):
        joint(session=unknown, snapshot=position_cut(), orders=order_cut(session=conflict))
    # An unknown order-side dimension remains unknown, not a positive match.
    absent = replace(SESSION, **{field: None})
    result = joint(session=unknown, snapshot=position_cut(), orders=order_cut(session=absent))
    assert getattr(result.order_cut.session, field) is None


def test_independently_declared_sequences_must_match():
    with pytest.raises(ValueError, match="cut sequences differ"):
        joint(snapshot=position_cut(sequence=1), coverage="account", orders=order_cut(sequence=2))
    with pytest.raises(ValueError, match="sequence"):
        order_cut(sequence=True)
    with pytest.raises(ValueError, match="cut domains differ"):
        joint(snapshot=position_cut(), coverage="account", orders=order_cut(domain="other"))
    # Equal numbers in an unknown domain are not evidence of a shared cut.
    assert joint(snapshot=position_cut(), coverage="unknown", orders=order_cut(domain=None)).order_cut.cut_domain_ref is None


def test_order_subscription_claim_is_independent_and_may_be_unknown():
    assert order_cut().order_subscription_ref is None
    cut = replace(order_cut(), order_subscription_ref="order-subscription",
                  order_subscription_epoch=3, order_valid_until_ns=99,
                  order_receipt_ref="order-receipt")
    assert cut.order_subscription_epoch == 3
    assert cut.order_receipt_ref == "order-receipt"
    with pytest.raises(ValueError):
        replace(cut, order_subscription_epoch=True)
    with pytest.raises(ValueError):
        replace(cut, order_subscription_ref=None)
    with pytest.raises(ValueError):
        replace(cut, order_receipt_ref="\x00")


def test_instrument_unit_and_quote_currency_are_explicit_claims():
    claim = RiskCutInstrumentUnit(INSTRUMENT, "lot", None)
    value = replace(joint(snapshot=position_cut(position()), coverage="account"), instrument_units=(claim,))
    assert value.instrument_units[0].quote_currency is None
    with pytest.raises(ValueError, match="quantity unit"):
        replace(value, instrument_units=(replace(claim, quantity_unit="coin"),))
    with pytest.raises(ValueError, match="duplicate instrument"):
        replace(value, instrument_units=(claim, claim))
    with pytest.raises(ValueError, match="does not match"):
        replace(value, instrument_units=(replace(claim, instrument=replace(INSTRUMENT, provider="other")),))


def test_account_scope_and_instrument_scope_cannot_be_mixed():
    wrong_account = replace(ACCOUNT, account_id="other")
    with pytest.raises(ValueError, match="order account"):
        order_cut(entry(account=wrong_account))
    wrong_instrument = replace(INSTRUMENT, environment="live")
    with pytest.raises(ValueError, match="account scope"):
        joint(snapshot=position_cut(position(instrument=wrong_instrument)), coverage="account")
    with pytest.raises(ValueError, match="account scope"):
        entry(instrument=wrong_instrument)
    with pytest.raises(ValueError, match="unresolved order account"):
        order_cut(unresolved=(RiskCutUnresolvedOrder(wrong_account, "unknown"),))


def test_unknown_and_unmatched_external_orders_remain_explicit():
    external = entry(association="external", economic_ref=None)
    unresolved = RiskCutUnresolvedOrder(ACCOUNT, "terminal_not_projected")
    result = joint(orders=order_cut(external, coverage="partial", unresolved=(unresolved,)))
    assert result.order_cut.orders[0].association == "external"
    assert result.order_cut.unresolved == (unresolved,)
    with pytest.raises(ValueError, match="local association"):
        entry(association="local", economic_ref=None)


def test_duplicate_provider_and_cross_source_economic_identity_are_rejected():
    with pytest.raises(ValueError, match="duplicate provider order"):
        order_cut(entry(), entry(economic_ref="different"))
    with pytest.raises(ValueError, match="duplicate economic"):
        order_cut(entry(), entry(order_id="different"))
    # The active remainder and an unresolved fill projection can be two
    # components of the same partially filled economic order.
    unresolved = RiskCutUnresolvedOrder(ACCOUNT, "fill_not_projected", "economic-1")
    cut = order_cut(entry(status="partially_filled", filled_quantity="0.5"), unresolved=(unresolved,))
    assert cut.orders[0].economic_ref == cut.unresolved[0].economic_ref
    with pytest.raises(ValueError, match="duplicate economic"):
        order_cut(unresolved=(unresolved, unresolved))
    terminal = RiskCutUnresolvedOrder(ACCOUNT, "terminal_not_projected", "terminal-1")
    assert order_cut(unresolved=(terminal,)).unresolved[0].reason == "terminal_not_projected"
    with pytest.raises(ValueError, match="duplicate economic"):
        order_cut(unresolved=(terminal, terminal))


def test_row_price_currency_is_not_inferred_as_contract_quote_currency():
    value = joint(snapshot=position_cut(position(price_currency="USD")), coverage="account",
                  orders=order_cut(entry(price_currency="EUR")))
    value = replace(value, instrument_units=(RiskCutInstrumentUnit(INSTRUMENT, "lot", "CNY"),))
    assert value.position_snapshot.positions[0].price_currency == "USD"
    assert value.order_cut.orders[0].observation.open_order.price_currency == "EUR"
    assert value.instrument_units[0].quote_currency == "CNY"
    assert not hasattr(value, "usable")


@pytest.mark.parametrize("other", [position(), position(side="net"), position(side="short", qty_unit="coin")])
def test_duplicate_position_and_inconsistent_units_are_rejected(other):
    with pytest.raises(ValueError):
        joint(snapshot=position_cut(position(), other), coverage="account")


def test_position_order_and_order_order_unit_mismatch_rejected():
    with pytest.raises(ValueError, match="quantity unit"):
        joint(snapshot=position_cut(position()), coverage="account", orders=order_cut(entry(qty_unit="coin")))
    with pytest.raises(ValueError, match="quantity unit"):
        joint(orders=order_cut(entry(), entry(order_id="other", economic_ref="other", qty_unit="coin")))
    with pytest.raises(ValueError, match="quantity unit"):
        joint(snapshot=position_cut(position()), coverage="account", orders=order_cut(
            entry(resource=AccountResourceKey("future", "other-margin"), qty_unit="coin")
        ))


def test_partial_coverage_is_preserved_and_invalid_claims_are_rejected():
    assert joint(snapshot=position_cut(), coverage="partial").position_coverage == "partial"
    for value in (True, "complete", ""):
        with pytest.raises(ValueError, match="coverage"):
            order_cut(coverage=value)
    with pytest.raises(ValueError, match="association"):
        entry(association="accepted")
    with pytest.raises(ValueError, match="unresolved"):
        RiskCutUnresolvedOrder(ACCOUNT, "complete")
    with pytest.raises(ValueError, match="reference"):
        entry(economic_ref="\x00")
