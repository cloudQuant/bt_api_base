"""Pure contract tests: no Gateway, Risk service, or persisted state."""

from dataclasses import replace

import pytest

from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.risk_service_protocol import (
    CONTROL_SCOPE_SCHEMA,
    ControlScopeV2,
    KillSwitchCommand,
    RiskServiceProtocolError,
)


def instrument():
    return MarketInstrumentKey("ctp", "SHFE", "sim", "future", "rb2701", "rb2701")


def test_account_and_full_instrument_canonical_round_trip():
    account = ControlScopeV2("account-1", "account", 2)
    scope = ControlScopeV2("account-1", "instrument", 2, instrument())
    assert account.to_mapping() == {
        "schema": CONTROL_SCOPE_SCHEMA,
        "schema_version": 2,
        "kind": "account",
        "account_scope": "account-1",
    }
    assert account.canonical_bytes() == (
        b'{"account_scope":"account-1","kind":"account",'
        b'"schema":"bt_api.control_scope","schema_version":2}'
    )
    assert scope.canonical_bytes() == (
        b'{"account_scope":"account-1","instrument":{"environment":"sim",'
        b'"instrument_id":"rb2701","native_symbol":"rb2701","product_type":"future",'
        b'"provider":"ctp","venue":"SHFE"},"kind":"instrument",'
        b'"schema":"bt_api.control_scope","schema_version":2}'
    )
    for original in (account, scope):
        decoded = ControlScopeV2.from_mapping(original.to_mapping())
        assert decoded == original
        assert decoded.canonical_bytes() == original.canonical_bytes()
        assert ControlScopeV2.from_canonical_bytes(original.canonical_bytes()) == original


@pytest.mark.parametrize("field", sorted(MarketInstrumentKey._FIELDS))
def test_each_instrument_dimension_changes_canonical_bytes(field):
    key = instrument()
    original = ControlScopeV2("account-1", "instrument", 2, key)
    changed = ControlScopeV2("account-1", "instrument", 2, replace(key, **{field: "other"}))
    assert changed.canonical_bytes() != original.canonical_bytes()


def test_account_and_unicode_are_exact_and_distinct():
    scope = ControlScopeV2("账户-1", "instrument", 2, instrument())
    assert "账户-1".encode() in scope.canonical_bytes()
    assert scope.canonical_bytes() != replace(scope, account_scope="账户-2").canonical_bytes()
    assert ControlScopeV2.from_mapping(scope.to_mapping()) == scope


def test_maximum_escaped_field_lengths_round_trip():
    key = MarketInstrumentKey(*(['\\' * 256] * 6))
    scope = ControlScopeV2('\\' * 256, "instrument", 2, key)
    assert ControlScopeV2.from_canonical_bytes(scope.canonical_bytes()) == scope


@pytest.mark.parametrize("field", ["account_scope", *sorted(MarketInstrumentKey._FIELDS)])
def test_non_ascii_reference_byte_limit(field):
    scope = ControlScopeV2("account-1", "instrument", 2, instrument())
    mapping = scope.to_mapping()
    target = mapping if field == "account_scope" else mapping["instrument"]
    target[field] = "界" * 85 + "a"  # 256 UTF-8 bytes
    assert ControlScopeV2.from_canonical_bytes(
        ControlScopeV2.from_mapping(mapping).canonical_bytes()
    ).to_mapping() == mapping
    target[field] += "a"  # 257 UTF-8 bytes
    with pytest.raises(RiskServiceProtocolError):
        ControlScopeV2.from_mapping(mapping)


@pytest.mark.parametrize("field", ["account_scope", *sorted(MarketInstrumentKey._FIELDS)])
def test_rejects_surrogates_in_scope_references(field):
    mapping = ControlScopeV2("account-1", "instrument", 2, instrument()).to_mapping()
    target = mapping if field == "account_scope" else mapping["instrument"]
    target[field] = "bad\ud800"
    with pytest.raises(RiskServiceProtocolError):
        ControlScopeV2.from_mapping(mapping)


def test_combining_characters_are_not_normalized():
    composed = ControlScopeV2("caf\u00e9", "account", 2)
    decomposed = ControlScopeV2("cafe\u0301", "account", 2)
    assert composed.canonical_bytes() != decomposed.canonical_bytes()
    for scope in (composed, decomposed):
        assert ControlScopeV2.from_canonical_bytes(scope.canonical_bytes()) == scope


@pytest.mark.parametrize("field", sorted(MarketInstrumentKey._FIELDS))
def test_instrument_mapping_rejects_str_subclass_keys(field):
    class TextKey(str):
        pass

    mapping = ControlScopeV2("account-1", "instrument", 2, instrument()).to_mapping()
    mapping["instrument"] = {
        TextKey(key) if key == field else key: value
        for key, value in mapping["instrument"].items()
    }
    with pytest.raises(RiskServiceProtocolError):
        ControlScopeV2.from_mapping(mapping)


@pytest.mark.parametrize("field", sorted(MarketInstrumentKey._FIELDS))
def test_complete_instrument_mapping_rejects_each_duplicate_key(field):
    scope = ControlScopeV2("account-1", "instrument", 2, instrument())
    raw = scope.canonical_bytes()
    key = ('"' + field + '":').encode("ascii")
    assert raw.count(key) == 1
    duplicated = raw.replace(key, key + '"duplicate",'.encode("ascii") + key, 1)
    with pytest.raises(RiskServiceProtocolError):
        ControlScopeV2.from_canonical_bytes(duplicated)


def test_canonical_decoder_rejects_escaped_surrogate():
    scope = ControlScopeV2("account-1", "account", 2)
    raw = scope.canonical_bytes().replace(b"account-1", b"bad\\ud800")
    with pytest.raises(RiskServiceProtocolError):
        ControlScopeV2.from_canonical_bytes(raw)


@pytest.mark.parametrize("version", [None, True, 1, 3, "2"])
def test_rejects_unrecognized_version(version):
    with pytest.raises(RiskServiceProtocolError):
        ControlScopeV2("account-1", "account", version)
    mapping = ControlScopeV2("account-1", "account", 2).to_mapping()
    mapping["schema_version"] = version
    with pytest.raises(RiskServiceProtocolError):
        ControlScopeV2.from_mapping(mapping)


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value.pop("account_scope"),
        lambda value: value.update(extra="x"),
        lambda value: value.update(schema="other"),
        lambda value: value.update(kind="strategy"),
        lambda value: value.update(kind="account"),
        lambda value: value.update(instrument="SHFE:rb2701"),
        lambda value: value["instrument"].pop("provider"),
        lambda value: value["instrument"].update(extra="x"),
        lambda value: value["instrument"].update(native_symbol=" "),
    ],
)
def test_rejects_ambiguous_or_invalid_instrument_mapping(change):
    value = ControlScopeV2("account-1", "instrument", 2, instrument()).to_mapping()
    change(value)
    with pytest.raises(RiskServiceProtocolError):
        ControlScopeV2.from_mapping(value)


def test_rejects_account_instrument_and_legacy_shape_without_conversion():
    with pytest.raises(RiskServiceProtocolError):
        ControlScopeV2("account-1", "account", 2, instrument())
    with pytest.raises(RiskServiceProtocolError):
        ControlScopeV2("account-1", "instrument", 2)
    legacy = KillSwitchCommand("cmd", "STOP_NEW", "instrument", "SHFE.rb2701", "r", "risk")
    with pytest.raises(RiskServiceProtocolError):
        ControlScopeV2.from_mapping(legacy.to_mapping())


@pytest.mark.parametrize(
    "raw",
    [
        b'{"account_scope":"a","account_scope":"b","kind":"account",'
        b'"schema":"bt_api.control_scope","schema_version":2}',
        b'{"account_scope":"a", "kind":"account",'
        b'"schema":"bt_api.control_scope","schema_version":2}',
        b'{"account_scope":"a","instrument":{"provider":"a","provider":"b"},'
        b'"kind":"instrument","schema":"bt_api.control_scope","schema_version":2}',
        b"\xff",
        b"x" * 4097,
        '{"schema":"bt_api.control_scope"}',
    ],
)
def test_canonical_decoder_rejects_duplicates_and_noncanonical_input(raw):
    with pytest.raises(RiskServiceProtocolError):
        ControlScopeV2.from_canonical_bytes(raw)
