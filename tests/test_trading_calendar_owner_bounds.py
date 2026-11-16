from dataclasses import FrozenInstanceError, replace

import pytest

from bt_api_base.trading_calendar_owner_bounds import SimulationCalendarOwnerBounds


def test_frozen_and_strict_status_payload():
    value = SimulationCalendarOwnerBounds(
        "COMPLETE", "COMPILED_SCOPE_COMPLETE", "v1", "X", "future", "p", "p1", 9, 0
    )
    with pytest.raises(FrozenInstanceError):
        value.max_advance_days = 1
    for changes in (
        {"max_advance_days": True},
        {"max_spill_days": -1},
        {"sources_verified": True},
        {"reason": "OTHER"},
        {"status": "UNKNOWN"},
        {"contract": ""},
    ):
        with pytest.raises(ValueError):
            replace(value, **changes)
    unknown = replace(
        value,
        status="UNKNOWN",
        reason="NO_COMPILED_ROWS",
        max_advance_days=None,
        max_spill_days=None,
    )
    with pytest.raises(ValueError):
        replace(unknown, max_spill_days=0)
