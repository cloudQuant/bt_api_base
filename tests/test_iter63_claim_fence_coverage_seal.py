"""Production coverage seal, READY publication and command retirement (synthetic)."""

import threading
import time

import pytest

from bt_api_base.claim_fence import ClaimFence, ClaimSchema, CoverageSealer, DispatchClaimError

SCHEMA = ClaimSchema(("text", "text", "text"), 0, 1, (0, 2))
DOMAINS = ("source", "control", "risk")


def _sealed(**coverage):
    core, sealer = ClaimFence.with_sealer("account", "owner", domains=DOMAINS, schema=SCHEMA,
                                          optional_domains=("risk",))
    sealer.seal(coverage or {"source": ("source-writer",), "control": ("control-writer",)},
                not_selected=("risk",))
    for domain in ("source", "control"):
        token = core.begin_change(domain)
        core.finish_change(token, "READY")
    return core


def _candidate(core, key, validity_ns=1_000_000_000):
    before, after = core.capture(), core.capture()
    return core._prepare_values(("account", "owner", key), before, after,
                                deadline_ns=time.monotonic_ns() + validity_ns)


def test_unsealed_production_core_stays_fail_closed():
    core, _sealer = ClaimFence.with_sealer("account", "owner", domains=DOMAINS, schema=SCHEMA,
                                           optional_domains=("risk",))
    token = core.begin_change("source")
    with pytest.raises(DispatchClaimError, match="COVERAGE_UNAVAILABLE"):
        core.finish_change(token, "READY")
    with pytest.raises(DispatchClaimError, match="COVERAGE_UNAVAILABLE"):
        core.capture()
    handle = core.writer_handle("control", account="account", owner_generation="owner")
    change = handle.begin_change()
    with pytest.raises(DispatchClaimError, match="COVERAGE_UNAVAILABLE"):
        handle.finish_ready(change)


def test_sealer_is_single_use_and_not_constructible_twice():
    core, sealer = ClaimFence.with_sealer("account", "owner", domains=DOMAINS, schema=SCHEMA,
                                          optional_domains=("risk",))
    with pytest.raises(DispatchClaimError, match="INVALID_SEALER"):
        CoverageSealer(core, core._seal)
    with pytest.raises(DispatchClaimError, match="INVALID_SEALER"):
        ClaimFence._seal_coverage(core, object(), {"source": ("a",), "control": ("b",)}, ("risk",))
    sealer.seal({"source": ("a",), "control": ("b",)}, not_selected=("risk",))
    with pytest.raises(DispatchClaimError, match="COVERAGE_SEALED"):
        sealer.seal({"source": ("a",), "control": ("b",)}, not_selected=("risk",))
    assert core.coverage_status()["sealed"] is True


@pytest.mark.parametrize("coverage,not_selected,code", [
    ({"source": ("a",)}, ("risk",), "COVERAGE_INCOMPLETE"),
    ({"source": ("a",), "control": ()}, ("risk",), "INVALID_COVERAGE"),
    ({"source": ("a",), "control": ("b",)}, ("control",), "INVALID_COVERAGE"),
    ({"source": ("a",), "control": ("b",), "risk": ("r",)}, ("risk",), "COVERAGE_INCOMPLETE"),
])
def test_seal_requires_every_selected_domain(coverage, not_selected, code):
    core, sealer = ClaimFence.with_sealer("account", "owner", domains=DOMAINS, schema=SCHEMA,
                                          optional_domains=("risk",))
    with pytest.raises(DispatchClaimError, match=code):
        sealer.seal(coverage, not_selected=not_selected)
    with pytest.raises(DispatchClaimError, match="COVERAGE_UNAVAILABLE"):
        core.capture()


def test_sealed_core_claims_and_fixes_not_selected_domains():
    core = _sealed()
    with pytest.raises(DispatchClaimError, match="DOMAIN_NOT_SELECTED"):
        core.begin_change("risk")
    token = core.begin_change("source")
    with pytest.raises(DispatchClaimError, match="INVALID_CHANGE"):
        core.finish_change(token, "NOT_SELECTED")  # only optional domains
    with pytest.raises(DispatchClaimError, match="DOMAIN_UNAVAILABLE"):
        core.capture()  # the change is still active
    core.finish_change(token, "READY")
    claim = core.try_claim(_candidate(core, "k1"))
    assert claim.binding == ("account", "owner", "k1")


def test_writer_handle_publishes_ready_after_seal_and_merges_concurrent_changes():
    core, sealer = ClaimFence.with_sealer("account", "owner", domains=DOMAINS, schema=SCHEMA,
                                          optional_domains=("risk",))
    source, attach = core.attach_writer_handle("source", account="account",
                                               owner_generation="owner")
    control = core.writer_handle("control", account="account", owner_generation="owner")
    sealer.seal({"source": ("source",), "control": ("control",)}, not_selected=("risk",))
    source.finish_ready(attach)
    first, second = control.begin_change(), control.begin_change()
    control.finish_ready(first)
    control.finish_unavailable(second)
    with pytest.raises(DispatchClaimError, match="DOMAIN_UNAVAILABLE"):
        core.capture()
    change = control.begin_change()
    control.finish_ready(change)
    assert core.try_claim(_candidate(core, "k"))


def test_revocation_before_claim_wins_and_after_claim_does_not_wait():
    core = _sealed()
    stale = _candidate(core, "a")
    revocation = core.begin_change("control")
    core.finish_change(revocation, "READY")
    with pytest.raises(DispatchClaimError, match="CANDIDATE_STALE"):
        core.try_claim(stale)

    live = _candidate(core, "b")
    claim = core.try_claim(live)
    done = threading.Event()

    def revoke():
        token = core.begin_change("control")
        core.finish_change(token, "UNAVAILABLE")
        done.set()

    # The claimed request stays in flight; revocation completes immediately.
    thread = threading.Thread(target=revoke)
    thread.start()
    assert done.wait(1.0)
    thread.join()
    assert claim.binding[2] == "b"
    with pytest.raises(DispatchClaimError, match="DOMAIN_UNAVAILABLE"):
        core.capture()


def test_retire_and_abandon_reclaim_capacity_without_reusing_claims():
    core, sealer = ClaimFence.with_sealer("account", "owner", domains=("source",),
                                          schema=SCHEMA, max_commands=1)
    sealer.seal({"source": ("w",)})
    token = core.begin_change("source")
    core.finish_change(token, "READY")
    prepared = _candidate(core, "x")
    with pytest.raises(DispatchClaimError, match="COMMAND_CAPACITY"):
        _candidate(core, "y")
    assert core.abandon(prepared) is True
    assert core.abandon(prepared) is False
    with pytest.raises(DispatchClaimError, match="INVALID_CANDIDATE"):
        core.try_claim(prepared)
    claim = core.try_claim(_candidate(core, "y"))
    with pytest.raises(DispatchClaimError, match="ALREADY_CLAIMED"):
        core.abandon(core._candidates[next(iter(core._candidates))][0])
    with pytest.raises(DispatchClaimError, match="COMMAND_CAPACITY"):
        _candidate(core, "z")
    core.retire(claim)
    with pytest.raises(DispatchClaimError, match="INVALID_CLAIM"):
        core.retire(claim)
    assert core.try_claim(_candidate(core, "z"))
    assert core.capacity_status()["commands"] == 1


def test_expired_candidate_cannot_be_claimed():
    core = _sealed()
    candidate = _candidate(core, "late", validity_ns=1_000_000)
    time.sleep(0.01)
    with pytest.raises(DispatchClaimError, match="CANDIDATE_STALE"):
        core.try_claim(candidate)
