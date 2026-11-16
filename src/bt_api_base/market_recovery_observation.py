"""Immutable local-process recovery observations, not source authentication.

Monotonic timestamps are comparable only in the originating process. These
values intentionally have no wire codec.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bt_api_base.market_protocol import MarketSubscriptionKey
from bt_api_base.service_protocol import MAX_REFERENCE_BYTES

_MAX_INT = (1 << 63) - 1
_UUID_HEX = re.compile(r"[0-9a-f]{32}\Z")
_STATES = frozenset({"RECOVERING", "RECOVERED", "FAILED", "UNKNOWN"})
_STATE_REASONS = {
    "RECOVERING": frozenset({"BEGIN", "WATERMARK"}),
    "RECOVERED": frozenset({"COMPLETED"}),
    "FAILED": frozenset({"FAILED"}),
    "UNKNOWN": frozenset(
        {"MEMBERS_CHANGED", "CLOSED", "REENTRY_FAILED", "SCOPE_CHANGED", "BEGIN_FAILED"}
    ),
}


def _integer(value: object, name: str, *, minimum: int = 1) -> None:
    if type(value) is not int or not minimum <= value <= _MAX_INT:
        raise ValueError(f"{name} is invalid")


def _uuid(value: object, name: str) -> None:
    if type(value) is not str or _UUID_HEX.fullmatch(value) is None:
        raise ValueError(f"{name} is invalid")


@dataclass(frozen=True)
class RecoveryObservationMember:
    key: MarketSubscriptionKey
    generation: str

    def __post_init__(self) -> None:
        if type(self.key) is not MarketSubscriptionKey:
            raise TypeError("key must be an exact MarketSubscriptionKey")
        generation = self.generation
        if (
            type(generation) is not str
            or not generation
            or generation != generation.strip()
            or not generation.isprintable()
        ):
            raise ValueError("generation is invalid")
        try:
            encoded = generation.encode("utf-8", errors="strict")
        except UnicodeError:
            raise ValueError("generation is invalid") from None
        if len(encoded) > MAX_REFERENCE_BYTES:
            raise ValueError("generation is invalid")


@dataclass(frozen=True)
class RecoveryCoverageObservation:
    source_epoch: str
    owner_pid: int
    sequence: int
    episode_id: str | None
    state: str
    reason: str
    observed_monotonic_ns: int
    coverage_started_monotonic_ns: int | None
    coverage_through_monotonic_ns: int | None
    origin_connection_generation: int | None
    observed_connection_generation: int | None
    members: tuple[RecoveryObservationMember, ...]

    def __post_init__(self) -> None:
        _uuid(self.source_epoch, "source_epoch")
        _integer(self.owner_pid, "owner_pid")
        _integer(self.sequence, "sequence")
        _integer(self.observed_monotonic_ns, "observed_monotonic_ns")
        if type(self.state) is not str or self.state not in _STATES:
            raise ValueError("state is invalid")
        if type(self.reason) is not str or self.reason not in _STATE_REASONS[self.state]:
            raise ValueError("reason is invalid")
        if self.episode_id is not None:
            _uuid(self.episode_id, "episode_id")
        for name in ("origin_connection_generation", "observed_connection_generation"):
            value = getattr(self, name)
            if value is not None:
                _integer(value, name)
        if self.state == "UNKNOWN":
            if (
                self.coverage_started_monotonic_ns is not None
                or self.coverage_through_monotonic_ns is not None
            ):
                raise ValueError("unknown observation cannot claim coverage")
        else:
            if self.episode_id is None or self.origin_connection_generation is None:
                raise ValueError("coverage requires an episode and origin")
            _integer(self.coverage_started_monotonic_ns, "coverage_started_monotonic_ns")
            _integer(self.coverage_through_monotonic_ns, "coverage_through_monotonic_ns")
            if not (
                self.coverage_started_monotonic_ns
                <= self.coverage_through_monotonic_ns
                <= self.observed_monotonic_ns
            ):
                raise ValueError("coverage interval is invalid")
        if type(self.members) is not tuple or len(self.members) > 1024:
            raise ValueError("members is invalid")
        if self.state != "UNKNOWN" and not self.members:
            raise ValueError("coverage requires members")
        if any(type(member) is not RecoveryObservationMember for member in self.members):
            raise TypeError("members must contain exact RecoveryObservationMember values")
        keys = tuple((member.key.stream_id, member.generation) for member in self.members)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("members must be sorted and unique")


@dataclass(frozen=True)
class RecoveryObservationPage:
    source_epoch: str
    owner_pid: int
    after_sequence: int
    first_available_sequence: int
    last_sequence: int
    observations: tuple[RecoveryCoverageObservation, ...]
    gap: bool

    def __post_init__(self) -> None:
        _uuid(self.source_epoch, "source_epoch")
        _integer(self.owner_pid, "owner_pid")
        _integer(self.after_sequence, "after_sequence", minimum=0)
        _integer(self.first_available_sequence, "first_available_sequence")
        _integer(self.last_sequence, "last_sequence", minimum=0)
        if (
            self.after_sequence > self.last_sequence
            or self.first_available_sequence > self.last_sequence + 1
            or (self.first_available_sequence == self.last_sequence + 1 and self.last_sequence != 0)
            or type(self.gap) is not bool
            or self.gap != (self.after_sequence < self.first_available_sequence - 1)
        ):
            raise ValueError("page sequence or gap is invalid")
        if type(self.observations) is not tuple or len(self.observations) > 256:
            raise ValueError("observations is invalid")
        if self.after_sequence < self.last_sequence and not self.observations:
            raise ValueError("a nonempty page must include its first available observation")
        expected = max(self.after_sequence + 1, self.first_available_sequence)
        for observation in self.observations:
            if (
                type(observation) is not RecoveryCoverageObservation
                or observation.source_epoch != self.source_epoch
                or observation.owner_pid != self.owner_pid
                or observation.sequence != expected
                or expected > self.last_sequence
            ):
                raise ValueError("observation page is inconsistent")
            expected += 1
