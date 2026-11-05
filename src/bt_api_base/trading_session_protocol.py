"""Provider-neutral trading-session schedule contracts.

A provider owns venue session facts (trading days, night sessions, call
auctions, holidays).  The SDK exposes them through
:class:`TradingSessionSchedulePort`; hosts use the answer to decide whether a
venue is closed now and when the next continuous session starts.  An unknown
calendar answer is never a closed or open fact.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from typing import Optional, Protocol, runtime_checkable

__all__ = (
    "TradingPhase",
    "TradingSessionSchedulePort",
    "TradingSessionState",
    "TradingWindow",
    "TradingWindowKind",
)


class TradingPhase(str, Enum):
    CLOSED = "closed"
    AUCTION = "auction"
    CONTINUOUS = "continuous"
    UNKNOWN = "unknown"


class TradingWindowKind(str, Enum):
    AUCTION = "auction"
    CONTINUOUS = "continuous"


def _utc(value: datetime, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class TradingWindow:
    """One half-open ``[start_utc, end_utc)`` window of one trading day."""

    trading_day: date
    kind: TradingWindowKind
    start_utc: datetime
    end_utc: datetime
    session_id: str

    def __post_init__(self) -> None:
        if type(self.trading_day) is not date:
            raise ValueError("trading_day must be a date")
        if type(self.kind) is not TradingWindowKind:
            raise ValueError("kind must be a TradingWindowKind")
        object.__setattr__(self, "start_utc", _utc(self.start_utc, "start_utc"))
        object.__setattr__(self, "end_utc", _utc(self.end_utc, "end_utc"))
        if self.end_utc <= self.start_utc:
            raise ValueError("end_utc must be after start_utc")
        if type(self.session_id) is not str or not self.session_id:
            raise ValueError("session_id must be a non-empty string")

    def contains(self, at_utc: datetime) -> bool:
        at = _utc(at_utc, "at_utc")
        return self.start_utc <= at < self.end_utc


@dataclass(frozen=True)
class TradingSessionState:
    """Answer for one instrument at one instant."""

    instrument_id: str
    at_utc: datetime
    phase: TradingPhase
    trading_day: Optional[date]
    current_window: Optional[TradingWindow]
    next_continuous: Optional[TradingWindow]
    calendar_ref: str
    reason: Optional[str] = None

    def __post_init__(self) -> None:
        if type(self.instrument_id) is not str or not self.instrument_id:
            raise ValueError("instrument_id must be a non-empty string")
        object.__setattr__(self, "at_utc", _utc(self.at_utc, "at_utc"))
        if type(self.phase) is not TradingPhase:
            raise ValueError("phase must be a TradingPhase")
        if type(self.calendar_ref) is not str or not self.calendar_ref:
            raise ValueError("calendar_ref must be a non-empty string")
        if self.phase is TradingPhase.UNKNOWN and not self.reason:
            raise ValueError("an UNKNOWN phase needs a reason")


@runtime_checkable
class TradingSessionSchedulePort(Protocol):
    """Provider-owned schedule for the instruments of one route."""

    def session_state(self, instrument_id: str, at_utc: datetime) -> TradingSessionState:
        """Return the phase of ``instrument_id`` at ``at_utc``."""

    def windows(
        self, instrument_id: str, start_utc: datetime, end_utc: datetime
    ) -> tuple[TradingWindow, ...]:
        """Return all windows overlapping ``[start_utc, end_utc)`` in time order."""
