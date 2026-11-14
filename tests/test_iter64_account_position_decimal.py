"""Account position splits must not depend on the ambient Decimal context."""

from decimal import (
    ROUND_05UP,
    ROUND_CEILING,
    ROUND_DOWN,
    ROUND_FLOOR,
    ROUND_HALF_DOWN,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    ROUND_UP,
    Clamped,
    Inexact,
    InvalidOperation,
    Overflow,
    Rounded,
    Subnormal,
    Underflow,
    localcontext,
)

import pytest

from bt_api_base.account_protocol import MAX_DECIMAL_BYTES, AccountPosition, AccountResourceKey
from bt_api_base.market_protocol import MarketInstrumentKey


def position(quantity, today, yesterday, *, side="long"):
    return AccountPosition(
        resource=AccountResourceKey("future", "margin"),
        instrument=MarketInstrumentKey("example", "SHFE", "paper", "future", "rb", "rb"),
        side=side,
        quantity=quantity,
        qty_unit="contracts",
        average_price=None,
        price_currency=None,
        observed_at_utc="2026-11-15T00:00:00Z",
        today_quantity=today,
        yesterday_quantity=yesterday,
    )


@pytest.mark.parametrize(
    "rounding",
    [ROUND_05UP, ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_DOWN,
     ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_UP],
)
@pytest.mark.parametrize("precision", [1, 2, 9])
def test_split_comparison_is_exact_and_leaves_caller_context_unchanged(rounding, precision):
    with localcontext() as context:
        context.prec = precision
        context.rounding = rounding
        context.Emin = -9
        context.Emax = 9
        for signal in (Clamped, Inexact, InvalidOperation, Overflow, Rounded, Subnormal, Underflow):
            context.traps[signal] = True
        context.clear_flags()

        actual = position("1.20", "0.6", "0.6000")
        assert (actual.quantity, actual.today_quantity, actual.yesterday_quantity) == (
            "1.20", "0.6", "0.6000"
        )
        with pytest.raises(ValueError, match=r"^today_quantity \+ yesterday_quantity must equal quantity$"):
            position("1", "0.6", "0.6")

        assert not any(context.flags.values())


def test_bounded_extreme_lengths_are_exact_without_rounding_or_context_flags():
    large = "9" * (MAX_DECIMAL_BYTES - 1)
    tiny = "0." + "0" * (MAX_DECIMAL_BYTES - 3) + "1"
    assert len(tiny) == MAX_DECIMAL_BYTES
    with localcontext() as context:
        context.prec = 1
        context.Emin = -9
        context.Emax = 9
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        context.traps[Underflow] = True
        context.traps[Overflow] = True
        context.clear_flags()

        position("1" + "0" * (MAX_DECIMAL_BYTES - 1), large, "1")
        position(tiny, "0", tiny)
        with pytest.raises(ValueError, match="must equal quantity"):
            position("9" * MAX_DECIMAL_BYTES, "9" * MAX_DECIMAL_BYTES, tiny)
        assert not any(context.flags.values())


@pytest.mark.parametrize("side,quantity,today,yesterday", [
    ("long", "0", "-0", "0.000"),
    ("net", "-0.00", "0", "-0.0"),
    ("short", "3.00", "1.0", "2.000"),
])
def test_zero_sign_and_decimal_lexemes_retain_valid_semantics(side, quantity, today, yesterday):
    actual = position(quantity, today, yesterday, side=side)
    assert AccountPosition.from_dict(actual.to_dict()) == actual


@pytest.mark.parametrize("field,value", [
    ("quantity", "1e0"),
    ("today", "NaN"),
    ("yesterday", "-0.01"),
    ("today", "0." + "0" * MAX_DECIMAL_BYTES),
    ("today", 1),
])
def test_existing_decimal_input_contract_remains_enforced(field, value):
    values = {"quantity": "1", "today": "0", "yesterday": "1"}
    values[field] = value
    with pytest.raises((TypeError, ValueError)):
        position(**values)


def test_partial_split_retains_existing_optional_behavior():
    assert position("2", "1", None).yesterday_quantity is None
    assert position("2", None, "1").today_quantity is None
