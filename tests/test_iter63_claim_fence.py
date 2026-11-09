"""Isolated tests of the Base owner-local fence; no provider or account I/O."""

import os
from dataclasses import FrozenInstanceError
import subprocess
import sys
import time

import pytest

from bt_api_base.claim_fence import ClaimFence, ClaimSchema, DispatchClaimError, _WriterChange


SCHEMA = ClaimSchema(("text", "text", "text"), 0, 1, (0, 2))


def _ready():
    c = ClaimFence._for_test("account", "owner", domains=("source", "control"), schema=SCHEMA)
    for domain in ("source", "control"):
        token = c.begin_change(domain)
        c.finish_change(token, "READY")
    return c


def _candidate(c, key):
    before, after = c.capture(), c.capture()
    return c._prepare_values(("account", "owner", key), before, after,
                             deadline_ns=time.monotonic_ns() + 1_000_000_000)


def test_production_and_writer_cannot_publish_ready_or_claim():
    c = ClaimFence("account", "owner", domains=("source",), schema=SCHEMA)
    handle = c.writer_handle("source", account="account", owner_generation="owner")
    assert not hasattr(handle, "finish_change")
    assert not hasattr(handle, "try_claim")
    with pytest.raises(FrozenInstanceError):
        handle._domain = "control"
    token = handle.begin_change()
    handle.finish_unavailable(token)
    with pytest.raises(DispatchClaimError, match="COVERAGE_UNAVAILABLE"):
        c.capture()
    token = c.begin_change("source")
    with pytest.raises(DispatchClaimError, match="COVERAGE_UNAVAILABLE"):
        c.finish_change(token, "READY")


def test_handle_binding_invalidates_existing_candidate_and_rejects_mixing():
    a, b = _ready(), _ready()
    candidate = _candidate(a, "one")
    with pytest.raises(DispatchClaimError, match="OWNER_MISMATCH"):
        a.writer_handle("source", account="other", owner_generation="owner")
    one = a.writer_handle("source", account="account", owner_generation="owner")
    assert one.matches(a, domain="source", account="account", owner_generation="owner")
    assert not one.matches(b, domain="source", account="account", owner_generation="owner")
    assert not one.matches(a, domain="control", account="account", owner_generation="owner")
    with pytest.raises(DispatchClaimError, match="DOMAIN_UNAVAILABLE"):
        a.try_claim(candidate)
    two = a.writer_handle("source", account="account", owner_generation="owner")
    token = one.begin_change()
    with pytest.raises(DispatchClaimError, match="INVALID_CHANGE"):
        two.finish_unavailable(token)
    one.finish_unavailable(token)
    with pytest.raises(DispatchClaimError, match="INVALID_CHANGE"):
        one.finish_unavailable(token)


def test_writer_invalidates_before_mutation_and_claim_after_is_in_flight():
    c = _ready()
    handle = c.writer_handle("source", account="account", owner_generation="owner")
    t = c.begin_change("source")
    c.finish_change(t, "READY")  # synthetic coverage only
    first = _candidate(c, "first")
    mutation = handle.begin_change()
    with pytest.raises(DispatchClaimError, match="DOMAIN_UNAVAILABLE"):
        c.try_claim(first)
    handle.finish_unavailable(mutation)
    t = c.begin_change("source")
    c.finish_change(t, "READY")
    with pytest.raises(DispatchClaimError, match="CANDIDATE_STALE"):
        c.try_claim(first)
    second = _candidate(c, "second")
    assert c.try_claim(second)
    token = handle.begin_change()
    handle.finish_unavailable(token)
    t = c.begin_change("source")
    c.finish_change(t, "READY")
    with pytest.raises(DispatchClaimError, match="ALREADY_CLAIMED"):
        c.try_claim(second)


def test_overlapping_handle_changes_and_poison_stay_unavailable():
    c = _ready()
    handle = c.writer_handle("source", account="account", owner_generation="owner")
    first, second = handle.begin_change(), handle.begin_change()
    handle.finish_unavailable(first)
    with pytest.raises(DispatchClaimError, match="DOMAIN_UNAVAILABLE"):
        c.capture()
    handle.poison(second)
    with pytest.raises(DispatchClaimError, match="DOMAIN_POISONED"):
        handle.begin_change()
    with pytest.raises(DispatchClaimError, match="DOMAIN_UNAVAILABLE"):
        c.capture()


def test_invalid_values_reject_before_lock_and_no_callbacks():
    class Trap:
        def __hash__(self):
            raise AssertionError("callback")
        def __eq__(self, other):
            raise AssertionError("callback")

    c = _ready()
    before, after = c.capture(), c.capture()
    with pytest.raises(DispatchClaimError, match="INVALID_CANDIDATE"):
        c._prepare_values(("account", "owner", Trap()), before, after,
                          deadline_ns=time.monotonic_ns() + 1_000_000_000)
    assert c.discard_pair(before, after) == (False, False)


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires POSIX fork")
def test_fork_while_fence_lock_held_rejects_before_child_lock():
    script = r'''
import os
from dataclasses import FrozenInstanceError
from bt_api_base.claim_fence import ClaimFence, ClaimSchema, DispatchClaimError, _WriterChange
schema = ClaimSchema(("text", "text", "text"), 0, 1, (0, 2))
c = ClaimFence._for_test("a", "o", domains=("x",), schema=schema)
with c._lock:
    pid = os.fork()
    if pid == 0:
        try:
            c.begin_change("x")
        except DispatchClaimError as e:
            os._exit(0 if e.code == "COORDINATOR_PROCESS_CHANGED" else 2)
        os._exit(3)
    _, status = os.waitpid(pid, 0)
    if not os.WIFEXITED(status) or os.WEXITSTATUS(status):
        raise SystemExit(1)
'''
    subprocess.run([sys.executable, "-c", script], check=True, timeout=5)


def test_native_work_is_outside_lock_after_claim():
    import threading

    c = _ready()
    handle = c.writer_handle("source", account="account", owner_generation="owner")
    token = c.begin_change("source")
    c.finish_change(token, "READY")
    candidate = _candidate(c, "in-flight")
    entered, release, revoked = threading.Event(), threading.Event(), threading.Event()
    errors = []

    def dispatch():
        try:
            c.try_claim(candidate)
            entered.set()
            if not release.wait(2):
                errors.append("native wait timed out")
        except BaseException as error:
            errors.append(error)

    def revoke():
        try:
            token = handle.begin_change()
            handle.finish_unavailable(token)
            revoked.set()
        except BaseException as error:
            errors.append(error)

    owner = threading.Thread(target=dispatch)
    owner.start()
    writer = threading.Thread(target=revoke)
    try:
        assert entered.wait(2)
        writer.start()
        assert revoked.wait(2)
    finally:
        release.set()
        owner.join(2)
        if writer.ident is not None:
            writer.join(2)
    assert not errors
    assert not owner.is_alive() and not writer.is_alive()


def test_command_key_is_reserved_once_across_distinct_snapshots():
    c = _ready()
    assert c.try_claim(_candidate(c, "same"))
    with pytest.raises(DispatchClaimError, match="COMMAND_ALREADY_PREPARED"):
        _candidate(c, "same")


def test_base_rechecks_bound_account_and_derives_command_key():
    c = _ready()
    before, after = c.capture(), c.capture()
    with pytest.raises(DispatchClaimError, match="OWNER_MISMATCH"):
        c._prepare_values(("other", "owner", "same"), before, after,
                          deadline_ns=time.monotonic_ns() + 1_000_000_000)
    assert c.discard_pair(before, after) == (False, False)
    assert c.try_claim(_candidate(c, "same"))
    with pytest.raises(DispatchClaimError, match="COMMAND_ALREADY_PREPARED"):
        _candidate(c, "same")


def test_unregistered_handle_and_rewrapped_token_cannot_change_domain():
    from bt_api_base.claim_fence import ClaimFenceWriter

    c = _ready()
    a = c.writer_handle("source", account="account", owner_generation="owner")
    b = c.writer_handle("source", account="account", owner_generation="owner")
    forged = ClaimFenceWriter(c, "control", "account", "owner", a._seal)
    with pytest.raises(DispatchClaimError, match="INVALID_HANDLE"):
        forged.begin_change()
    token = a.begin_change()
    rewrapped = _WriterChange(b, token.token)
    with pytest.raises(DispatchClaimError, match="INVALID_CHANGE"):
        b.finish_unavailable(rewrapped)
    with pytest.raises(DispatchClaimError, match="INVALID_CHANGE"):
        c.finish_change(token.token, "READY")
    with pytest.raises(DispatchClaimError, match="DOMAIN_UNAVAILABLE"):
        c.capture()
    a.finish_unavailable(token)


def test_final_core_refuses_subclasses_before_they_can_reenter():
    with pytest.raises(TypeError, match="final"):
        class EvilFence(ClaimFence):
            def __getattribute__(self, name):
                raise AssertionError("untrusted callback")


def test_writer_handle_capacity_is_bounded_and_closed_fails_safely():
    c = ClaimFence._for_test("account", "owner", domains=("source",), schema=SCHEMA,
                             max_snapshots=2)
    a = c.writer_handle("source", account="account", owner_generation="owner")
    c.writer_handle("source", account="account", owner_generation="owner")
    token = c.begin_change("source")
    c.finish_change(token, "READY")
    candidate = _candidate(c, "capacity")
    with pytest.raises(DispatchClaimError, match="HANDLE_CAPACITY"):
        c.writer_handle("source", account="account", owner_generation="owner")
    assert c.capacity_status()["writer_handles"] == 2
    assert c.capacity_status()["max_writer_handles"] == 2
    with pytest.raises(DispatchClaimError, match="DOMAIN_UNAVAILABLE"):
        c.try_claim(candidate)
    c.close()
    with pytest.raises(DispatchClaimError, match="COORDINATOR_CLOSED"):
        a.begin_change()


def test_completed_changes_use_constant_space_until_long_writer_finishes():
    c = _ready()
    long_change = c.begin_change("source")
    for _ in range(10000):
        short_change = c.begin_change("source")
        c.finish_change(short_change, "READY")
    assert c._domains["source"][3] == "READY"
    assert len(c._domains["source"][2]) == 1
    c.finish_change(long_change, "READY")
    assert c._domains["source"][1] == "READY"
    assert c._domains["source"][3] is None


def test_mixed_results_and_poison_discard_constant_space_aggregate():
    c = _ready()
    long_change = c.begin_change("source")
    for status in ("READY", "UNAVAILABLE", "READY"):
        token = c.begin_change("source")
        c.finish_change(token, status)
    c.finish_change(long_change, "READY")
    with pytest.raises(DispatchClaimError, match="DOMAIN_UNAVAILABLE"):
        c.capture()
    token = c.begin_change("source")
    c.poison(token)
    assert c._domains["source"][3] is None
    with pytest.raises(DispatchClaimError, match="DOMAIN_POISONED"):
        c.begin_change("source")


def test_close_drops_local_objects_and_rejects_outstanding_operations():
    c = _ready()
    handle = c.writer_handle("source", account="account", owner_generation="owner")
    change = c.begin_change("source")
    c.finish_change(change, "READY")
    in_flight = c.try_claim(_candidate(c, "sent"))
    pending = _candidate(c, "pending")
    before = c.capture()
    writer = handle.begin_change()
    c.close()
    assert in_flight.binding == ("account", "owner", "sent")
    assert not c._commands and not c._candidates and not c._snapshots
    assert not c._writer_handles and not c._writer_changes
    assert all(not state[2] and state[3] is None for state in c._domains.values())
    with pytest.raises(DispatchClaimError, match="COORDINATOR_CLOSED"):
        c.try_claim(pending)
    with pytest.raises(DispatchClaimError, match="COORDINATOR_CLOSED"):
        c.discard_snapshot(before)
    with pytest.raises(DispatchClaimError, match="COORDINATOR_CLOSED"):
        handle.finish_unavailable(writer)


def test_atomic_attach_stays_active_through_racing_ready_until_bound():
    c = _ready()
    existing = _candidate(c, "existing")
    handle, attachment = c.attach_writer_handle(
        "source", account="account", owner_generation="owner"
    )
    # A READY result from another writer cannot publish while attachment is open.
    racing = c.begin_change("source")
    c.finish_change(racing, "READY")
    with pytest.raises(DispatchClaimError, match="DOMAIN_UNAVAILABLE"):
        c.capture()
    with pytest.raises(DispatchClaimError, match="DOMAIN_UNAVAILABLE"):
        c.try_claim(existing)
    handle.finish_unavailable(attachment)
    with pytest.raises(DispatchClaimError, match="DOMAIN_UNAVAILABLE"):
        c.capture()
    # Only the trusted owner may later assert that all sources are ready.
    ready = c.begin_change("source")
    c.finish_change(ready, "READY")
    with pytest.raises(DispatchClaimError, match="CANDIDATE_STALE"):
        c.try_claim(existing)
    assert c.try_claim(_candidate(c, "after-attach"))


def test_atomic_attach_rejects_other_handle_and_forged_tokens_then_poison():
    c = _ready()
    other = c.writer_handle("source", account="account", owner_generation="owner")
    handle, attachment = c.attach_writer_handle(
        "source", account="account", owner_generation="owner"
    )
    forged = _WriterChange(other, attachment.token)
    with pytest.raises(DispatchClaimError, match="INVALID_CHANGE"):
        other.finish_unavailable(forged)
    with pytest.raises(DispatchClaimError, match="INVALID_CHANGE"):
        c.finish_change(attachment.token, "READY")
    with pytest.raises(DispatchClaimError, match="DOMAIN_UNAVAILABLE"):
        c.capture()
    handle.poison(attachment)
    with pytest.raises(DispatchClaimError, match="DOMAIN_POISONED"):
        handle.begin_change()
    with pytest.raises(DispatchClaimError, match="DOMAIN_UNAVAILABLE"):
        c.capture()


def test_atomic_attach_checks_owner_capacity_and_production_remains_closed():
    c = ClaimFence("account", "owner", domains=("source",), schema=SCHEMA,
                   max_snapshots=2)
    with pytest.raises(DispatchClaimError, match="OWNER_MISMATCH"):
        c.attach_writer_handle("source", account="other", owner_generation="owner")
    for _ in range(2):
        handle, token = c.attach_writer_handle(
            "source", account="account", owner_generation="owner"
        )
        handle.finish_unavailable(token)
    with pytest.raises(DispatchClaimError, match="HANDLE_CAPACITY"):
        c.attach_writer_handle("source", account="account", owner_generation="owner")
    assert c.capacity_status()["writer_handles"] == 2
    with pytest.raises(DispatchClaimError, match="COVERAGE_UNAVAILABLE"):
        c.capture()


def test_atomic_attach_and_claim_have_one_linearization_order():
    import threading

    for number in range(50):
        c = _ready()
        candidate = _candidate(c, f"concurrent-{number}")
        barrier = threading.Barrier(2)
        outcome = []
        attachment = []

        def attach():
            barrier.wait()
            attachment.append(c.attach_writer_handle(
                "source", account="account", owner_generation="owner"
            ))

        def claim():
            barrier.wait()
            try:
                c.try_claim(candidate)
                outcome.append("in-flight")
            except DispatchClaimError as error:
                outcome.append(error.code)

        a, b = threading.Thread(target=attach), threading.Thread(target=claim)
        a.start()
        b.start()
        a.join(2)
        b.join(2)
        assert not a.is_alive() and not b.is_alive()
        assert len(attachment) == len(outcome) == 1
        assert outcome[0] in ("in-flight", "DOMAIN_UNAVAILABLE")
        handle, token = attachment[0]
        handle.finish_unavailable(token)
        with pytest.raises(DispatchClaimError, match="DOMAIN_UNAVAILABLE"):
            c.capture()


@pytest.mark.parametrize("error", [RuntimeError("storage failure"), DispatchClaimError("INJECTED")])
def test_partial_discard_faults_core_before_raw_claim_can_run(monkeypatch, error):
    import threading

    c = _ready()
    candidate = _candidate(c, "pending")
    before, after = c.capture(), c.capture()
    real_take = ClaimFence._take_snapshot_locked
    entered, release, claim_started = threading.Event(), threading.Event(), threading.Event()
    outcomes = []
    count = 0

    def injected(core, snapshot):
        nonlocal count
        count += 1
        if count == 2:
            entered.set()
            assert release.wait(2)
            raise error
        return real_take(core, snapshot)

    def discard():
        try:
            c.discard_pair(before, after)
        except BaseException as failure:
            outcomes.append(("discard", failure))

    def claim():
        claim_started.set()
        try:
            c.try_claim(candidate)
            outcomes.append(("claim", "sent"))
        except DispatchClaimError as failure:
            outcomes.append(("claim", failure.code))

    # Instrumentation deliberately injects an exception in the critical section;
    # production core operations use only internal exact types and builtins.
    monkeypatch.setattr(ClaimFence, "_take_snapshot_locked", injected)
    a = threading.Thread(target=discard)
    b = threading.Thread(target=claim)
    a.start()
    try:
        assert entered.wait(2)
        b.start()
        assert claim_started.wait(2)
    finally:
        release.set()
        a.join(2)
        if b.ident is not None:
            b.join(2)
    assert not a.is_alive() and not b.is_alive()
    assert ("claim", "COORDINATOR_FAILED") in outcomes
    assert any(kind == "discard" and failure is error for kind, failure in outcomes)
    with pytest.raises(DispatchClaimError, match="COORDINATOR_FAILED"):
        c.capture()
    c.close()
    with pytest.raises(DispatchClaimError, match="COORDINATOR_CLOSED"):
        c.try_claim(candidate)


def test_fault_mark_before_claim_fences_and_after_claim_keeps_inflight():
    before = _ready()
    pending = _candidate(before, "pending")
    before.mark_failed()
    before.mark_failed()  # Fault is irreversible and idempotent.
    with pytest.raises(DispatchClaimError, match="COORDINATOR_FAILED"):
        before.try_claim(pending)
    with pytest.raises(DispatchClaimError, match="COORDINATOR_FAILED"):
        before.begin_change("source")

    after = _ready()
    already = _candidate(after, "already")
    claim = after.try_claim(already)
    after.mark_failed()
    assert claim.binding == ("account", "owner", "already")
    with pytest.raises(DispatchClaimError, match="COORDINATOR_FAILED"):
        after.try_claim(already)


def test_outside_error_does_not_automatically_fault_core():
    c = _ready()
    candidate = _candidate(c, "outside")
    with pytest.raises(RuntimeError, match="external"):
        raise RuntimeError("external")
    # External callers must explicitly invoke mark_failed after such failures.
    assert c.try_claim(candidate)


@pytest.mark.parametrize("error", [RuntimeError("allocation"), DispatchClaimError("INTERNAL")])
def test_unexpected_token_creation_failure_faults_entire_core(monkeypatch, error):
    c = _ready()
    candidate = _candidate(c, "existing")

    def fail_after_epoch(core):
        raise error

    monkeypatch.setattr(ClaimFence, "_next", fail_after_epoch)
    with pytest.raises(type(error)) as captured:
        c.begin_change("source")
    assert captured.value is error
    with pytest.raises(DispatchClaimError, match="COORDINATOR_FAILED"):
        c.try_claim(candidate)
    c.close()


@pytest.mark.parametrize("failure", [RuntimeError("validator failure"), DispatchClaimError("INTERNAL")])
def test_unexpected_schema_validation_error_faults_raw_core(monkeypatch, failure):
    c = _ready()
    pending = _candidate(c, "existing")
    before, after = c.capture(), c.capture()

    def broken(*args):
        raise failure

    monkeypatch.setattr(ClaimSchema, "validate", broken)
    with pytest.raises(type(failure)) as captured:
        c._prepare_values(("account", "owner", "next"), before, after,
                          deadline_ns=time.monotonic_ns() + 1_000_000_000)
    assert captured.value is failure
    with pytest.raises(DispatchClaimError, match="COORDINATOR_FAILED"):
        c.try_claim(pending)


def test_schema_rejection_releases_only_owned_tickets_without_fault():
    c, foreign = _ready(), _ready()
    candidate = _candidate(c, "existing")
    local, outside = c.capture(), foreign.capture()
    with pytest.raises(DispatchClaimError, match="OWNER_MISMATCH"):
        c._prepare_values(("other", "owner", "next"), local, outside,
                          deadline_ns=time.monotonic_ns() + 1_000_000_000)
    assert c.capacity_status()["snapshots"] == 0
    foreign.discard_snapshot(outside)
    assert c.try_claim(candidate)


def test_schema_failure_mark_follows_a_claim_already_inflight(monkeypatch):
    import threading

    c = _ready()
    prior = _candidate(c, "prior")
    before, after = c.capture(), c.capture()
    entered, release = threading.Event(), threading.Event()
    errors = []

    def broken(*args):
        entered.set()
        assert release.wait(2)
        raise RuntimeError("validator failure")

    def run_prepare():
        try:
            c._prepare_values(("account", "owner", "next"), before, after,
                              deadline_ns=time.monotonic_ns() + 1_000_000_000)
        except BaseException as error:
            errors.append(error)

    monkeypatch.setattr(ClaimSchema, "validate", broken)
    worker = threading.Thread(target=run_prepare)
    worker.start()
    try:
        assert entered.wait(2)
        assert c.try_claim(prior).binding == ("account", "owner", "prior")
    finally:
        release.set()
        worker.join(2)
    assert not worker.is_alive() and len(errors) == 1
    assert isinstance(errors[0], RuntimeError)
    with pytest.raises(DispatchClaimError, match="COORDINATOR_FAILED"):
        c.try_claim(prior)


def test_schema_and_fault_mark_double_failure_keeps_original_and_reports_gap(monkeypatch):
    c = _ready()
    candidate = _candidate(c, "pending")
    before, after = c.capture(), c.capture()
    original = RuntimeError("validator failure")

    def fail_schema(*args):
        raise original

    def fail_mark(*args):
        raise RuntimeError("cannot acquire core lock")

    monkeypatch.setattr(ClaimSchema, "validate", fail_schema)
    monkeypatch.setattr(ClaimFence, "mark_failed", fail_mark)
    with pytest.raises(RuntimeError) as captured:
        c._prepare_values(("account", "owner", "new"), before, after,
                          deadline_ns=time.monotonic_ns() + 1_000_000_000)
    assert captured.value is original
    assert original.claim_fence_mark_failed is True
    # This injected double failure cannot guarantee a global fence. A trusted
    # owner must stop dispatch and retain the original in-flight identity.
    assert c.try_claim(candidate)
