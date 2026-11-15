"""EXPERIMENTAL provider-neutral calendar query shapes; not an authority.

These types do not authenticate sources, verify exchange facts, clocks, account
identity or grant trading permission. COMPLETE is a supplied structural claim,
not independent verification. This module is not wired to an existing port.
UTC intervals are half-open; local endpoints retain their declared IANA zone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional, Protocol, runtime_checkable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_TEXT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,255}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_ITEMS = 100_000


class CalendarContractKind(str, Enum):
    FUTURE = "future"
    OPTION = "option"


class CalendarCoverageStatus(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    OUT_OF_SCOPE = "out_of_scope"


class CalendarPhase(str, Enum):
    CONTINUOUS = "continuous"
    AUCTION = "auction"
    BREAK = "break"
    CLOSED = "closed"


class CalendarGapReason(str, Enum):
    COVERAGE_UNAVAILABLE = "coverage_unavailable"
    SOURCE_MISSING = "source_missing"
    RULE_UNKNOWN = "rule_unknown"
    CONFLICT = "conflict"
    UNSUPPORTED = "unsupported"


class CalendarResultReason(str, Enum):
    PARTIAL_COVERAGE = "partial_coverage"
    COVERAGE_UNAVAILABLE = "coverage_unavailable"
    IDENTITY_OUT_OF_SCOPE = "identity_out_of_scope"
    SOURCE_MISSING = "source_missing"
    RULE_UNKNOWN = "rule_unknown"
    CONFLICT = "conflict"
    UNSUPPORTED = "unsupported"


def _text(value: Any, name: str) -> None:
    if type(value) is not str or _TEXT.fullmatch(value) is None:
        raise ValueError(f"{name} must be bounded canonical text")


def _locator(value: Any) -> None:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or not value.isprintable()
        or len(value.encode("utf-8")) > 1024
    ):
        raise ValueError("locator must be bounded printable text")


def _utc(value: Any, name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be an aware UTC datetime")


def _tuple(value: Any, name: str) -> None:
    if type(value) is not tuple or len(value) > _MAX_ITEMS:
        raise ValueError(f"{name} must be a bounded tuple")


def _refs(value: Any, name: str) -> None:
    _tuple(value, name)
    if not value:
        raise ValueError(f"{name} must not be empty")
    for item in value:
        _text(item, name)
    if len(set(value)) != len(value):
        raise ValueError(f"{name} must be unique")


@dataclass(frozen=True)
class CalendarScope:
    """Exact caller-selected route and contract; no product inference."""

    route: str
    venue: str
    kind: CalendarContractKind
    product: str
    instrument: str

    def __post_init__(self) -> None:
        for name in ("route", "venue", "product", "instrument"):
            _text(getattr(self, name), name)
        if type(self.kind) is not CalendarContractKind:
            raise ValueError("kind must be CalendarContractKind")


@dataclass(frozen=True)
class UtcInterval:
    """Strictly nonempty UTC half-open interval [start_utc, end_utc)."""

    start_utc: datetime
    end_utc: datetime

    def __post_init__(self) -> None:
        _utc(self.start_utc, "start_utc")
        _utc(self.end_utc, "end_utc")
        if self.start_utc >= self.end_utc:
            raise ValueError("interval must be nonempty and ordered")
        object.__setattr__(self, "start_utc", self.start_utc.astimezone(timezone.utc))
        object.__setattr__(self, "end_utc", self.end_utc.astimezone(timezone.utc))


@dataclass(frozen=True)
class CalendarQuery:
    scope: CalendarScope
    interval: UtcInterval

    def __post_init__(self) -> None:
        if type(self.scope) is not CalendarScope or type(self.interval) is not UtcInterval:
            raise ValueError("query requires exact scope and UTC interval")


@dataclass(frozen=True)
class CalendarVersion:
    """Snapshot label and supplied SHA-256; neither proves authenticity."""

    calendar_ref: str
    content_sha256: str

    def __post_init__(self) -> None:
        _text(self.calendar_ref, "calendar_ref")
        if type(self.content_sha256) is not str or _SHA256.fullmatch(self.content_sha256) is None:
            raise ValueError("content_sha256 must be lowercase SHA-256 hex")


@dataclass(frozen=True)
class CalendarSource:
    """Opaque source identity and locator, neither independently verified."""

    source_id: str
    locator: str

    def __post_init__(self) -> None:
        _text(self.source_id, "source_id")
        _locator(self.locator)


@dataclass(frozen=True)
class CalendarCoverage:
    """A structurally asserted known portion with explicit source references."""

    interval: UtcInterval
    source_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.interval) is not UtcInterval:
            raise ValueError("coverage requires UtcInterval")
        _refs(self.source_ids, "source_ids")


@dataclass(frozen=True)
class CalendarGap:
    """A range whose session state is not known."""

    interval: UtcInterval
    reason: CalendarGapReason

    def __post_init__(self) -> None:
        if type(self.interval) is not UtcInterval or type(self.reason) is not CalendarGapReason:
            raise ValueError("gap requires UtcInterval and CalendarGapReason")


@dataclass(frozen=True)
class CalendarWindow:
    """One phase with original trading day, local endpoints and source refs."""

    interval: UtcInterval
    phase: CalendarPhase
    trading_day: date
    local_timezone: str
    start_local: datetime
    end_local: datetime
    source_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.interval) is not UtcInterval or type(self.phase) is not CalendarPhase:
            raise ValueError("window requires interval and phase")
        if type(self.trading_day) is not date:
            raise ValueError("trading_day must be a date")
        _text(self.local_timezone, "local_timezone")
        try:
            zone = ZoneInfo(self.local_timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("unknown IANA local timezone") from exc
        for name, local, utc in (
            ("start_local", self.start_local, self.interval.start_utc),
            ("end_local", self.end_local, self.interval.end_utc),
        ):
            if type(local) is not datetime or local.tzinfo is None or local.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
            expected = utc.astimezone(zone)
            if (
                local.replace(tzinfo=None) != expected.replace(tzinfo=None)
                or local.utcoffset() != expected.utcoffset()
                or local.fold != expected.fold
            ):
                raise ValueError(f"{name} does not match interval and local timezone")
            object.__setattr__(self, name, expected)
        _refs(self.source_ids, "source_ids")


def _ordered(items: tuple, name: str) -> None:
    for before, after in zip(items, items[1:]):
        if before.interval.end_utc > after.interval.start_utc:
            raise ValueError(f"{name} must be ordered and nonoverlapping")


@dataclass(frozen=True)
class CalendarQueryResult:
    """Partition of the request into explicitly covered and unknown ranges.

    COMPLETE may have zero windows: that is a known-empty phase set. PARTIAL and
    UNKNOWN never claim that absent windows in gaps mean closed. OUT_OF_SCOPE is
    an identity/scope result and does not assert a coverage partition.
    """

    request: CalendarQuery
    status: CalendarCoverageStatus
    version: Optional[CalendarVersion]  # noqa: UP045 - runtime type hints on Python 3.9
    coverage: tuple[CalendarCoverage, ...]
    gaps: tuple[CalendarGap, ...]
    windows: tuple[CalendarWindow, ...]
    sources: tuple[CalendarSource, ...]
    reason: Optional[CalendarResultReason] = None  # noqa: UP045 - Python 3.9

    def __post_init__(self) -> None:
        if (
            type(self.request) is not CalendarQuery
            or type(self.status) is not CalendarCoverageStatus
        ):
            raise ValueError("result requires exact query and status")
        if self.version is not None and type(self.version) is not CalendarVersion:
            raise ValueError("version must be CalendarVersion or None")
        for name in ("coverage", "gaps", "windows", "sources"):
            _tuple(getattr(self, name), name)
        for name, expected in (
            ("coverage", CalendarCoverage),
            ("gaps", CalendarGap),
            ("windows", CalendarWindow),
            ("sources", CalendarSource),
        ):
            if any(type(item) is not expected for item in getattr(self, name)):
                raise ValueError(f"{name} contains invalid items")
        reasons = {
            CalendarCoverageStatus.COMPLETE: {None},
            CalendarCoverageStatus.PARTIAL: {
                CalendarResultReason.PARTIAL_COVERAGE,
                CalendarResultReason.SOURCE_MISSING,
                CalendarResultReason.RULE_UNKNOWN,
                CalendarResultReason.CONFLICT,
                CalendarResultReason.UNSUPPORTED,
            },
            CalendarCoverageStatus.UNKNOWN: {
                CalendarResultReason.COVERAGE_UNAVAILABLE,
                CalendarResultReason.SOURCE_MISSING,
                CalendarResultReason.RULE_UNKNOWN,
                CalendarResultReason.CONFLICT,
                CalendarResultReason.UNSUPPORTED,
            },
            CalendarCoverageStatus.OUT_OF_SCOPE: {
                CalendarResultReason.IDENTITY_OUT_OF_SCOPE,
                CalendarResultReason.UNSUPPORTED,
            },
        }
        if (
            self.reason is not None and type(self.reason) is not CalendarResultReason
        ) or self.reason not in reasons[self.status]:
            raise ValueError("reason is inconsistent with result status")
        source_ids = {item.source_id for item in self.sources}
        if len(source_ids) != len(self.sources):
            raise ValueError("source IDs must be unique")
        for row in self.coverage + self.windows:
            if not set(row.source_ids) <= source_ids:
                raise ValueError("coverage or window refers to an absent source")
        for name in ("coverage", "gaps", "windows"):
            _ordered(getattr(self, name), name)
        if self.status is CalendarCoverageStatus.OUT_OF_SCOPE:
            if self.coverage or self.gaps or self.windows:
                raise ValueError("out-of-scope result cannot assert intervals")
            return
        if self.status is CalendarCoverageStatus.COMPLETE:
            if self.version is None or not self.coverage or self.gaps:
                raise ValueError("complete requires version, coverage and no gaps")
        elif self.status is CalendarCoverageStatus.PARTIAL:
            if self.version is None or not self.coverage or not self.gaps:
                raise ValueError("partial requires version, coverage and gaps")
        elif self.status is CalendarCoverageStatus.UNKNOWN and (
            self.coverage or self.windows or not self.gaps
        ):
            raise ValueError("unknown requires gaps and no coverage or windows")
        pieces = sorted(
            (row.interval for row in self.coverage + self.gaps), key=lambda x: x.start_utc
        )
        span = self.request.interval
        if (
            not pieces
            or pieces[0].start_utc != span.start_utc
            or pieces[-1].end_utc != span.end_utc
            or any(a.end_utc != b.start_utc for a, b in zip(pieces, pieces[1:]))
        ):
            raise ValueError("coverage and gaps must exactly partition the requested interval")
        gap_index = 0
        for window in self.windows:
            w = window.interval
            if w.start_utc < span.start_utc or w.end_utc > span.end_utc:
                raise ValueError("window lies outside request")
            while (
                gap_index < len(self.gaps) and self.gaps[gap_index].interval.end_utc <= w.start_utc
            ):
                gap_index += 1
            if gap_index < len(self.gaps) and self.gaps[gap_index].interval.start_utc < w.end_utc:
                raise ValueError("window overlaps an unknown gap")

    @property
    def known_empty(self) -> bool:
        return self.status is CalendarCoverageStatus.COMPLETE and not self.windows


@runtime_checkable
class TradingCalendarQueryPort(Protocol):
    """Experimental read-only interface, no provider discovery or registration."""

    def query(self, request: CalendarQuery) -> CalendarQueryResult:
        """Return one version-bound result for the exact request scope."""
        ...
