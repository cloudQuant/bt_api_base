"""Offline synthetic contracts, not official exchange or account evidence."""

from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from bt_api_base.trading_calendar_protocol import (
    CalendarContractKind,
    CalendarCoverage,
    CalendarCoverageStatus,
    CalendarGap,
    CalendarGapReason,
    CalendarPhase,
    CalendarQuery,
    CalendarQueryResult,
    CalendarResultReason,
    CalendarScope,
    CalendarSource,
    CalendarVersion,
    CalendarWindow,
    TradingCalendarQueryPort,
    UtcInterval,
)

START = datetime(2026, 10, 9, 13, tzinfo=timezone.utc)
ZONE = ZoneInfo("Asia/Shanghai")
SOURCE = CalendarSource("synthetic", "https://example.invalid/a?x=1&y=2")
VERSION = CalendarVersion("fixture-v1", "a" * 64)
SCOPE = CalendarScope("route-a", "SIM", CalendarContractKind.FUTURE, "x", "x2601")


def interval(start, end):
    return UtcInterval(START + timedelta(hours=start), START + timedelta(hours=end))


def request():
    return CalendarQuery(SCOPE, interval(0, 10))


def coverage(start, end, source_ids=("synthetic",)):
    return CalendarCoverage(interval(start, end), source_ids)


def gap(start, end):
    return CalendarGap(interval(start, end), CalendarGapReason.COVERAGE_UNAVAILABLE)


def window(start, end, sources=("synthetic",), phase=CalendarPhase.CONTINUOUS):
    span = interval(start, end)
    return CalendarWindow(
        span,
        phase,
        date(2026, 10, 12),
        "Asia/Shanghai",
        span.start_utc.astimezone(ZONE),
        span.end_utc.astimezone(ZONE),
        sources,
    )


def result(
    status=CalendarCoverageStatus.COMPLETE,
    covers=None,
    gaps=(),
    windows=(),
    sources=(SOURCE,),
    version=VERSION,
    reason=None,
):
    if covers is None:
        covers = (coverage(0, 10),)
    return CalendarQueryResult(request(), status, version, covers, gaps, windows, sources, reason)


def test_complete_known_empty_and_cross_midnight_trading_day():
    empty = result()
    assert empty.known_empty
    night = window(0, 4)
    assert night.start_local.isoformat() == "2026-10-09T21:00:00+08:00"
    assert night.end_local.isoformat() == "2026-10-10T01:00:00+08:00"
    assert night.trading_day == date(2026, 10, 12)
    actual = result(windows=(night, window(4, 5, phase=CalendarPhase.AUCTION)))
    assert not actual.known_empty
    assert actual.windows[0].interval.end_utc == actual.windows[1].interval.start_utc
    assert actual.request.scope == SCOPE and actual.version == VERSION

    explicitly_closed = result(windows=(window(0, 1, phase=CalendarPhase.CLOSED),))
    assert explicitly_closed.windows[0].phase is CalendarPhase.CLOSED
    assert not explicitly_closed.known_empty


def test_partial_exact_partition_and_half_open_gap_boundaries():
    partial = result(
        CalendarCoverageStatus.PARTIAL,
        covers=(coverage(0, 4), coverage(6, 10)),
        gaps=(gap(4, 6),),
        windows=(window(1, 4), window(6, 9)),
        reason=CalendarResultReason.PARTIAL_COVERAGE,
    )
    assert not partial.known_empty
    assert partial.coverage[0].interval.end_utc == partial.gaps[0].interval.start_utc
    assert partial.gaps[0].interval.end_utc == partial.windows[1].interval.start_utc
    for bad in (window(3, 5), window(5, 7), window(4, 6)):
        with pytest.raises(ValueError, match="gap"):
            replace(partial, windows=(bad,))

    disjoint = result(
        CalendarCoverageStatus.PARTIAL,
        covers=(coverage(0, 2), coverage(4, 6), coverage(8, 10)),
        gaps=(gap(2, 4), gap(6, 8)),
        windows=(window(0, 2), window(4, 6), window(8, 10)),
        reason=CalendarResultReason.PARTIAL_COVERAGE,
    )
    assert len(disjoint.windows) == 3
    with pytest.raises(ValueError, match="gap"):
        replace(disjoint, windows=(window(5, 7),))


def test_unknown_and_out_of_scope_cannot_look_like_known_empty():
    unknown = result(
        CalendarCoverageStatus.UNKNOWN,
        covers=(),
        gaps=(gap(0, 10),),
        sources=(),
        version=None,
        reason=CalendarResultReason.COVERAGE_UNAVAILABLE,
    )
    assert not unknown.known_empty and not unknown.windows
    out = result(
        CalendarCoverageStatus.OUT_OF_SCOPE,
        covers=(),
        sources=(),
        version=None,
        reason=CalendarResultReason.IDENTITY_OUT_OF_SCOPE,
    )
    assert not out.known_empty and not out.windows
    with pytest.raises(ValueError):
        replace(unknown, windows=(window(1, 2),), sources=(SOURCE,))
    with pytest.raises(ValueError):
        replace(out, gaps=(gap(0, 10),))
    with pytest.raises(ValueError):
        replace(unknown, gaps=(gap(0, 4),))


def test_contract_type_is_explicit_and_not_inferred():
    option = replace(SCOPE, kind=CalendarContractKind.OPTION, instrument="x2601-C-10")
    assert option.kind is CalendarContractKind.OPTION and option != SCOPE
    with pytest.raises(ValueError):
        replace(option, kind="option")
    with pytest.raises(ValueError):
        replace(option, instrument="")
    with pytest.raises(ValueError):
        replace(option, route="route a")


@pytest.mark.parametrize(
    "covers,gaps,status",
    [
        ((coverage(0, 4), coverage(5, 10)), (), CalendarCoverageStatus.COMPLETE),
        ((coverage(0, 4), coverage(3, 10)), (), CalendarCoverageStatus.COMPLETE),
        ((coverage(0, 10),), (gap(4, 6),), CalendarCoverageStatus.PARTIAL),
        ((coverage(0, 4),), (gap(5, 10),), CalendarCoverageStatus.PARTIAL),
        ((coverage(0, 4),), (), CalendarCoverageStatus.PARTIAL),
        ((), (gap(0, 10),), CalendarCoverageStatus.PARTIAL),
        ((coverage(0, 10),), (gap(0, 10),), CalendarCoverageStatus.UNKNOWN),
    ],
)
def test_bad_partitions_or_status_cannot_claim_completeness(covers, gaps, status):
    reasons = {
        CalendarCoverageStatus.COMPLETE: None,
        CalendarCoverageStatus.PARTIAL: CalendarResultReason.PARTIAL_COVERAGE,
        CalendarCoverageStatus.UNKNOWN: CalendarResultReason.COVERAGE_UNAVAILABLE,
    }
    with pytest.raises(ValueError):
        result(status, covers=covers, gaps=gaps, reason=reasons[status])


def test_reason_must_be_finite_and_match_status():
    with pytest.raises(ValueError):
        result(reason=CalendarResultReason.CONFLICT)
    with pytest.raises(ValueError):
        result(
            CalendarCoverageStatus.UNKNOWN,
            covers=(),
            gaps=(gap(0, 10),),
            sources=(),
            version=None,
            reason=CalendarResultReason.IDENTITY_OUT_OF_SCOPE,
        )
    with pytest.raises(ValueError):
        result(
            CalendarCoverageStatus.UNKNOWN,
            covers=(),
            gaps=(gap(0, 10),),
            sources=(),
            version=None,
            reason="coverage_unavailable",
        )


def test_window_order_range_and_source_checks():
    with pytest.raises(ValueError):
        result(windows=(window(3, 5), window(4, 6)))
    with pytest.raises(ValueError):
        result(windows=(window(5, 6), window(1, 2)))
    with pytest.raises(ValueError):
        result(windows=(window(-1, 1),))
    with pytest.raises(ValueError):
        result(windows=(window(9, 11),))
    with pytest.raises(ValueError):
        result(windows=(window(0, 1, sources=("missing",)),))
    with pytest.raises(ValueError):
        result(covers=(coverage(0, 10, ("missing",)),))
    with pytest.raises(ValueError):
        result(sources=())
    with pytest.raises(ValueError):
        result(sources=(SOURCE, SOURCE))
    with pytest.raises(ValueError):
        coverage(0, 10, ())
    with pytest.raises(ValueError):
        coverage(0, 10, ("synthetic", "synthetic"))


def test_local_and_utc_consistency_and_strict_timezone():
    span = interval(0, 4)
    with pytest.raises(ValueError):
        UtcInterval(START.replace(tzinfo=None), span.end_utc)
    with pytest.raises(ValueError):
        UtcInterval(START.astimezone(ZONE), span.end_utc)
    with pytest.raises(ValueError):
        UtcInterval(START, START)
    good = window(0, 4)
    with pytest.raises(ValueError):
        replace(good, start_local=good.start_local + timedelta(minutes=1))
    with pytest.raises(ValueError):
        replace(good, local_timezone="Not/A_Timezone")
    with pytest.raises(ValueError):
        replace(good, start_local=good.start_local.replace(tzinfo=None))
    with pytest.raises(ValueError):
        replace(good, trading_day=datetime(2026, 10, 12))
    with pytest.raises(ValueError):
        replace(good, phase="continuous")

    # Canonical timezone objects are detached from supplied offset wrappers.
    fixed_zone = timezone(timedelta(hours=8))
    stable = replace(
        good,
        start_local=good.start_local.astimezone(fixed_zone),
        end_local=good.end_local.astimezone(fixed_zone),
    )
    assert stable.start_local.tzinfo is ZONE
    assert stable.interval.start_utc.tzinfo is timezone.utc


def test_version_digest_and_immutable_nested_types():
    for digest in ("A" * 64, "a" * 63, "g" * 64, ""):
        with pytest.raises(ValueError):
            CalendarVersion("v", digest)
    with pytest.raises(ValueError):
        CalendarVersion("", "a" * 64)
    value = result(windows=(window(0, 1),))
    with pytest.raises(FrozenInstanceError):
        value.status = CalendarCoverageStatus.UNKNOWN
    with pytest.raises(FrozenInstanceError):
        value.request.scope.route = "other"
    with pytest.raises(FrozenInstanceError):
        value.windows[0].interval.start_utc = START
    with pytest.raises(ValueError):
        replace(value, windows=list(value.windows))
    with pytest.raises(ValueError):
        replace(value, sources=[SOURCE])


def test_minimal_query_protocol_is_read_only_shape():
    class SyntheticProvider:
        def query(self, selected):
            assert selected == request()
            return result()

    provider = SyntheticProvider()
    assert isinstance(provider, TradingCalendarQueryPort)
    assert provider.query(request()).known_empty
