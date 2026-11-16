"""Local simulation snapshot observations, without source or trading authority."""

from __future__ import annotations

import re
from dataclasses import dataclass

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_REASONS = {
    "COMPLETE": "COMPILED_SCOPE_COMPLETE",
    "UNKNOWN": ("NO_COMPILED_ROWS", "RULE_COVERAGE_INCOMPLETE"),
    "OUT_OF_SCOPE": "IDENTITY_NOT_IN_SNAPSHOT",
}


@dataclass(frozen=True)
class SimulationCalendarOwnerBounds:
    """Bounds over existing compiled rows only, not a coverage assertion."""

    status: str
    reason: str
    calendar_ref: str
    venue: str
    kind: str
    product: str
    contract: str
    max_advance_days: int | None
    max_spill_days: int | None
    sources_verified: bool = False

    def __post_init__(self) -> None:
        if (
            any(
                type(v) is not str or _ID.fullmatch(v) is None
                for v in (self.calendar_ref, self.venue, self.product, self.contract)
            )
            or self.kind not in ("future", "option")
            or type(self.kind) is not str
        ):
            raise ValueError("invalid calendar scope")
        if type(self.status) is not str or self.status not in _REASONS:
            raise ValueError("invalid status")
        allowed = _REASONS[self.status]
        if type(self.reason) is not str or (
            self.reason not in allowed if type(allowed) is tuple else self.reason != allowed
        ):
            raise ValueError("invalid reason")
        if self.sources_verified is not False:
            raise ValueError("source verification is not supported")
        values = (self.max_advance_days, self.max_spill_days)
        if self.status == "COMPLETE":
            if any(type(v) is not int or v < 0 for v in values):
                raise ValueError("complete bounds require nonnegative integers")
        elif any(v is not None for v in values):
            raise ValueError("incomplete bounds must be absent")
