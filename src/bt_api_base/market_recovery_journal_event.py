"""Bounded recovery-journal event codec; it does not authenticate a producer.

Monotonic observations retain their source-process domain. UTC bounds are local
qualification claims, not independent clock proof or trading authority.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, fields

from bt_api_base.market_protocol import MarketSubscriptionKey
from bt_api_base.market_recovery_observation import (
    RecoveryCoverageObservation,
    RecoveryObservationMember,
)
from bt_api_base.service_protocol import MAX_REFERENCE_BYTES

RECOVERY_JOURNAL_EVENT_SCHEMA = "bt_api.market_recovery_journal_event/v1"
RECOVERY_JOURNAL_EVENT_TYPE = "gateway.recovery.journal.v1"
MAX_RECOVERY_JOURNAL_EVENT_BYTES = 64 * 1024
_MAX_INT = (1 << 63) - 1
_MIN_INT = -(1 << 63)
_FIELDS = frozenset(
    {
        "schema",
        "scope_ref",
        "source_ref",
        "source_epoch",
        "journal_cursor",
        "kind",
        "observation",
        "qualification",
        "gap_start",
        "gap_end",
        "previous_epoch",
        "continuity",
        "through_sequence",
    }
)
_OBSERVATION_FIELDS = frozenset(field.name for field in fields(RecoveryCoverageObservation))
_QUALIFICATION_FIELDS = frozenset(
    {
        "status",
        "reason",
        "start_utc_lower_ns",
        "start_utc_upper_ns",
        "end_utc_lower_ns",
        "end_utc_upper_ns",
        "source_epoch",
        "first_sample_sequence",
        "last_sample_sequence",
    }
)
_UNKNOWN_REASONS = frozenset(
    {
        "SOURCE_UNKNOWN",
        "INVALID_INTERVAL",
        "OWNER_CHANGED",
        "INTERVAL_NOT_PAST",
        "CLOCK_DISCONTINUITY",
        "NO_CLOCK_HISTORY",
        "HISTORY_GAP",
        "HISTORY_LIMIT",
        "HISTORY_CHANGED",
        "HISTORY_UNAVAILABLE",
        "INVALID_HISTORY",
        "INVALID_SAMPLE",
        "CLOCK_UNAVAILABLE",
        "NO_START_SAMPLE",
        "SAMPLE_EXPIRED",
    }
)


class RecoveryJournalEventError(ValueError):
    """Finite codec error without payload, identity, or transport details."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _fail(code="INVALID_EVENT"):
    raise RecoveryJournalEventError(code) from None


def _reference(value):
    if type(value) is not str or not value or value != value.strip() or not value.isprintable():
        _fail()
    if len(value.encode("utf-8", "strict")) > MAX_REFERENCE_BYTES:
        _fail()


def _epoch(value):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{32}", value, re.ASCII) is None:
        _fail()


def _integer(value, minimum=0, maximum=_MAX_INT):
    if type(value) is not int or not minimum <= value <= maximum:
        _fail()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail()
        result[key] = value
    return result


def _observation(raw):
    if type(raw) is not dict or set(raw) != _OBSERVATION_FIELDS or type(raw["members"]) is not list:
        _fail()
    if len(raw["members"]) > 1024:
        _fail()
    members = []
    for member in raw["members"]:
        if (
            type(member) is not dict
            or set(member) != {"key", "generation"}
            or type(member["key"]) is not dict
            or type(member["key"].get("instrument")) is not dict
        ):
            _fail()
        members.append(
            RecoveryObservationMember(
                MarketSubscriptionKey.from_dict(member["key"]), member["generation"]
            )
        )
    return RecoveryCoverageObservation(**{**raw, "members": tuple(members)})


def recovery_journal_observation_from_mapping(raw):
    """Construct an independent, validated observation from its wire shape."""
    try:
        return _observation(raw)
    except RecoveryJournalEventError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, OverflowError):
        _fail()


def validate_recovery_journal_qualification(raw, observation):
    """Check the exact neutral qualification shape against one observation."""
    try:
        if (
            type(observation) is not RecoveryCoverageObservation
            or type(raw) is not dict
            or set(raw) != _QUALIFICATION_FIELDS
        ):
            _fail()
        observation.__post_init__()
        status, reason = raw["status"], raw["reason"]
        projected = tuple(
            raw[name]
            for name in (
                "start_utc_lower_ns",
                "start_utc_upper_ns",
                "end_utc_lower_ns",
                "end_utc_upper_ns",
            )
        )
        samples = (raw["source_epoch"], raw["first_sample_sequence"], raw["last_sample_sequence"])
        if type(status) is not str or type(reason) is not str:
            _fail()
        if status == "UNKNOWN":
            if (
                reason not in _UNKNOWN_REASONS
                or any(x is not None for x in (*projected, *samples))
                or (observation.state == "UNKNOWN") != (reason == "SOURCE_UNKNOWN")
            ):
                _fail()
        elif status == "QUALIFIED":
            if reason != "OK" or observation.state == "UNKNOWN":
                _fail()
            for value in projected:
                _integer(value, _MIN_INT)
            start_low, start_high, end_low, end_high = projected
            if (
                start_low > start_high
                or end_low > end_high
                or start_low > end_high
                or (
                    observation.coverage_started_monotonic_ns
                    == observation.coverage_through_monotonic_ns
                    and (start_low != end_low or start_high != end_high)
                )
            ):
                _fail()
            _epoch(samples[0])
            _integer(samples[1], 1)
            _integer(samples[2], 1)
            if samples[1] > samples[2]:
                _fail()
        else:
            _fail()
    except RecoveryJournalEventError:
        raise
    except (ValueError, TypeError, AttributeError, UnicodeError, OverflowError):
        _fail()


def _validate(raw):
    if (
        type(raw) is not dict
        or set(raw) != _FIELDS
        or raw["schema"] != RECOVERY_JOURNAL_EVENT_SCHEMA
        or type(raw["schema"]) is not str
    ):
        _fail()
    _reference(raw["scope_ref"])
    _reference(raw["source_ref"])
    _epoch(raw["source_epoch"])
    _integer(raw["journal_cursor"], 1)
    kind = raw["kind"]
    if type(kind) is not str or kind not in ("observation", "gap", "epoch", "capture_stopped"):
        _fail()
    nullable = {
        "observation",
        "qualification",
        "gap_start",
        "gap_end",
        "previous_epoch",
        "continuity",
        "through_sequence",
    }
    allowed = {
        "observation": {"observation", "qualification"},
        "gap": {"gap_start", "gap_end", "continuity"},
        "epoch": {"previous_epoch", "continuity"},
        "capture_stopped": {"through_sequence", "continuity"},
    }[kind]
    if any(raw[name] is not None for name in nullable - allowed):
        _fail()
    if kind == "observation":
        observation = _observation(raw["observation"])
        if observation.source_epoch != raw["source_epoch"]:
            _fail()
        validate_recovery_journal_qualification(raw["qualification"], observation)
    elif kind == "gap":
        _integer(raw["gap_start"], 1)
        _integer(raw["gap_end"], 1)
        if (
            raw["gap_start"] > raw["gap_end"]
            or raw["continuity"] != "unknown"
            or type(raw["continuity"]) is not str
        ):
            _fail()
    elif kind == "epoch":
        if raw["continuity"] != "unknown" or type(raw["continuity"]) is not str:
            _fail()
        if raw["previous_epoch"] is not None:
            _epoch(raw["previous_epoch"])
            if raw["previous_epoch"] == raw["source_epoch"]:
                _fail()
    else:
        _integer(raw["through_sequence"])
        if raw["continuity"] != "unknown" or type(raw["continuity"]) is not str:
            _fail()


def _canonical(raw):
    try:
        _validate(raw)
        encoded = json.dumps(
            raw, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("ascii")
        if len(encoded) > MAX_RECOVERY_JOURNAL_EVENT_BYTES:
            _fail("EVENT_TOO_LARGE")
        # The caller may mutate a mapping during serialization. Validate exactly
        # the detached bytes that will be returned, not only the input object.
        detached = json.loads(encoded, object_pairs_hook=_pairs, parse_constant=lambda _: _fail())
        _validate(detached)
        return encoded
    except RecoveryJournalEventError:
        raise
    except (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        UnicodeError,
        OverflowError,
        RecursionError,
    ):
        _fail()


def _decode(data):
    if type(data) is not bytes:
        _fail()
    if len(data) > MAX_RECOVERY_JOURNAL_EVENT_BYTES:
        _fail("EVENT_TOO_LARGE")
    try:
        raw = json.loads(
            data.decode("utf-8", "strict"),
            object_pairs_hook=_pairs,
            parse_constant=lambda _: _fail(),
        )
        return _canonical(raw)
    except RecoveryJournalEventError:
        raise
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
        _fail()


@dataclass(frozen=True, slots=True)
class MarketRecoveryJournalEvent:
    """Independent canonical bytes; each mapping projection is freshly decoded."""

    _canonical_json: bytes

    def __post_init__(self):
        canonical = _decode(self._canonical_json)
        if canonical != self._canonical_json:
            _fail()

    def to_dict(self):
        return json.loads(encode_recovery_journal_event(self))


def parse_recovery_journal_event(value, *, expected_scope_ref=None, expected_source_ref=None):
    """Validate and detach a mapping or UTF-8 JSON bytes; expected refs are caller policy."""
    canonical = _canonical(value) if type(value) is dict else _decode(value)
    detached = json.loads(canonical)
    if expected_scope_ref is not None:
        _reference(expected_scope_ref)
        if detached["scope_ref"] != expected_scope_ref:
            _fail("SCOPE_MISMATCH")
    if expected_source_ref is not None:
        _reference(expected_source_ref)
        if detached["source_ref"] != expected_source_ref:
            _fail("SOURCE_MISMATCH")
    return MarketRecoveryJournalEvent(canonical)


def encode_recovery_journal_event(event):
    if type(event) is not MarketRecoveryJournalEvent:
        _fail()
    canonical = _decode(event._canonical_json)
    if canonical != event._canonical_json:
        _fail()
    return canonical
