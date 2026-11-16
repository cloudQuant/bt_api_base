import copy
import json

import pytest

from bt_api_base.market_protocol import MarketInstrumentKey, MarketSubscriptionKey
from bt_api_base.market_recovery_journal_event import (
    RECOVERY_JOURNAL_EVENT_SCHEMA,
    RECOVERY_JOURNAL_EVENT_TYPE,
    RecoveryJournalEventError,
    encode_recovery_journal_event,
    parse_recovery_journal_event,
)

EPOCH = "a" * 32
CLOCK = "c" * 32
KEY = MarketSubscriptionKey(
    "src", "grant", MarketInstrumentKey("ctp", "venue", "demo", "future", "id", "symbol"), "trade"
)


def event(kind="observation"):
    result = {
        "schema": RECOVERY_JOURNAL_EVENT_SCHEMA,
        "scope_ref": "scope",
        "source_ref": "source",
        "source_epoch": EPOCH,
        "journal_cursor": 1,
        "kind": kind,
        "observation": None,
        "qualification": None,
        "gap_start": None,
        "gap_end": None,
        "previous_epoch": None,
        "continuity": None,
        "through_sequence": None,
    }
    if kind == "observation":
        result["observation"] = {
            "source_epoch": EPOCH,
            "owner_pid": 321,
            "sequence": 1,
            "episode_id": "d" * 32,
            "state": "RECOVERING",
            "reason": "WATERMARK",
            "observed_monotonic_ns": 102,
            "coverage_started_monotonic_ns": 100,
            "coverage_through_monotonic_ns": 102,
            "origin_connection_generation": 1,
            "observed_connection_generation": 2,
            "members": [{"key": KEY.to_dict(), "generation": "gen"}],
        }
        result["qualification"] = {
            "status": "QUALIFIED",
            "reason": "OK",
            "start_utc_lower_ns": 1000,
            "start_utc_upper_ns": 1002,
            "end_utc_lower_ns": 1010,
            "end_utc_upper_ns": 1012,
            "source_epoch": CLOCK,
            "first_sample_sequence": 1,
            "last_sample_sequence": 2,
        }
    elif kind == "gap":
        result.update(gap_start=1, gap_end=2, continuity="unknown")
    elif kind == "epoch":
        result.update(continuity="unknown", previous_epoch="b" * 32)
    else:
        result.update(continuity="unknown", through_sequence=2)
    return result


def test_roundtrip_detaches_input_and_mapping():
    assert RECOVERY_JOURNAL_EVENT_TYPE == "gateway.recovery.journal.v1"
    source = event()
    stored = parse_recovery_journal_event(
        source, expected_scope_ref="scope", expected_source_ref="source"
    )
    expected = encode_recovery_journal_event(stored)
    source["observation"]["members"][0]["generation"] = "changed"
    detached = stored.to_dict()
    detached["scope_ref"] = "changed"
    assert encode_recovery_journal_event(stored) == expected
    assert parse_recovery_journal_event(expected).to_dict()["scope_ref"] == "scope"
    assert (
        parse_recovery_journal_event(expected).to_dict()["observation"]["members"][0]["generation"]
        == "gen"
    )
    with pytest.raises(RecoveryJournalEventError, match="SCOPE_MISMATCH"):
        parse_recovery_journal_event(expected, expected_scope_ref="wrong")
    with pytest.raises(RecoveryJournalEventError, match="SOURCE_MISMATCH"):
        parse_recovery_journal_event(expected, expected_source_ref="wrong")


def test_mapping_mutation_during_encoding_is_revalidated(monkeypatch):
    from bt_api_base import market_recovery_journal_event as codec

    raw = event()
    original = codec._validate
    calls = 0

    def mutate_after_first_validation(value):
        nonlocal calls
        original(value)
        calls += 1
        if calls == 1:
            raw["qualification"]["status"] = "UNKNOWN"

    monkeypatch.setattr(codec, "_validate", mutate_after_first_validation)
    with pytest.raises(RecoveryJournalEventError):
        parse_recovery_journal_event(raw)


@pytest.mark.parametrize("kind", ["observation", "gap", "epoch", "capture_stopped"])
def test_each_kind_is_canonical_and_roundtrips(kind):
    original = event(kind)
    encoded = encode_recovery_journal_event(parse_recovery_journal_event(original))
    assert parse_recovery_journal_event(encoded).to_dict() == original
    assert encoded == json.dumps(
        original, sort_keys=True, ensure_ascii=True, separators=(",", ":")
    ).encode("ascii")


def test_unknown_is_separate_from_qualified_projection():
    raw = event()
    raw["observation"].update(
        episode_id=None,
        state="UNKNOWN",
        reason="BEGIN_FAILED",
        coverage_started_monotonic_ns=None,
        coverage_through_monotonic_ns=None,
        origin_connection_generation=None,
        observed_connection_generation=None,
        members=[],
    )
    raw["qualification"] = {
        "status": "UNKNOWN",
        "reason": "SOURCE_UNKNOWN",
        "start_utc_lower_ns": None,
        "start_utc_upper_ns": None,
        "end_utc_lower_ns": None,
        "end_utc_upper_ns": None,
        "source_epoch": None,
        "first_sample_sequence": None,
        "last_sample_sequence": None,
    }
    assert parse_recovery_journal_event(raw).to_dict() == raw
    raw["qualification"]["end_utc_lower_ns"] = 10
    with pytest.raises(RecoveryJournalEventError):
        parse_recovery_journal_event(raw)


def test_qualified_zero_length_requires_equal_utc_endpoint_bounds():
    raw = event()
    raw["observation"]["coverage_through_monotonic_ns"] = 100
    with pytest.raises(RecoveryJournalEventError):
        parse_recovery_journal_event(raw)
    raw["qualification"]["end_utc_lower_ns"] = raw["qualification"]["start_utc_lower_ns"]
    raw["qualification"]["end_utc_upper_ns"] = raw["qualification"]["start_utc_upper_ns"]
    assert parse_recovery_journal_event(raw).to_dict() == raw


def test_malformed_fields_types_ranges_and_members_are_refused():
    base = event()
    cases = []
    extra = copy.deepcopy(base)
    extra["extra"] = 1
    cases.append(extra)
    missing = copy.deepcopy(base)
    del missing["gap_start"]
    cases.append(missing)
    wrong_epoch = copy.deepcopy(base)
    wrong_epoch["observation"]["source_epoch"] = "b" * 32
    cases.append(wrong_epoch)
    wrong_number = copy.deepcopy(base)
    wrong_number["journal_cursor"] = True
    cases.append(wrong_number)
    nan = copy.deepcopy(base)
    nan["qualification"]["end_utc_lower_ns"] = float("nan")
    cases.append(nan)
    extra_q = copy.deepcopy(base)
    extra_q["qualification"]["extra"] = None
    cases.append(extra_q)
    extra_member = copy.deepcopy(base)
    extra_member["observation"]["members"][0]["extra"] = None
    cases.append(extra_member)
    duplicate = copy.deepcopy(base)
    duplicate["observation"]["members"].append(
        copy.deepcopy(duplicate["observation"]["members"][0])
    )
    cases.append(duplicate)
    bad_ref = copy.deepcopy(base)
    bad_ref["source_ref"] = "a" * 257
    cases.append(bad_ref)
    bad_gap = event("gap")
    bad_gap["gap_end"] = True
    cases.append(bad_gap)
    bad_marker = event("epoch")
    bad_marker["previous_epoch"] = EPOCH
    cases.append(bad_marker)
    bad_stop = event("capture_stopped")
    bad_stop["observation"] = base["observation"]
    cases.append(bad_stop)
    for case in cases:
        with pytest.raises(RecoveryJournalEventError):
            parse_recovery_journal_event(case)
    with pytest.raises(RecoveryJournalEventError):
        parse_recovery_journal_event(b'{"schema":"a","schema":"b"}')
    with pytest.raises(RecoveryJournalEventError):
        parse_recovery_journal_event(b'{"schema":NaN}')


def test_oversized_event_rejected_without_member_truncation():
    raw = event()
    # Distinct valid keys must be sorted by their derived stream ID.
    members = []
    for index in range(300):
        key = MarketSubscriptionKey(
            "s" * 256,
            "g" * 256,
            MarketInstrumentKey("ctp", "venue", "demo", "future", str(index), "symbol"),
            "trade",
        )
        members.append((key.stream_id, {"key": key.to_dict(), "generation": "gen"}))
    raw["observation"]["members"] = [member for _, member in sorted(members)]
    with pytest.raises(RecoveryJournalEventError, match="EVENT_TOO_LARGE"):
        parse_recovery_journal_event(raw)
    assert len(raw["observation"]["members"]) == 300
