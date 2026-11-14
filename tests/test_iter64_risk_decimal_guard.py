"""Synthetic v1 decimal serialization checks; no account or provider evidence."""

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


def order(quantity="2.50", price="3500.0"):
    return RiskOrderView(
        "acct-hash",
        "CTP___FUTURE",
        "11111111-2222-3333-4444-555555555555",
        "strategy",
        "11111111-2222-3333-4444-555555555555:7",
        INSTRUMENT,
        "BUY",
        "OPEN",
        "NET",
        Decimal(quantity),
        "lots",
        "LIMIT",
        Decimal(price),
        "DAY",
        "20261112",
        "s-1",
    )


def parent(quantity="5.00", price="3500.0"):
    return RiskParentView(
        "acct-hash",
        "CTP___FUTURE",
        "strategy-a",
        "parent-1",
        INSTRUMENT,
        "SELL",
        "CLOSE_TODAY",
        "LONG",
        Decimal(quantity),
        "lots",
        Decimal(price),
        "20261111",
        "20261112",
    )


def test_v1_golden_and_roundtrip():
    for view, field, text, digest in (
        (
            order(),
            "quantity",
            "2.5",
            "9c58fc72c2aa9cf46676e733ce0afa3f4264058e0cd8d94ae5a03d5a16f54425",
        ),
        (
            parent(),
            "total_quantity",
            "5",
            "691055e68efff27963235df9e2d882250382ce3344da74f54ad66b513c2cee15",
        ),
    ):
        mapping = view.to_mapping()
        assert mapping[field] == text and mapping["limit_price"] == "3500"
        assert view.digest() == digest
        assert type(view).from_mapping(mapping) == view
        assert type(view).from_mapping(mapping).digest() == digest


@pytest.mark.parametrize(
    "value, expected",
    [
        ("0.001200", "0.0012"),
        ("-12.3400", "-12.34"),
        ("-0", "0"),
        ("12.00", "12"),
        ("1E+3", "1000"),
    ],
)
def test_safe_text_matches_original_encoder(value, expected):
    number = Decimal(value)
    old = format(number.normalize(), "f")
    assert _decimal_text(number) == ("0" if old == "-0" else old) == expected


@pytest.mark.parametrize("factory,field", [(order, "quantity"), (parent, "total_quantity")])
def test_views_reject_negative_values(factory, field):
    with pytest.raises(RiskServiceProtocolError):
        replace(factory(), **{field: Decimal("-1")})
    with pytest.raises(RiskServiceProtocolError):
        replace(factory(), limit_price=Decimal("-1"))


@pytest.mark.parametrize("factory", [order, parent])
def test_distinct_precise_values_do_not_collide(factory):
    first = "1.23456789012345678901234567891"
    second = "1.23456789012345678901234567892"
    with localcontext() as context:
        context.prec = 28
        assert format(Decimal(first).normalize(), "f") == format(Decimal(second).normalize(), "f")
        a, b = factory(first), factory(second)
        assert a.digest() != b.digest()
        assert type(a).from_mapping(a.to_mapping()) == a
        assert factory(price=first).to_mapping()["limit_price"] == first
        digests = (a.digest(), b.digest())
    with localcontext() as context:
        context.prec = 40
        a, b = factory(first), factory(second)
        assert a.digest() != b.digest()
        assert type(a).from_mapping(a.to_mapping()) == a
        assert (a.digest(), b.digest()) == digests


@pytest.mark.parametrize("trap", [False, True])
def test_context_rounding_and_traps_are_finite(trap):
    with localcontext() as context:
        context.prec = 3
        context.traps[Inexact] = trap
        for view in (order("1.234"), parent(price="1.234")):
            mapping = view.to_mapping()
            assert "1.234" in (mapping.get("quantity"), mapping["limit_price"])
    with localcontext() as context:
        context.prec = 3
        context.traps[Rounded] = True
        assert order("1.2300").to_mapping()["quantity"] == "1.23"


@pytest.mark.parametrize("trap", [False, True])
@pytest.mark.parametrize("value,signal", [("1E+3", Overflow), ("1E-5", Underflow)])
def test_context_overflow_and_underflow(trap, value, signal):
    with localcontext() as context:
        context.prec = 2
        context.Emax = 2
        context.Emin = -2
        context.traps[signal] = trap
        assert parent(value).to_mapping()["total_quantity"] == {"1E+3": "1000", "1E-5": "0.00001"}[value]


@pytest.mark.parametrize(
    "value", ["1E+999999999", "1E-999999999", "1E+4096", "1E-4096", "1" * 4097]
)
def test_oversized_inputs_are_rejected_before_fixed_formatting(value):
    for view in (order(value), parent(price=value)):
        with pytest.raises(RiskServiceProtocolError, match="^RISK_DECIMAL_ENCODING_INVALID$"):
            view.to_mapping()


def test_size_bound_and_nonfinite_defense():
    assert len(_decimal_text(Decimal("1E+4095"))) == 4096
    assert len(_decimal_text(Decimal("1E-4094"))) == 4096
    for value in (Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")):
        with pytest.raises(RiskServiceProtocolError, match="^RISK_DECIMAL_ENCODING_INVALID$"):
            _decimal_text(value)


def test_serialization_is_independent_of_each_threads_context():
    view = order("1.23456789")
    barrier = Barrier(2)

    def serialize(precision):
        with localcontext() as context:
            context.prec = precision
            barrier.wait(timeout=5)
            try:
                return view.to_mapping()["quantity"]
            except RiskServiceProtocolError as exc:
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(serialize, (4, 12)))
    assert results == ["1.23456789", "1.23456789"]
