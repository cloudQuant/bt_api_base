"""Owner-local claim fence primitives. They do not establish authorization.

Normal construction cannot publish READY or issue claims. Trusted composition,
source coverage, persisted intent, recovery and provider identity are external.
The private test constructor is synthetic only, never a production enabler.
"""
from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass

_READY = "READY"
_UNAVAILABLE = "UNAVAILABLE"
_NOT_SELECTED = "NOT_SELECTED"
_TEST_ISSUER = object()


class DispatchClaimError(RuntimeError):
    """Finite failure code; it does not authorize a native call."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _ExpectedRefusal(DispatchClaimError):
    """Internal marker for predeclared, non-fault rejections."""


def _text(value: object) -> bool:
    return type(value) is str and 0 < len(value) <= 512 and value == value.strip() and value.isprintable()


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True, eq=False)
class ClaimSchema:
    """Declarative built-in-only identity validation; not source authority."""

    __slots__ = ("fields", "account_index", "owner_index", "key_indices", "pairs")
    fields: tuple
    account_index: int
    owner_index: int
    key_indices: tuple
    pairs: tuple

    def __init__(self, fields: tuple, account_index: int, owner_index: int,
                 key_indices: tuple, pairs: tuple = ()):
        kinds = ("text", "hex256", "optional_text")
        if (type(fields) is not tuple or not fields
                or any(type(v) is not str or v not in kinds for v in fields)
                or type(account_index) is not int or type(owner_index) is not int
                or not 0 <= account_index < len(fields) or not 0 <= owner_index < len(fields)
                or account_index == owner_index
                or fields[account_index] != "text" or fields[owner_index] != "text"
                or type(key_indices) is not tuple or not key_indices
                or any(type(i) is not int or not 0 <= i < len(fields)
                       or fields[i] != "text" for i in key_indices)
                or len(set(key_indices)) != len(key_indices)
                or type(pairs) is not tuple
                or any(type(pair) is not tuple or len(pair) != 2
                       or any(type(i) is not int or not 0 <= i < len(fields)
                              or fields[i] != "optional_text" for i in pair)
                       or pair[0] == pair[1] for pair in pairs)):
            raise DispatchClaimError("INVALID_SCHEMA")
        object.__setattr__(self, "fields", tuple(v for v in fields))
        object.__setattr__(self, "account_index", account_index)
        object.__setattr__(self, "owner_index", owner_index)
        object.__setattr__(self, "key_indices", tuple(i for i in key_indices))
        object.__setattr__(self, "pairs", tuple((a, b) for a, b in pairs))

    def validate(self, values: object, account: str, owner_generation: str):
        if type(self) is not ClaimSchema or type(values) is not tuple or len(values) != len(self.fields):
            raise _ExpectedRefusal("INVALID_CANDIDATE")
        for kind, value in zip(self.fields, values):
            if kind == "text" and not _text(value):
                raise _ExpectedRefusal("INVALID_CANDIDATE")
            if kind == "hex256" and (type(value) is not str or _SHA256.fullmatch(value) is None):
                raise _ExpectedRefusal("INVALID_CANDIDATE")
            if kind == "optional_text" and value is not None and not _text(value):
                raise _ExpectedRefusal("INVALID_CANDIDATE")
        if any((values[a] is None) != (values[b] is None) for a, b in self.pairs):
            raise _ExpectedRefusal("INVALID_CANDIDATE")
        if values[self.account_index] != account or values[self.owner_index] != owner_generation:
            raise _ExpectedRefusal("OWNER_MISMATCH")
        return tuple(values[i] for i in self.key_indices)


@dataclass(frozen=True, eq=False)
class _Change:
    __slots__ = ('domain', 'sequence', '_seal')
    domain: str
    sequence: int
    _seal: object


@dataclass(frozen=True, eq=False)
class _Snapshot:
    __slots__ = ('sequence', 'versions', 'captured_ns', '_seal')
    sequence: int
    versions: tuple[tuple[str, int, str], ...]
    captured_ns: int
    _seal: object

    def __copy__(self):
        return _Snapshot(self.sequence, self.versions, self.captured_ns, self._seal)


@dataclass(frozen=True, eq=False)
class _Candidate:
    __slots__ = ('sequence', 'binding', 'versions', 'deadline_ns', '_seal')
    sequence: int
    binding: tuple
    versions: tuple[tuple[str, int, str], ...]
    deadline_ns: int
    _seal: object


@dataclass(frozen=True, eq=False)
class DispatchClaim:
    __slots__ = ('binding', 'claimed_ns', '_seal')
    """One successful in-process claim; never a venue or durable receipt."""

    binding: tuple
    claimed_ns: int
    _seal: object


class ClaimFence:
    """Shared version and once-only claim state; owner supplies fixed domains."""

    def __init_subclass__(cls, **kwargs):
        raise TypeError("ClaimFence is a final internal core")

    def __init__(self, account: str, owner_generation: str, *, domains: tuple, schema: ClaimSchema,
                 optional_domains: tuple = (), max_commands: int = 4096,
                 max_snapshots: int = 4096, max_validity_ns: int = 2_000_000_000):
        ClaimFence._initialize(self, account, owner_generation, max_commands, max_snapshots,
                               max_validity_ns, issuer=None, domains=domains, schema=schema,
                               optional_domains=optional_domains)

    @classmethod
    def _for_test(cls, account: str, owner_generation: str, *, domains: tuple, schema: ClaimSchema,
                  optional_domains: tuple = (), max_commands: int = 4096,
                  max_snapshots: int = 4096, max_validity_ns: int = 2_000_000_000):
        instance = cls.__new__(cls)
        ClaimFence._initialize(instance, account, owner_generation, max_commands, max_snapshots,
                               max_validity_ns, issuer=_TEST_ISSUER, domains=domains, schema=schema,
                               optional_domains=optional_domains)
        return instance

    def _initialize(self, account, owner_generation, max_commands, max_snapshots,
                    max_validity_ns, *, issuer, domains, optional_domains, schema):
        if (type(self) is not ClaimFence or type(schema) is not ClaimSchema
                or not _text(account) or not _text(owner_generation)
                or type(max_commands) is not int or not 1 <= max_commands <= 100_000
                or type(max_snapshots) is not int or not 2 <= max_snapshots <= 100_000
                or type(max_validity_ns) is not int or not 1 <= max_validity_ns <= 2_000_000_000
                or issuer not in (None, _TEST_ISSUER)
                or type(domains) is not tuple or not domains
                or any(not _text(name) for name in domains) or len(set(domains)) != len(domains)
                or type(optional_domains) is not tuple
                or any(type(name) is not str or name not in domains for name in optional_domains)
                or len(set(optional_domains)) != len(optional_domains)):
            raise DispatchClaimError("INVALID_COORDINATOR")
        self._account, self._generation, self._pid = account, owner_generation, os.getpid()
        self._domain_names = tuple(name for name in domains)
        self._optional_domains = tuple(name for name in optional_domains)
        self._schema = ClaimSchema(schema.fields, schema.account_index, schema.owner_index,
                                   schema.key_indices, schema.pairs)
        self._test_only = issuer is _TEST_ISSUER
        self._max_commands, self._max_snapshots = max_commands, max_snapshots
        self._max_validity_ns = max_validity_ns
        self._seal, self._lock = object(), threading.Lock()
        self._closed = False
        self._faulted = False
        self._sequence = 0
        # Each domain is [epoch, status, active tokens, merged result, poisoned].
        self._domains = {name: [0, _UNAVAILABLE, {}, None, False] for name in self._domain_names}
        self._snapshots, self._snapshot_ids = {}, {}
        self._commands, self._candidates = {}, {}
        self._writer_handles, self._writer_changes = {}, {}

    def _process(self) -> None:
        # Check before acquiring any inherited lock: locks can remain held after fork.
        if type(self) is not ClaimFence:
            raise DispatchClaimError("INVALID_COORDINATOR")
        if os.getpid() != self._pid:
            raise DispatchClaimError("COORDINATOR_PROCESS_CHANGED")

    def _active(self) -> None:
        if self._closed:
            raise _ExpectedRefusal("COORDINATOR_CLOSED")
        if self._faulted:
            raise _ExpectedRefusal("COORDINATOR_FAILED")

    def mark_failed(self) -> None:
        """Irreversibly fail this core under the same lock used by claim.

        External callers may use this after detecting a failure outside this
        core. Failure to acquire the lock or process termination cannot be
        fenced by this in-memory primitive.
        """
        ClaimFence._process(self)
        with self._lock:
            self._faulted = True

    def _mark_failed_preserving(self, original: BaseException) -> None:
        try:
            ClaimFence.mark_failed(self)
        except BaseException:
            # Keep the original error while exposing that the global fence
            # itself did not complete. Some exception types reject attributes.
            try:
                original.claim_fence_mark_failed = True
                if hasattr(original, "add_note"):
                    original.add_note("claim fence could not mark its core failed")
            except BaseException:
                pass

    def _next(self) -> int:
        self._sequence += 1
        return self._sequence

    def matches_owner(self, account: object, owner_generation: object) -> bool:
        ClaimFence._process(self)
        return (type(account) is str and type(owner_generation) is str
                and account == self._account and owner_generation == self._generation)

    def begin_change(self, domain: str) -> _Change:
        ClaimFence._process(self)
        if type(domain) is not str or domain not in self._domain_names:
            raise DispatchClaimError("INVALID_DOMAIN")
        with self._lock:
            try:
                ClaimFence._active(self)
                state = self._domains[domain]
                if state[4]:
                    raise _ExpectedRefusal("DOMAIN_POISONED")
                if len(state[2]) >= self._max_snapshots:
                    ClaimFence._poison_locked(self, state)
                    raise _ExpectedRefusal("CHANGE_CAPACITY")
                state[0] += 1
                token = _Change(domain, ClaimFence._next(self), self._seal)
                state[2][token.sequence] = token
                return token

            except _ExpectedRefusal as failure:
                raise DispatchClaimError(failure.code) from None
            except BaseException:
                self._faulted = True
                raise

    def finish_change(self, token: _Change, status: str) -> None:
        ClaimFence._process(self)
        if type(token) is not _Change:
            raise DispatchClaimError("INVALID_CHANGE")
        domain, sequence, seal = token.domain, token.sequence, token._seal
        if (type(domain) is not str or domain not in self._domain_names or type(sequence) is not int
                or seal is not self._seal or type(status) is not str
                or status not in (_READY, _UNAVAILABLE, _NOT_SELECTED)
                or (status == _NOT_SELECTED and domain not in self._optional_domains)):
            raise DispatchClaimError("INVALID_CHANGE")
        with self._lock:
            try:
                ClaimFence._active(self)
                state = self._domains[domain]
                if (state[4] or state[2].get(sequence) is not token
                        or sequence in self._writer_changes):
                    raise _ExpectedRefusal("INVALID_CHANGE")
                del state[2][sequence]
                # A public status cannot certify source coverage.  Without a real
                # coverage capability, READY is refused even after a mutation.
                no_coverage = status == _READY and not self._test_only
                result = _UNAVAILABLE if no_coverage else status
                state[3] = result if state[3] is None else (
                    result if state[3] == result else _UNAVAILABLE
                )
                if not state[2]:
                    state[1] = state[3]
                    state[3] = None
                if no_coverage:
                    raise _ExpectedRefusal("COVERAGE_UNAVAILABLE")

            except _ExpectedRefusal as failure:
                raise DispatchClaimError(failure.code) from None
            except BaseException:
                self._faulted = True
                raise

    def poison(self, token: _Change) -> None:
        ClaimFence._process(self)
        if type(token) is not _Change:
            raise DispatchClaimError("INVALID_CHANGE")
        domain, sequence, seal = token.domain, token.sequence, token._seal
        if (type(domain) is not str or domain not in self._domain_names
                or type(sequence) is not int or seal is not self._seal):
            raise DispatchClaimError("INVALID_CHANGE")
        with self._lock:
            try:
                ClaimFence._active(self)
                state = self._domains[domain]
                if state[2].get(sequence) is not token or sequence in self._writer_changes:
                    raise _ExpectedRefusal("INVALID_CHANGE")
                ClaimFence._poison_locked(self, state)

            except _ExpectedRefusal as failure:
                raise DispatchClaimError(failure.code) from None
            except BaseException:
                self._faulted = True
                raise

    def poison_domain(self, domain: str) -> None:
        """Irreversibly close a domain after an integration or publication error."""
        ClaimFence._process(self)
        if type(domain) is not str or domain not in self._domain_names:
            raise DispatchClaimError("INVALID_DOMAIN")
        with self._lock:
            try:
                ClaimFence._active(self)
                ClaimFence._poison_locked(self, self._domains[domain])

            except _ExpectedRefusal as failure:
                raise DispatchClaimError(failure.code) from None
            except BaseException:
                self._faulted = True
                raise

    def _poison_locked(self, state: list) -> None:
        for sequence in state[2]:
            self._writer_changes.pop(sequence, None)
        state[0] += 1
        state[1], state[4] = _UNAVAILABLE, True
        state[2].clear()
        state[3] = None

    def _versions_locked(self) -> tuple[tuple[str, int, str], ...]:
        if not self._test_only:
            raise _ExpectedRefusal("COVERAGE_UNAVAILABLE")
        vector = []
        for name in self._domain_names:
            epoch, status, active, _, poisoned = self._domains[name]
            if (poisoned or active or status not in (_READY, _NOT_SELECTED)
                    or (status == _NOT_SELECTED and name not in self._optional_domains)):
                raise _ExpectedRefusal("DOMAIN_UNAVAILABLE")
            vector.append((name, epoch, status))
        return tuple(vector)

    def capture(self) -> _Snapshot:
        """Capture a sealed version vector before or after external validation."""
        ClaimFence._process(self)
        with self._lock:
            try:
                ClaimFence._active(self)
                versions = ClaimFence._versions_locked(self)
                if len(self._snapshots) >= self._max_snapshots:
                    raise _ExpectedRefusal("SNAPSHOT_CAPACITY")
                snapshot = _Snapshot(ClaimFence._next(self), versions, time.monotonic_ns(), self._seal)
                self._snapshots[snapshot.sequence] = (snapshot, versions, snapshot.captured_ns)
                self._snapshot_ids[id(snapshot)] = snapshot.sequence
                return snapshot

            except _ExpectedRefusal as failure:
                raise DispatchClaimError(failure.code) from None
            except BaseException:
                self._faulted = True
                raise

    def _take_snapshot_locked(self, snapshot: object):
        """Consume only this instance's exact issued object, not a lookalike."""
        if type(snapshot) is not _Snapshot:
            return None
        identity = id(snapshot)
        sequence = self._snapshot_ids.get(identity)
        entry = self._snapshots.get(sequence) if sequence is not None else None
        if entry is None or entry[0] is not snapshot:
            return None
        del self._snapshot_ids[identity]
        del self._snapshots[sequence]
        return sequence, entry

    def _take_pair_locked(self, before: object, after: object):
        # Even a failure after consuming the first ticket invalidates the
        # entire core before the common lock is released.
        try:
            return (ClaimFence._take_snapshot_locked(self, before),
                    ClaimFence._take_snapshot_locked(self, after))
        except BaseException:
            self._faulted = True
            raise

    def discard_snapshot(self, snapshot: _Snapshot) -> None:
        ClaimFence._process(self)
        if type(snapshot) is not _Snapshot:
            raise DispatchClaimError("INVALID_SNAPSHOT")
        with self._lock:
            try:
                ClaimFence._active(self)
                try:
                    taken = ClaimFence._take_snapshot_locked(self, snapshot)
                except BaseException:
                    self._faulted = True
                    raise
                if taken is None:
                    raise _ExpectedRefusal("INVALID_SNAPSHOT")

            except _ExpectedRefusal as failure:
                raise DispatchClaimError(failure.code) from None
            except BaseException:
                self._faulted = True
                raise

    def discard_pair(self, before: object, after: object) -> tuple[bool, bool]:
        """Atomically discard owned tickets, reporting which were still live.

        This assists callers whose validation fails before ``prepare``. Forged,
        foreign, already consumed, or absent values are left untouched and
        reported as False. Process changes and coordinator closure still fail.
        """
        ClaimFence._process(self)
        with self._lock:
            try:
                ClaimFence._active(self)
                before_taken, after_taken = ClaimFence._take_pair_locked(self, before, after)
                return before_taken is not None, after_taken is not None

            except _ExpectedRefusal as failure:
                raise DispatchClaimError(failure.code) from None
            except BaseException:
                self._faulted = True
                raise

    def _prepare_values(self, values: tuple, before: object, after: object, *, deadline_ns: int):
        """Consume tickets on ordinary rejection; fault on unexpected validation errors.

        A failure outside the common lock is ordered when ``mark_failed``
        acquires it. A claim already completed before that point remains in
        flight; callers must fence source mutations before beginning them.
        """
        ClaimFence._process(self)
        try:
            command_key = ClaimSchema.validate(self._schema, values, self._account, self._generation)
            if (type(before) is not _Snapshot or type(after) is not _Snapshot
                    or type(deadline_ns) is not int):
                raise _ExpectedRefusal("INVALID_CANDIDATE")
            before_sequence, after_sequence = before.sequence, after.sequence
            if (type(before_sequence) is not int or type(after_sequence) is not int
                    or before._seal is not self._seal or after._seal is not self._seal):
                raise _ExpectedRefusal("INVALID_CANDIDATE")
        except _ExpectedRefusal as failure:
            original = DispatchClaimError(failure.code)
            try:
                ClaimFence.discard_pair(self, before, after)
            except BaseException:
                # Cleanup may fail before entering the core; preserve the
                # original refusal while attempting an irreversible fence.
                ClaimFence._mark_failed_preserving(self, original)
            raise original from None
        except BaseException as failure:
            # This is outside the core lock; a competing claim may already win.
            ClaimFence._mark_failed_preserving(self, failure)
            raise
        with self._lock:
            try:
                ClaimFence._active(self)
                before_taken, after_taken = ClaimFence._take_pair_locked(self, before, after)
                if (before_taken is None or after_taken is None
                        or before_taken[0] != before_sequence or after_taken[0] != after_sequence):
                    raise _ExpectedRefusal("CANDIDATE_STALE")
                versions = ClaimFence._versions_locked(self)
                now = time.monotonic_ns()
                before_saved, after_saved = before_taken[1], after_taken[1]
                if (before_sequence >= after_sequence or before_saved[1] != after_saved[1]
                        or after_saved[1] != versions or deadline_ns <= now
                        or deadline_ns > before_saved[2] + self._max_validity_ns):
                    raise _ExpectedRefusal("CANDIDATE_STALE")
                if command_key in self._commands:
                    raise _ExpectedRefusal("COMMAND_ALREADY_PREPARED")
                if len(self._commands) >= self._max_commands:
                    raise _ExpectedRefusal("COMMAND_CAPACITY")
                candidate = _Candidate(ClaimFence._next(self), values, versions, deadline_ns, self._seal)
                self._commands[command_key] = [candidate, "PREPARED", values, versions, deadline_ns]
                self._candidates[candidate.sequence] = (candidate, command_key)
                return candidate

            except _ExpectedRefusal as failure:
                raise DispatchClaimError(failure.code) from None
            except BaseException:
                self._faulted = True
                raise

    def writer_handle(self, domain: str, *, account: str, owner_generation: str):
        """Atomically invalidate and register a domain-bound writer capability."""
        ClaimFence._process(self)
        if (type(domain) is not str or domain not in self._domain_names
                or type(account) is not str or type(owner_generation) is not str
                or account != self._account or owner_generation != self._generation):
            raise DispatchClaimError("OWNER_MISMATCH")
        with self._lock:
            try:
                ClaimFence._active(self)
                state = self._domains[domain]
                if state[4] or state[2]:
                    raise _ExpectedRefusal("DOMAIN_UNAVAILABLE")
                if len(self._writer_handles) >= self._max_snapshots:
                    state[0] += 1
                    state[1] = _UNAVAILABLE
                    raise _ExpectedRefusal("HANDLE_CAPACITY")
                state[0] += 1
                state[1] = _UNAVAILABLE
                handle = ClaimFenceWriter(self, domain, account, owner_generation, self._seal)
                self._writer_handles[id(handle)] = (handle, domain)
                return handle

            except _ExpectedRefusal as failure:
                raise DispatchClaimError(failure.code) from None
            except BaseException:
                self._faulted = True
                raise

    def attach_writer_handle(self, domain: str, *, account: str, owner_generation: str):
        """Issue a writer with an active attach token under the same short lock.

        The caller must finish the returned token through the returned handle
        after binding, or poison it on failure. Until then the domain cannot be
        used to claim, even if another writer reports READY. This is a local
        invalidation primitive, not proof of source, authority or coverage.
        """
        ClaimFence._process(self)
        if (type(domain) is not str or type(account) is not str
                or type(owner_generation) is not str):
            raise DispatchClaimError("OWNER_MISMATCH")
        with self._lock:
            try:
                ClaimFence._active(self)
                if (domain not in self._domain_names or account != self._account
                        or owner_generation != self._generation):
                    raise _ExpectedRefusal("OWNER_MISMATCH")
                state = self._domains[domain]
                if state[4] or state[2]:
                    raise _ExpectedRefusal("DOMAIN_UNAVAILABLE")
                if len(self._writer_handles) >= self._max_snapshots:
                    state[0] += 1
                    state[1] = _UNAVAILABLE
                    raise _ExpectedRefusal("HANDLE_CAPACITY")
                state[0] += 1
                state[1] = _UNAVAILABLE
                handle = None
                try:
                    handle = ClaimFenceWriter(self, domain, account, owner_generation, self._seal)
                    token = _Change(domain, ClaimFence._next(self), self._seal)
                    wrapper = _WriterChange(handle, token)
                    self._writer_handles[id(handle)] = (handle, domain)
                    state[2][token.sequence] = token
                    self._writer_changes[token.sequence] = (handle, token, wrapper)
                except BaseException:
                    self._faulted = True
                    if handle is not None:
                        self._writer_handles.pop(id(handle), None)
                    ClaimFence._poison_locked(self, state)
                    raise
                return handle, wrapper

            except _ExpectedRefusal as failure:
                raise DispatchClaimError(failure.code) from None
            except BaseException:
                self._faulted = True
                raise

    def _writer_registered_locked(self, handle):
        if type(handle) is not ClaimFenceWriter:
            raise _ExpectedRefusal("INVALID_HANDLE")
        entry = self._writer_handles.get(id(handle))
        if entry is None or entry[0] is not handle:
            raise _ExpectedRefusal("INVALID_HANDLE")
        return entry[1]

    def _writer_begin(self, handle):
        ClaimFence._process(self)
        with self._lock:
            try:
                ClaimFence._active(self)
                domain = ClaimFence._writer_registered_locked(self, handle)
                state = self._domains[domain]
                if state[4]:
                    raise _ExpectedRefusal("DOMAIN_POISONED")
                if len(state[2]) >= self._max_snapshots:
                    ClaimFence._poison_locked(self, state)
                    raise _ExpectedRefusal("CHANGE_CAPACITY")
                state[0] += 1
                token = _Change(domain, ClaimFence._next(self), self._seal)
                state[2][token.sequence] = token
                wrapper = _WriterChange(handle, token)
                self._writer_changes[token.sequence] = (handle, token, wrapper)
                return wrapper

            except _ExpectedRefusal as failure:
                raise DispatchClaimError(failure.code) from None
            except BaseException:
                self._faulted = True
                raise

    def _writer_finish(self, handle, wrapper, poison: bool):
        ClaimFence._process(self)
        if type(wrapper) is not _WriterChange or type(poison) is not bool:
            raise DispatchClaimError("INVALID_CHANGE")
        with self._lock:
            try:
                ClaimFence._active(self)
                domain = ClaimFence._writer_registered_locked(self, handle)
                token = wrapper.token
                if type(token) is not _Change or type(token.sequence) is not int:
                    raise _ExpectedRefusal("INVALID_CHANGE")
                entry = self._writer_changes.get(token.sequence)
                state = self._domains[domain]
                if (entry is None or entry[0] is not handle or entry[1] is not token
                        or entry[2] is not wrapper or wrapper.handle is not handle
                        or state[2].get(token.sequence) is not token or state[4]):
                    raise _ExpectedRefusal("INVALID_CHANGE")
                del self._writer_changes[token.sequence]
                if poison:
                    ClaimFence._poison_locked(self, state)
                    return
                del state[2][token.sequence]
                state[3] = _UNAVAILABLE
                if not state[2]:
                    state[1] = _UNAVAILABLE
                    state[3] = None

            except _ExpectedRefusal as failure:
                raise DispatchClaimError(failure.code) from None
            except BaseException:
                self._faulted = True
                raise

    def _writer_matches(self, handle, coordinator, domain, account, owner_generation):
        ClaimFence._process(self)
        if (coordinator is not self or type(domain) is not str or type(account) is not str
                or type(owner_generation) is not str):
            return False
        with self._lock:
            try:
                ClaimFence._active(self)
                try:
                    bound_domain = ClaimFence._writer_registered_locked(self, handle)
                except _ExpectedRefusal:
                    return False
                return (domain == bound_domain and account == self._account
                        and owner_generation == self._generation)

            except _ExpectedRefusal as failure:
                raise DispatchClaimError(failure.code) from None
            except BaseException:
                self._faulted = True
                raise

    def try_claim(self, candidate: _Candidate) -> DispatchClaim:
        """Atomically claim once; never invokes a callback, journal or provider."""
        ClaimFence._process(self)
        if type(candidate) is not _Candidate:
            raise DispatchClaimError("INVALID_CANDIDATE")
        sequence, seal = candidate.sequence, candidate._seal
        if type(sequence) is not int or seal is not self._seal:
            raise DispatchClaimError("INVALID_CANDIDATE")
        with self._lock:
            try:
                ClaimFence._active(self)
                versions = ClaimFence._versions_locked(self)
                entry = self._candidates.get(sequence)
                if entry is None or entry[0] is not candidate:
                    raise _ExpectedRefusal("INVALID_CANDIDATE")
                saved = self._commands.get(entry[1])
                if saved is None or saved[0] is not candidate:
                    raise _ExpectedRefusal("INVALID_CANDIDATE")
                if saved[1] != "PREPARED":
                    raise _ExpectedRefusal("ALREADY_CLAIMED")
                now = time.monotonic_ns()
                if saved[3] != versions or now >= saved[4]:
                    raise _ExpectedRefusal("CANDIDATE_STALE")
                saved[1] = "IN_FLIGHT"
                return DispatchClaim(saved[2], now, self._seal)

            except _ExpectedRefusal as failure:
                raise DispatchClaimError(failure.code) from None
            except BaseException:
                self._faulted = True
                raise

    def capacity_status(self) -> dict[str, int]:
        """Expose counts for monitoring; this neither evicts nor proves safety."""
        ClaimFence._process(self)
        with self._lock:
            try:
                ClaimFence._active(self)
                return {"commands": len(self._commands), "max_commands": self._max_commands,
                        "snapshots": len(self._snapshots), "max_snapshots": self._max_snapshots,
                        "writer_handles": len(self._writer_handles),
                        "max_writer_handles": self._max_snapshots}

            except _ExpectedRefusal as failure:
                raise DispatchClaimError(failure.code) from None
            except BaseException:
                self._faulted = True
                raise

    def close(self) -> None:
        ClaimFence._process(self)
        with self._lock:
            try:
                self._closed = True
                self._snapshots.clear()
                self._snapshot_ids.clear()
                self._commands.clear()
                self._candidates.clear()
                self._writer_handles.clear()
                self._writer_changes.clear()
                for state in self._domains.values():
                    state[1] = _UNAVAILABLE
                    state[2].clear()
                    state[3] = None


            except _ExpectedRefusal as failure:
                raise DispatchClaimError(failure.code) from None
            except BaseException:
                self._faulted = True
                raise
@dataclass(frozen=True, eq=False)
class _WriterChange:
    __slots__ = ('handle', 'token')
    handle: object
    token: _Change


@dataclass(frozen=True, eq=False)
class ClaimFenceWriter:
    """Domain-bound invalidation capability; cannot certify READY or grant claims.

    ``matches`` accepts the exact Base core, not an SDK composition wrapper.
    Handles remain registered until core close; exhaustion invalidates the domain.
    """

    __slots__ = ("_coordinator", "_domain", "_account", "_generation", "_seal")
    _coordinator: object
    _domain: str
    _account: str
    _generation: str
    _seal: object

    def __init__(self, coordinator, domain, account, generation, seal):
        if (type(coordinator) is not ClaimFence or seal is not coordinator._seal
                or type(domain) is not str or domain not in coordinator._domain_names
                or account != coordinator._account or generation != coordinator._generation):
            raise DispatchClaimError("INVALID_HANDLE")
        object.__setattr__(self, "_coordinator", coordinator)
        object.__setattr__(self, "_domain", domain)
        object.__setattr__(self, "_account", account)
        object.__setattr__(self, "_generation", generation)
        object.__setattr__(self, "_seal", seal)

    def matches(self, coordinator, *, domain: str, account: str, owner_generation: str) -> bool:
        return ClaimFence._writer_matches(self._coordinator, self, coordinator,
                                          domain, account, owner_generation)

    def begin_change(self):
        return ClaimFence._writer_begin(self._coordinator, self)

    def finish_unavailable(self, token):
        ClaimFence._writer_finish(self._coordinator, self, token, False)

    def poison(self, token):
        ClaimFence._writer_finish(self._coordinator, self, token, True)
