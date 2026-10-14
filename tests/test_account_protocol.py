"""Focused tests for the neutral account snapshot protocol."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from bt_api_base.account_protocol import (
    MAX_ACCOUNT_OBSERVATION_BYTES,
    AccountBalance,
    AccountKey,
    AccountObservation,
    AccountPosition,
    AccountResourceKey,
    AccountValuation,
)
from bt_api_base.market_protocol import MarketInstrumentKey

_OLD_UTC = "2020-01-02T03:04:05.123Z"
_START_UTC = "2026-10-13T04:05:06Z"
_COMPLETE_UTC = "2026-10-13T04:05:08.500Z"


def _account(**updates: object) -> AccountKey:
    values: dict[str, object] = {
        "provider": "alpha",
        "venue": "alpha-futures",
        "environment": "paper",
        "account_id": "account-17",
        "subaccount_id": "sub-2",
    }
    values.update(updates)
    return AccountKey(**values)  # type: ignore[arg-type]


def _resource(**updates: object) -> AccountResourceKey:
    values: dict[str, object] = {"product_type": "linear-perpetual", "margin_pool": "usd-m"}
    values.update(updates)
    return AccountResourceKey(**values)  # type: ignore[arg-type]


def _instrument(account: AccountKey | None = None, **updates: str) -> MarketInstrumentKey:
    key = account or _account()
    values = {
        "provider": key.provider,
        "venue": key.venue,
        "environment": key.environment,
        "product_type": "linear-perpetual",
        "instrument_id": "BTC-USD-PERP",
        "native_symbol": "BTCUSD_PERP",
    }
    values.update(updates)
    return MarketInstrumentKey(**values)


def _balance(
    resource: AccountResourceKey | None = None,
    *,
    currency: str = "USD",
    observed_at_utc: str = _OLD_UTC,
    **updates: object,
) -> AccountBalance:
    values: dict[str, object] = {
        "resource": resource or _resource(),
        "currency": currency,
        "total": "100.00",
        "available": "75.00",
        "locked": "25.00",
        "observed_at_utc": observed_at_utc,
    }
    values.update(updates)
    return AccountBalance(**values)  # type: ignore[arg-type]


def _position(
    account: AccountKey | None = None,
    resource: AccountResourceKey | None = None,
    *,
    side: str = "net",
    quantity: str = "-2.500",
    instrument: MarketInstrumentKey | None = None,
    observed_at_utc: str = _OLD_UTC,
    **updates: object,
) -> AccountPosition:
    values: dict[str, object] = {
        "resource": resource or _resource(),
        "instrument": instrument or _instrument(account),
        "side": side,
        "quantity": quantity,
        "qty_unit": "contracts",
        "average_price": "65000.1250",
        "price_currency": "USD",
        "observed_at_utc": observed_at_utc,
    }
    values.update(updates)
    return AccountPosition(**values)  # type: ignore[arg-type]


def _observation(**updates: object) -> AccountObservation:
    resource = _resource()
    values: dict[str, object] = {
        "account_key": _account(),
        "observation_id": "provider-read-42",
        "coverage": (resource,),
        "balances": (_balance(resource),),
        "positions": (_position(resource=resource),),
        "valuation": AccountValuation(
            currency="USD",
            available_cash="75.00",
            equity="125.00",
            observed_at_utc=_OLD_UTC,
        ),
        "started_at_utc": _START_UTC,
        "completed_at_utc": _COMPLETE_UTC,
        "consistency": "multi_query",
        "balances_complete": True,
        "positions_complete": True,
    }
    values.update(updates)
    return AccountObservation(**values)  # type: ignore[arg-type]


def test_account_key_is_immutable_hashable_and_has_stable_full_owner_digest() -> None:
    key = _account()
    restored = AccountKey.from_dict(json.loads(json.dumps(key.to_dict())))

    assert restored == key
    assert hash(restored) == hash(key)
    assert restored.account_key_id == key.account_key_id
    assert key.account_key_id.startswith("account-")
    canonical = json.dumps(
        key.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    assert key.account_key_id == "account-" + hashlib.sha256(canonical).hexdigest()
    assert (
        len(
            {
                key.account_key_id,
                replace(key, provider="beta").account_key_id,
                replace(key, venue="beta-futures").account_key_id,
                replace(key, environment="live").account_key_id,
                replace(key, account_id="account-18").account_key_id,
                replace(key, subaccount_id="sub-3").account_key_id,
                replace(key, subaccount_id=None).account_key_id,
            }
        )
        == 7
    )

    with pytest.raises(FrozenInstanceError):
        key.account_id = "changed"  # type: ignore[misc]


def test_full_observation_round_trips_json_and_preserves_provider_lexemes() -> None:
    observation = _observation()
    encoded = json.dumps(observation.to_dict(), ensure_ascii=False, allow_nan=False)
    restored = AccountObservation.from_dict(json.loads(encoded))

    assert restored == observation
    assert restored.positions[0].quantity == "-2.500"
    assert restored.positions[0].average_price == "65000.1250"
    assert restored.balances[0].total == "100.00"
    assert restored.valuation is not None
    assert restored.valuation.currency == "USD"
    assert hash(restored) == hash(observation)
    with pytest.raises(FrozenInstanceError):
        restored.balances_complete = False  # type: ignore[misc]


def test_account_owner_digest_and_resource_dimensions_are_not_strategy_scopes() -> None:
    key = _account()
    same_owner = _account()
    other_margin_pool = _resource(margin_pool="coin-m")
    other_product = _resource(product_type="spot", margin_pool="spot-wallet")

    assert key == same_owner
    assert key.account_key_id == same_owner.account_key_id
    assert other_margin_pool != _resource()
    assert other_product != _resource()
    assert set(key.to_dict()) == {
        "provider",
        "venue",
        "environment",
        "account_id",
        "subaccount_id",
    }
    assert "strategy" not in key.to_dict()
    assert AccountResourceKey.from_dict(other_product.to_dict()) == other_product


@pytest.mark.parametrize(
    "field,value",
    [
        ("provider", ""),
        ("venue", " venue"),
        ("environment", "paper\nprod"),
        ("account_id", "x" * 257),
        ("account_id", "bad\ud800value"),
        ("subaccount_id", "x" * 129 + "雪" * 43),
    ],
)
def test_account_key_references_are_bounded_printable_utf8(field: str, value: str) -> None:
    with pytest.raises((TypeError, ValueError)):
        _account(**{field: value})


@pytest.mark.parametrize(
    "value",
    [
        1,
        1.25,
        True,
        float("nan"),
        float("inf"),
        "NaN",
        "Infinity",
        "1e9",
        "+1",
        "01",
        ".5",
        "1.",
        "1" * 129,
    ],
)
def test_decimal_fields_reject_non_strings_non_finite_and_unbounded_forms(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        _balance(total=value)


def test_decimal_signs_are_preserved_and_only_directional_position_sides_restrict_sign() -> None:
    assert _balance(total="-0.0001").total == "-0.0001"
    assert _position(side="net", quantity="-2.50").quantity == "-2.50"
    assert _position(side="long", quantity="0.000").quantity == "0.000"
    assert _position(side="short", quantity="2").quantity == "2"

    with pytest.raises(ValueError):
        _position(side="long", quantity="-0.01")
    with pytest.raises(ValueError):
        _position(side="short", quantity="-1")
    with pytest.raises(ValueError):
        replace(_position(side="net", quantity="1"), side="both")


def test_timestamp_requires_explicit_utc_but_historical_provider_facts_remain_valid() -> None:
    old = _OLD_UTC
    observation = _observation(
        balances=(_balance(observed_at_utc=old),),
        positions=(_position(observed_at_utc=old),),
        valuation=AccountValuation(
            currency="USD", available_cash=None, equity=None, observed_at_utc=old
        ),
    )
    assert observation.balances[0].observed_at_utc == old
    assert observation.started_at_utc > observation.balances[0].observed_at_utc

    for invalid in (
        "2026-10-13T04:05:06",
        "2026-10-13T04:05:06+00:00",
        "2026-10-13T06:05:06+02:00",
        "2026-02-30T04:05:06Z",
    ):
        with pytest.raises(ValueError):
            replace(observation, completed_at_utc=invalid)


def test_observation_requires_ordered_times_and_row_times_no_later_than_completion() -> None:
    with pytest.raises(ValueError):
        _observation(started_at_utc=_COMPLETE_UTC, completed_at_utc=_START_UTC)
    with pytest.raises(ValueError):
        _observation(balances=(_balance(observed_at_utc="2026-10-13T04:05:09Z"),))
    with pytest.raises(ValueError):
        _observation(
            valuation=AccountValuation(
                currency="USD",
                available_cash="1",
                equity="1",
                observed_at_utc="2026-10-13T04:05:09Z",
            )
        )


def test_observation_coverage_and_row_identity_are_unique_and_in_scope() -> None:
    resource = _resource()
    other_resource = _resource(margin_pool="coin-m")
    balance = _balance(resource)
    position = _position(resource=resource)

    with pytest.raises(ValueError):
        _observation(coverage=(resource, resource))
    with pytest.raises(ValueError):
        _observation(coverage=())
    with pytest.raises(ValueError):
        _observation(balances=(balance, balance))
    with pytest.raises(ValueError):
        _observation(positions=(position, position))
    with pytest.raises(ValueError):
        _observation(coverage=(other_resource,))
    with pytest.raises(ValueError):
        _observation(positions=(replace(position, resource=other_resource),))


@pytest.mark.parametrize(
    "instrument",
    [
        _instrument(_account(), provider="beta"),
        _instrument(_account(), venue="beta-futures"),
        _instrument(_account(), environment="live"),
        _instrument(_account(), product_type="spot"),
    ],
)
def test_position_instrument_must_match_account_and_resource(
    instrument: MarketInstrumentKey,
) -> None:
    with pytest.raises(ValueError):
        _observation(positions=(_position(instrument=instrument),))


def test_exact_dict_shapes_reject_missing_extra_and_wrong_nested_fields() -> None:
    observation = _observation().to_dict()

    missing = dict(observation)
    del missing["coverage"]
    with pytest.raises(ValueError):
        AccountObservation.from_dict(missing)

    extra = {**observation, "session_generation": "worker-owned"}
    with pytest.raises(ValueError):
        AccountObservation.from_dict(extra)

    wrong_nested = json.loads(json.dumps(observation))
    wrong_nested["coverage"][0]["strategy_id"] = "strategy-1"
    with pytest.raises(ValueError):
        AccountObservation.from_dict(wrong_nested)

    with pytest.raises(TypeError):
        AccountKey.from_dict({1: "not a string field"})  # type: ignore[dict-item]


def test_completeness_is_explicit_and_requires_real_booleans() -> None:
    incomplete = _observation(balances_complete=False, positions_complete=False)
    assert not incomplete.balances_complete
    assert not incomplete.positions_complete
    with pytest.raises(TypeError):
        replace(incomplete, balances_complete=1)
    with pytest.raises(ValueError):
        replace(incomplete, consistency="eventual")


def test_coverage_and_row_counts_are_bounded() -> None:
    resources = tuple(_resource(product_type=f"product-{index}") for index in range(2049))
    with pytest.raises(ValueError):
        _observation(coverage=resources)


def test_serialized_observation_is_bounded_to_512_kib() -> None:
    resources = tuple(
        AccountResourceKey(product_type=f"product-{index}", margin_pool="m" * 256)
        for index in range(2048)
    )
    with pytest.raises(ValueError, match="byte limit"):
        _observation(coverage=resources, balances=(), positions=(), valuation=None)
    assert MAX_ACCOUNT_OBSERVATION_BYTES == 512 * 1024


def test_import_has_no_gateway_transport_or_zmq_dependency() -> None:
    source_root = Path(__file__).parents[1] / "src"
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(source_root), env.get("PYTHONPATH", "")]).rstrip(
        os.pathsep
    )
    script = """
import importlib
import json
import sys

before = set(sys.modules)
importlib.import_module('bt_api_base.account_protocol')
added = set(sys.modules) - before
forbidden = sorted(
    name for name in added
    if name.startswith(('bt_api_gateway', 'bt_api_transport', 'zmq'))
)
print(json.dumps({'forbidden_modules': forbidden}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert json.loads(result.stdout)["forbidden_modules"] == []
