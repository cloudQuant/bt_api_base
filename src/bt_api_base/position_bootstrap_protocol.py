"""Neutral declarations for a position snapshot/stream handoff.

These types are data, not provider evidence. A host must explicitly bind a
trusted provider adapter which validates the receipt, subscription and current
session. No adapter in this module authenticates an account or a venue.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from bt_api_base.account_protocol import AccountKey, AccountPosition


def _text(value: object) -> None:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError("position bootstrap reference is invalid")


def _positive(value: object) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError("position bootstrap number is invalid")


@dataclass(frozen=True)
class PositionStreamBinding:
    """Claimed account and one provider subscription/session generation."""

    account_key: AccountKey
    account_ref: str
    route_ref: str
    session_ref: str
    connection_epoch: int
    subscription_epoch: int
    subscription_ready_ref: str
    valid_until_ns: int

    def __post_init__(self) -> None:
        if type(self.account_key) is not AccountKey:
            raise TypeError("account_key must be an AccountKey")
        for value in (
            self.account_ref,
            self.route_ref,
            self.session_ref,
            self.subscription_ready_ref,
        ):
            _text(value)
        for value in (self.connection_epoch, self.subscription_epoch, self.valid_until_ns):
            _positive(value)


@dataclass(frozen=True)
class PositionStreamSnapshot:
    """Claimed complete snapshot at a provider-defined stream cut."""

    binding: PositionStreamBinding
    cut_sequence: int
    observed_ns: int
    snapshot_receipt_ref: str
    positions: tuple[AccountPosition, ...]

    def __post_init__(self) -> None:
        if type(self.binding) is not PositionStreamBinding:
            raise TypeError("binding must be a PositionStreamBinding")
        if type(self.cut_sequence) is not int or self.cut_sequence < 0:
            raise ValueError("snapshot cut is invalid")
        _positive(self.observed_ns)
        _text(self.snapshot_receipt_ref)
        if type(self.positions) is not tuple or any(
            type(row) is not AccountPosition for row in self.positions
        ):
            raise TypeError("positions must be a tuple of AccountPosition")


@dataclass(frozen=True)
class PositionStreamEvent:
    """An absolute position update with a provider-defined sequence."""

    binding: PositionStreamBinding
    sequence: int
    observed_ns: int
    event_receipt_ref: str
    position: AccountPosition

    def __post_init__(self) -> None:
        if type(self.binding) is not PositionStreamBinding:
            raise TypeError("binding must be a PositionStreamBinding")
        _positive(self.sequence)
        _positive(self.observed_ns)
        _text(self.event_receipt_ref)
        if type(self.position) is not AccountPosition:
            raise TypeError("position must be an AccountPosition")


class PositionStreamVerifier(Protocol):
    """Trusted adapter port; implementations must verify source-owned evidence.

    The caller owns verifier selection and authorization. Returning True is an
    adapter assertion, not independent proof supplied by these data classes.
    Inputs are detached copies: a real adapter must validate receipt references
    and all bound facts against its own trusted source, not infer trust from
    strings, object identity, or the submitted claims. The current built-in
    providers do not provide this verifier contract.
    """

    def verify_binding(self, binding: PositionStreamBinding) -> bool: ...

    def verify_snapshot(
        self, binding: PositionStreamBinding, snapshot: PositionStreamSnapshot
    ) -> bool: ...

    def verify_event(self, binding: PositionStreamBinding, event: PositionStreamEvent) -> bool: ...

    def verify_live(self, binding: PositionStreamBinding, now_ns: int) -> bool: ...
