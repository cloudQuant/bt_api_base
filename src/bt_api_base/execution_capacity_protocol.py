"""Provider-neutral order-capacity DTO and capability port.

Only a trusted SDK-selected provider authority may produce an observed
snapshot. This common contract contains bounded counts and a limit only; it
does not expose order references, provider rows, native state, or write
authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable


ORDER_CAPACITY_SCHEMA = "bt_api_base.execution_capacity.v1"

_OBSERVED = "OBSERVED"
_UNAVAILABLE = "UNAVAILABLE"
_UNSTABLE_OR_OVER_CAPACITY = "UNSTABLE_OR_OVER_CAPACITY"
_STATUSES = frozenset({_OBSERVED, _UNAVAILABLE, _UNSTABLE_OR_OVER_CAPACITY})

_UNAVAILABLE_REASONS = frozenset(
    {
        "order_capacity_route_resolution_failed",
        "order_capacity_route_unavailable",
        "order_capacity_route_unregistered",
        "order_capacity_factory_failed",
        "order_capacity_provider_unavailable",
        "order_capacity_projection_invalid",
        "order_capacity_capability_unavailable",
        "order_capacity_authority_unavailable",
    }
)


@dataclass(frozen=True)
class OrderCapacitySnapshot:
    """One immutable order-capacity projection, route-bound when observed.

    Only ``UNAVAILABLE`` snapshots may omit ``exchange_name``; this represents
    an SDK selector that could not resolve exactly one route. Unavailable
    snapshots carry no counts. ``UNSTABLE_OR_OVER_CAPACITY`` snapshots retain
    validated counts and the limit that established the over-capacity state.
    Active/UNKNOWN retention is marked unbounded until an SDK authority proves
    a separate bound.
    """

    exchange_name: Optional[str]
    status: str
    active_order_count: Optional[int] = None
    unknown_order_count: Optional[int] = None
    terminal_order_count: Optional[int] = None
    dispatching_order_count: Optional[int] = None
    terminal_order_limit: Optional[int] = None
    terminal_limit_respected: Optional[bool] = None
    active_unknown_limit: Optional[int] = None
    active_unknown_bounded: Optional[bool] = None
    reason_code: Optional[str] = None

    @property
    def schema(self) -> str:
        return ORDER_CAPACITY_SCHEMA

    def __post_init__(self) -> None:
        if type(self.status) is not str or self.status not in _STATUSES:
            raise ValueError("order_capacity_status_invalid")
        if self.exchange_name is None:
            if self.status != _UNAVAILABLE:
                raise ValueError("order_capacity_route_required")
        else:
            _validate_exchange_name(self.exchange_name)

        if self.status == _UNAVAILABLE:
            if not _is_unavailable_reason(self.reason_code):
                raise ValueError("order_capacity_unavailable_reason_invalid")
            if any(
                value is not None
                for value in (
                    self.active_order_count,
                    self.unknown_order_count,
                    self.terminal_order_count,
                    self.dispatching_order_count,
                    self.terminal_order_limit,
                    self.terminal_limit_respected,
                    self.active_unknown_limit,
                    self.active_unknown_bounded,
                )
            ):
                raise ValueError("order_capacity_unavailable_projection_invalid")
            return

        _validate_counts_and_limit(self)
        if self.active_unknown_limit is not None or self.active_unknown_bounded is not False:
            raise ValueError("order_capacity_unknown_retention_contract_invalid")

        if self.status == _OBSERVED:
            if (
                self.terminal_limit_respected is not True
                or self.terminal_order_count > self.terminal_order_limit
                or self.dispatching_order_count != 0
                or self.reason_code is not None
            ):
                raise ValueError("order_capacity_observation_invalid")
            return

        if (
            self.terminal_limit_respected is not False
            or self.terminal_order_count <= self.terminal_order_limit
            or self.dispatching_order_count != 0
            or self.reason_code != "order_capacity_over_capacity"
        ):
            raise ValueError("order_capacity_over_capacity_projection_invalid")

@runtime_checkable
class OrderCapacityProviderPort(Protocol):
    """SDK-internal provider capability for one explicitly selected route."""

    def order_capacity_facts(self) -> OrderCapacitySnapshot:
        """Return facts obtained from the route's registered authority."""


def unavailable_order_capacity_snapshot(
    exchange_name: Optional[str],
    reason_code: str = "order_capacity_capability_unavailable",
) -> OrderCapacitySnapshot:
    """Build a typed no-observation result using a finite SDK reason code."""

    if exchange_name is not None:
        _validate_exchange_name(exchange_name)
    if not _is_unavailable_reason(reason_code):
        reason_code = "order_capacity_capability_unavailable"
    return OrderCapacitySnapshot(
        exchange_name=exchange_name,
        status=_UNAVAILABLE,
        reason_code=reason_code,
    )


def _validate_counts_and_limit(snapshot: OrderCapacitySnapshot) -> None:
    for value in (
        snapshot.active_order_count,
        snapshot.unknown_order_count,
        snapshot.terminal_order_count,
        snapshot.dispatching_order_count,
    ):
        if type(value) is not int or value < 0:
            raise ValueError("order_capacity_count_invalid")
    if type(snapshot.terminal_order_limit) is not int or snapshot.terminal_order_limit <= 0:
        raise ValueError("order_capacity_limit_invalid")
    if type(snapshot.terminal_limit_respected) is not bool:
        raise ValueError("order_capacity_limit_projection_invalid")


def _validate_exchange_name(exchange_name: object) -> None:
    if (
        type(exchange_name) is not str
        or not exchange_name
        or exchange_name != exchange_name.strip()
        or not exchange_name.isprintable()
        or len(exchange_name) > 256
    ):
        raise ValueError("order_capacity_exchange_name_invalid")


def _is_unavailable_reason(reason_code: object) -> bool:
    return type(reason_code) is str and reason_code in _UNAVAILABLE_REASONS


__all__ = [
    "ORDER_CAPACITY_SCHEMA",
    "OrderCapacityProviderPort",
    "OrderCapacitySnapshot",
    "unavailable_order_capacity_snapshot",
]
