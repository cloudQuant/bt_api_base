"""Isolated structural contracts for iteration 65 parent and child claims."""

from collections.abc import Mapping
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal, localcontext

import pytest

from bt_api_base.execution_parent_protocol import (
    ExecutionChildAttribution,
    ExecutionParentProtocolError,
    LimitParentTerms,
)
from bt_api_base.market_protocol import MarketInstrumentKey

INSTRUMENT = MarketInstrumentKey("ctp", "SHFE", "simnow", "future", "rb2701", "rb2701")


def parent(**changes):
    values = {
        "account_scope": "account",
        "strategy_scope": "strategy",
        "parent_ref": "parent",
        "instrument": INSTRUMENT,
        "side": "buy",
        "offset": "open",
        "quantity_unit": "lots",
        "quantity": Decimal("2.500"),
        "limit_price": Decimal("3500.00"),
        "order_type": "limit",
    }
    values.update(changes)
    return LimitParentTerms(**values)


def child(**changes):
    values = {
        "account_scope": "account",
        "strategy_scope": "strategy",
        "parent_ref": "parent",
        "child_id": "child",
        "request_key": "child",
    }
    values.update(changes)
    return ExecutionChildAttribution(**values)


def assert_invalid(call, code):
    with pytest.raises(ExecutionParentProtocolError) as error:
        call()
    assert error.value.code == code
    assert str(error.value) == code
    assert error.value.__cause__ is None


def test_parent_roundtrip_is_exact_immutable_and_detached():
    value = parent()
    mapping = value.to_mapping()
    assert mapping["quantity"] == "2.500"
    assert mapping["limit_price"] == "3500.00"
    assert LimitParentTerms.from_mapping(mapping) == value
    assert LimitParentTerms.from_mapping(mapping).to_mapping() == mapping
    mapping["instrument"]["native_symbol"] = "other"
    assert value.instrument == INSTRUMENT
    with pytest.raises(FrozenInstanceError):
        value.parent_ref = "other"
    with pytest.raises(FrozenInstanceError):
        value.instrument.native_symbol = "other"


def test_long_decimals_are_exact_under_low_precision_context():
    number = "1234567890" * 30 + "." + "9876543210" * 20
    terms = parent(quantity=Decimal(number), limit_price=Decimal("0." + "0" * 180 + "123456789"))
    with localcontext() as context:
        context.prec = 2
        wire = terms.to_mapping()
        restored = LimitParentTerms.from_mapping(wire)
        assert wire["quantity"] == number
        assert restored.to_mapping() == wire
        assert restored.quantity.as_tuple() == terms.quantity.as_tuple()
        assert restored.limit_price.as_tuple() == terms.limit_price.as_tuple()


@pytest.mark.parametrize("field", ["account_scope", "strategy_scope", "parent_ref"])
@pytest.mark.parametrize("bad", [None, "", " ", " secret ", True, 1, ["a", "b"], {"a": "b"}])
def test_parent_rejects_bad_scope_references(field, bad):
    assert_invalid(lambda: parent(**{field: bad}), "INVALID_PARENT_TERMS")


@pytest.mark.parametrize("field", ["quantity", "limit_price"])
@pytest.mark.parametrize(
    "bad",
    [
        None,
        True,
        1,
        1.0,
        "2",
        Decimal("0"),
        Decimal("-1"),
        Decimal("NaN"),
        Decimal("sNaN"),
        Decimal("Infinity"),
    ],
)
def test_parent_constructor_requires_positive_finite_decimal(field, bad):
    assert_invalid(lambda: parent(**{field: bad}), "INVALID_PARENT_TERMS")


@pytest.mark.parametrize("field", ["quantity", "limit_price"])
@pytest.mark.parametrize(
    "bad",
    [
        None,
        True,
        1,
        1.0,
        Decimal("2"),
        "",
        " 1",
        "1 ",
        "NaN",
        "Infinity",
        "0",
        "-1",
        "+1",
        "1e2",
        "01",
        ".1",
        "1.",
    ],
)
def test_parent_wire_requires_strict_positive_decimal_strings(field, bad):
    wire = parent().to_mapping()
    wire[field] = bad
    assert_invalid(lambda: LimitParentTerms.from_mapping(wire), "INVALID_PARENT_TERMS")


@pytest.mark.parametrize(
    "field,bad",
    [
        ("side", "BUY"),
        ("side", []),
        ("offset", "OPEN"),
        ("offset", None),
        ("quantity_unit", "unknown"),
        ("quantity_unit", True),
        ("order_type", "market"),
        ("order_type", "LIMIT"),
        ("order_type", None),
        ("instrument", None),
        ("instrument", {}),
        ("schema_version", True),
        ("schema_version", 2),
        ("schema_version", 1.0),
    ],
)
def test_parent_rejects_unsupported_types_and_values(field, bad):
    assert_invalid(lambda: parent(**{field: bad}), "INVALID_PARENT_TERMS")


@pytest.mark.parametrize("side", ["buy", "sell"])
@pytest.mark.parametrize("offset", ["open", "close", "close_today", "close_yesterday"])
@pytest.mark.parametrize("unit", ["base", "contracts", "lots", "native"])
def test_parent_supported_vocabulary(side, offset, unit):
    assert parent(side=side, offset=offset, quantity_unit=unit).to_mapping()["offset"] == offset


class DuplicateKeys(Mapping):
    def __init__(self, data):
        self.data = data

    def __getitem__(self, key):
        return self.data[key]

    def __iter__(self):
        yield from self.data
        yield next(iter(self.data))

    def __len__(self):
        return len(self.data) + 1


@pytest.mark.parametrize(
    "kind", ["missing", "extra", "duplicate", "instrument_extra", "instrument_missing"]
)
def test_parent_rejects_nonexact_mapping(kind):
    wire = parent().to_mapping()
    if kind == "missing":
        del wire["parent_ref"]
    elif kind == "extra":
        wire["strategies"] = ["secret"]
    elif kind == "duplicate":
        wire = DuplicateKeys(wire)
    elif kind == "instrument_extra":
        wire["instrument"]["secret"] = "secret"
    else:
        del wire["instrument"]["venue"]
    assert_invalid(lambda: LimitParentTerms.from_mapping(wire), "INVALID_PARENT_TERMS")


def test_child_roundtrip_and_immutable():
    value = child()
    assert ExecutionChildAttribution.from_mapping(value.to_mapping()) == value
    assert (
        ExecutionChildAttribution.from_mapping(value.to_mapping()).to_mapping()
        == value.to_mapping()
    )
    with pytest.raises(FrozenInstanceError):
        value.parent_ref = "other"


@pytest.mark.parametrize(
    "field", ["account_scope", "strategy_scope", "parent_ref", "child_id", "request_key"]
)
@pytest.mark.parametrize("bad", [None, "", " ", " secret ", True, 1, ["a", "b"], {"a": "b"}])
def test_child_rejects_invalid_references(field, bad):
    assert_invalid(lambda: child(**{field: bad}), "INVALID_CHILD_ATTRIBUTION")


@pytest.mark.parametrize(
    "kind", ["missing", "extra", "duplicate", "unequal", "bool_version", "other_version"]
)
def test_child_rejects_invalid_mapping(kind):
    wire = child().to_mapping()
    if kind == "missing":
        del wire["parent_ref"]
    elif kind == "extra":
        wire["parents"] = ["secret"]
    elif kind == "duplicate":
        wire = DuplicateKeys(wire)
    elif kind == "unequal":
        wire["request_key"] = "secret"
    elif kind == "bool_version":
        wire["schema_version"] = True
    else:
        wire["schema_version"] = 2
    assert_invalid(
        lambda: ExecutionChildAttribution.from_mapping(wire), "INVALID_CHILD_ATTRIBUTION"
    )


def test_child_rejects_unequal_direct_construction():
    assert_invalid(lambda: replace(child(), request_key="secret"), "INVALID_CHILD_ATTRIBUTION")


def test_nested_duplicate_instrument_key_is_rejected():
    wire = parent().to_mapping()
    wire["instrument"] = DuplicateKeys(wire["instrument"])
    assert_invalid(lambda: LimitParentTerms.from_mapping(wire), "INVALID_PARENT_TERMS")


@pytest.mark.parametrize("bad", [None, [], "secret", 1, True])
def test_top_level_requires_mapping(bad):
    assert_invalid(lambda: LimitParentTerms.from_mapping(bad), "INVALID_PARENT_TERMS")
    assert_invalid(lambda: ExecutionChildAttribution.from_mapping(bad), "INVALID_CHILD_ATTRIBUTION")


def test_validation_does_not_expose_instrument_or_numeric_input():
    wire = parent().to_mapping()
    wire["instrument"]["native_symbol"] = "secret\ud800"
    assert_invalid(lambda: LimitParentTerms.from_mapping(wire), "INVALID_PARENT_TERMS")
    wire = parent().to_mapping()
    wire["quantity"] = "secret"
    assert_invalid(lambda: LimitParentTerms.from_mapping(wire), "INVALID_PARENT_TERMS")


@pytest.mark.parametrize("field", ["quantity", "limit_price"])
@pytest.mark.parametrize("number", [Decimal("1e1000000000"), Decimal("1e-1000000000")])
def test_huge_decimal_exponents_rejected_before_serialization(field, number):
    assert_invalid(lambda: parent(**{field: number}), "INVALID_PARENT_TERMS")


def test_decimal_text_bound_is_exact_and_independent_of_downstream_authority():
    # This structural bound permits far more than authority's 42+42 digit bound.
    wire = parent().to_mapping()
    wire["quantity"] = "1" * 4096
    assert LimitParentTerms.from_mapping(wire).to_mapping() == wire
    wire["quantity"] += "1"
    assert_invalid(lambda: LimitParentTerms.from_mapping(wire), "INVALID_PARENT_TERMS")
