"""Synthetic decimal encoding tests; no account or provider evidence."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal, Inexact, Overflow, Rounded, Underflow, localcontext
from threading import Barrier

import pytest

from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.risk_service_protocol import (
    RiskOrderView,
    RiskParentView,
    RiskServiceProtocolError,
    _decimal_text,
)


INSTRUMENT = MarketInstrumentKey("ctp", "SHFE", "simnow", "future", "rb2701", "rb2701")


def _order(quantity="1", price="100"):
    return RiskOrderView(
        "account", "route", "strategy", "strategy", "request", INSTRUMENT,
        "BUY", "OPEN", "NET", quantity, "lots", "LIMIT", price,
    )


def _parent(quantity="1", price="100"):
    return RiskParentView(
        "account", "route", "strategy", "parent", INSTRUMENT,
        "SELL", "OPEN", "NET", quantity, "lots", price, "20261112", "20261112",
    )


@pytest.mark.parametrize("factory,quantity_key", [(_order, "quantity"), (_parent, "total_quantity")])
def test_mapping_and_digest_ignore_precision_and_traps(factory, quantity_key):
    quantity = "1.23456789012345678901234567890123456789"
    price = "100.00001"
    view = factory(quantity, price)
    with localcontext() as context:
        context.prec = 60
        expected = view.to_mapping(), view.digest()
    for precision in (1, 4, 28, 80):
        with localcontext() as context:
            context.prec = precision
            context.Emin = -2
            context.Emax = 2
            for signal in (Inexact, Rounded, Underflow, Overflow):
                context.traps[signal] = True
            context.clear_flags()
            assert view.to_mapping() == expected[0]
            assert view.digest() == expected[1]
            assert view.to_mapping()[quantity_key] == quantity
            assert view.to_mapping()["limit_price"] == price
            assert not any(context.flags.values())
            assert type(view).from_mapping(view.to_mapping()).digest() == expected[1]


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("100000", "100000"),
        ("100.00000", "100"),
        ("1200.001200", "1200.0012"),
        ("0.000001000", "0.000001"),
        ("1E+4", "10000"),
        ("-1E+4", "-10000"),
        ("-0.000", "0"),
        ("0E+4", "0"),
    ],
)
def test_fixed_point_canonicalization(raw, expected):
    with localcontext() as context:
        context.prec = 1
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        assert _decimal_text(Decimal(raw)) == expected


@pytest.mark.parametrize("factory", [_order, _parent])
def test_equal_values_have_equal_wire_bytes_and_digest(factory):
    first = factory("123.45000", "1000.00")
    second = factory("123.45", "1E+3")
    with localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = True
        assert first.to_mapping() == second.to_mapping()
        assert first.digest() == second.digest()


def test_independent_thread_decimal_contexts():
    view = _order("1.234567890123456789012345678901", "100.00001")
    barrier = Barrier(2)

    def serialize(precision):
        with localcontext() as context:
            context.prec = precision
            context.traps[Inexact] = True
            barrier.wait(timeout=5)
            return view.to_mapping(), view.digest()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = executor.map(serialize, (2, 70))
    assert first == second


def test_fixed_point_output_bound_and_nonfinite():
    with localcontext() as context:
        context.prec = 1
        context.traps[Inexact] = True
        assert _decimal_text(Decimal("9" * 4096)) == "9" * 4096
        assert _decimal_text(Decimal("1E+4095")) == "1" + "0" * 4095
        assert _decimal_text(Decimal("1E-4094")) == "0." + "0" * 4093 + "1"
        for value in ("1E+4096", "1E-4095", "9" * 4097, "NaN", "Infinity", "-Infinity"):
            with pytest.raises(RiskServiceProtocolError, match="^RISK_DECIMAL_ENCODING_INVALID$"):
                _decimal_text(Decimal(value))


@pytest.mark.parametrize("factory,field,code", [
    (_order, "quantity", "RISK_VIEW_INVALID"),
    (_parent, "total_quantity", "RISK_PARENT_INVALID"),
])
def test_raw_text_is_bounded_before_decimal_construction(factory, field, code):
    # Leading zeroes would collapse on Decimal construction, so post-conversion
    # digit checks alone would not bound the incoming wire representation.
    value = "0" * 4095 + "1"
    assert replace(factory(), **{field: value}).to_mapping()[field] == "1"
    for field_name in (field, "limit_price"):
        with pytest.raises(RiskServiceProtocolError, match=f"^{code}$"):
            replace(factory(), **{field_name: "0" + value})
