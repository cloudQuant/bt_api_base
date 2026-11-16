"""Strict local recovery observation contract."""

from dataclasses import FrozenInstanceError, replace

import pytest

from bt_api_base.market_protocol import MarketInstrumentKey, MarketSubscriptionKey
from bt_api_base.market_recovery_observation import (
    RecoveryCoverageObservation,
    RecoveryObservationMember,
    RecoveryObservationPage,
)


def _member(symbol="IF", generation="g1"):
    return RecoveryObservationMember(
        MarketSubscriptionKey(
            "source", "ent", MarketInstrumentKey("ctp", "x", "sim", "f", symbol, symbol), "tick"
        ),
        generation,
    )


def _observation(**changes):
    fields = {
        "source_epoch": "a" * 32,
        "owner_pid": 1,
        "sequence": 1,
        "episode_id": "b" * 32,
        "state": "RECOVERING",
        "reason": "BEGIN",
        "observed_monotonic_ns": 3,
        "coverage_started_monotonic_ns": 1,
        "coverage_through_monotonic_ns": 2,
        "origin_connection_generation": 1,
        "observed_connection_generation": 2,
        "members": (_member(),),
    }
    fields.update(changes)
    return RecoveryCoverageObservation(**fields)


def test_observations_are_frozen_local_values():
    observation = _observation()
    with pytest.raises(FrozenInstanceError):
        observation.state = "UNKNOWN"
    assert not hasattr(observation, "to_dict")
    assert RecoveryObservationPage("a" * 32, 1, 0, 1, 1, (observation,), False).observations == (
        observation,
    )


@pytest.mark.parametrize(
    "change",
    [
        {"owner_pid": True},
        {"sequence": 0},
        {"sequence": 1 << 63},
        {"source_epoch": "A" * 32},
        {"state": "healthy"},
        {"reason": "arbitrary"},
        {"coverage_through_monotonic_ns": 4},
        {"coverage_started_monotonic_ns": 0},
        {"origin_connection_generation": False},
        {"members": (_member(), _member())},
        {"members": [_member()]},
        {"state": "UNKNOWN"},
        {"episode_id": None},
        {"members": ()},
        {"reason": "COMPLETED"},
        {"state": "RECOVERED", "reason": "WATERMARK"},
        {"state": "FAILED", "reason": "COMPLETED"},
    ],
)
def test_invalid_observations_are_rejected(change):
    with pytest.raises((ValueError, TypeError)):
        _observation(**change)


def test_unknown_has_no_coverage_and_page_detects_missing_prefix():
    unknown = _observation(
        state="UNKNOWN",
        reason="SCOPE_CHANGED",
        coverage_started_monotonic_ns=None,
        coverage_through_monotonic_ns=None,
    )
    assert unknown.state == "UNKNOWN"
    later = replace(unknown, sequence=2)
    page = RecoveryObservationPage("a" * 32, 1, 0, 2, 2, (later,), True)
    assert page.gap
    with pytest.raises(ValueError):
        replace(page, gap=False)
    with pytest.raises(ValueError):
        replace(page, observations=(unknown,))
    with pytest.raises(ValueError):
        replace(page, observations=())


def test_member_validation_and_sorting():
    with pytest.raises(ValueError):
        _member(generation=" x ")
    with pytest.raises(ValueError) as error:
        _member(generation="\ud800")
    assert error.value.__cause__ is None
    with pytest.raises(TypeError):
        RecoveryObservationMember(object(), "g")
    members = sorted((_member("IF"), _member("IH")), key=lambda m: (m.key.stream_id, m.generation))
    with pytest.raises(ValueError):
        _observation(members=tuple(reversed(members)))
