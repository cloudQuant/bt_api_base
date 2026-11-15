"""Untrusted declarations for a joint account position and order cut.

These structures validate internal consistency only. They do not authenticate a
provider, establish a common cut or complete coverage, validate a lease, resolve
order ownership, establish an FX/price fact, or authorize a trade. An owner must
bind and revalidate independent source evidence before using any declaration.
A missing batch, unknown coverage, or an unresolved order is not zero exposure.
"""

from __future__ import annotations

from dataclasses import dataclass

from bt_api_base.account_protocol import (
    MAX_ACCOUNT_ROWS,
    AccountKey,
    account_venue_contains_instrument_venue,
)
from bt_api_base.account_row_observation_protocol import (
    AccountOpenOrderObservation,
    AccountPositionObservation,
)
from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.position_bootstrap_protocol import PositionStreamSnapshot
from bt_api_base.service_protocol import MAX_REFERENCE_BYTES

_COVERAGE = frozenset({"account", "partial", "unknown"})
_ASSOCIATION = frozenset({"local", "external", "unknown"})
_UNRESOLVED = frozenset({"unknown", "fill_not_projected", "terminal_not_projected"})


def _reference(value: object) -> None:
    if type(value) is not str or not value or value != value.strip() or not value.isprintable():
        raise ValueError("invalid risk cut reference")
    try:
        length = len(value.encode("utf-8", "strict"))
    except UnicodeError:
        raise ValueError("invalid risk cut reference") from None
    if length > MAX_REFERENCE_BYTES:
        raise ValueError("invalid risk cut reference")


def _coverage(value: object) -> None:
    if type(value) is not str or value not in _COVERAGE:
        raise ValueError("invalid risk cut coverage")


@dataclass(frozen=True)
class RiskCutOrder:
    """An active order and an unverified cross-source economic association.

    External/unknown rows may have no economic reference and must not be
    discarded merely because they do not match a local permit.
    """

    observation: AccountOpenOrderObservation
    association: str
    economic_ref: str | None = None

    def __post_init__(self) -> None:
        if type(self.observation) is not AccountOpenOrderObservation:
            raise TypeError("observation must be an AccountOpenOrderObservation")
        if type(self.association) is not str or self.association not in _ASSOCIATION:
            raise ValueError("invalid risk cut order association")
        if self.economic_ref is not None:
            _reference(self.economic_ref)
        if self.association == "local" and self.economic_ref is None:
            raise ValueError("local association requires an economic reference")


@dataclass(frozen=True)
class RiskCutUnresolvedOrder:
    """An order whose exposure or position projection remains unresolved.

    No quantity or absence of a matching open-order row is inferred from this
    marker. It remains a blocker for calculations that require that fact.
    """

    account_key: AccountKey
    reason: str
    economic_ref: str | None = None

    def __post_init__(self) -> None:
        if type(self.account_key) is not AccountKey:
            raise TypeError("account_key must be an AccountKey")
        if type(self.reason) is not str or self.reason not in _UNRESOLVED:
            raise ValueError("invalid unresolved order reason")
        if self.economic_ref is not None:
            _reference(self.economic_ref)


@dataclass(frozen=True)
class RiskCutInstrumentUnit:
    """Claimed contract quantity unit and quote currency, not price authority.

    An account row's price_currency describes that row's price, while this
    quote currency is a contract claim. The account protocol does not specify
    whether row prices can be converted. Equality or a difference is not a
    source proof, and neither alone permits an estimation or FX conversion.
    """

    instrument: MarketInstrumentKey
    quantity_unit: str
    quote_currency: str | None

    def __post_init__(self) -> None:
        if type(self.instrument) is not MarketInstrumentKey:
            raise TypeError("instrument must be a MarketInstrumentKey")
        _reference(self.quantity_unit)
        if self.quote_currency is not None:
            _reference(self.quote_currency)


@dataclass(frozen=True)
class RiskAccountSessionClaim:
    """Account/session declaration without assuming a position subscription.

    None means unknown; no field authenticates its value or asserts readiness.
    """

    account_key: AccountKey
    account_ref: str | None
    route_ref: str | None
    session_ref: str | None
    connection_epoch: int | None

    def __post_init__(self) -> None:
        if type(self.account_key) is not AccountKey:
            raise TypeError("account_key must be an AccountKey")
        for value in (self.account_ref, self.route_ref, self.session_ref):
            if value is not None:
                _reference(value)
        if self.connection_epoch is not None and (
            type(self.connection_epoch) is not int or self.connection_epoch <= 0
        ):
            raise ValueError("invalid connection epoch")


@dataclass(frozen=True)
class RiskOrderCutClaim:
    """Claimed order batch in the provider-defined cut sequence domain."""

    session: RiskAccountSessionClaim
    cut_sequence: int
    coverage: str
    orders: tuple[RiskCutOrder, ...]
    unresolved: tuple[RiskCutUnresolvedOrder, ...]
    cut_domain_ref: str | None = None
    order_subscription_ref: str | None = None
    order_subscription_epoch: int | None = None
    order_valid_until_ns: int | None = None
    order_receipt_ref: str | None = None

    def __post_init__(self) -> None:
        if type(self.session) is not RiskAccountSessionClaim:
            raise TypeError("session must be a RiskAccountSessionClaim")
        if type(self.cut_sequence) is not int or self.cut_sequence < 0:
            raise ValueError("invalid risk cut sequence")
        if self.cut_domain_ref is not None:
            _reference(self.cut_domain_ref)
        if self.order_receipt_ref is not None:
            _reference(self.order_receipt_ref)
        subscription = (self.order_subscription_ref, self.order_subscription_epoch,
                        self.order_valid_until_ns)
        if any(value is not None for value in subscription):
            _reference(self.order_subscription_ref)
            if any(type(value) is not int or value <= 0 for value in subscription[1:]):
                raise ValueError("invalid order subscription claim")
        _coverage(self.coverage)
        if type(self.orders) is not tuple or any(type(row) is not RiskCutOrder for row in self.orders):
            raise TypeError("orders must be a tuple of RiskCutOrder")
        if type(self.unresolved) is not tuple or any(
            type(row) is not RiskCutUnresolvedOrder for row in self.unresolved
        ):
            raise TypeError("unresolved must be a tuple of RiskCutUnresolvedOrder")
        if len(self.orders) + len(self.unresolved) > MAX_ACCOUNT_ROWS:
            raise ValueError("risk order cut exceeds row limit")
        if any(row.observation.account_key != self.session.account_key for row in self.orders):
            raise ValueError("order account does not match risk cut")
        if any(row.account_key != self.session.account_key for row in self.unresolved):
            raise ValueError("unresolved order account does not match risk cut")
        identities = tuple(
            (row.observation.open_order.resource, row.observation.open_order.instrument,
             row.observation.open_order.order_id)
            for row in self.orders
        )
        if len(set(identities)) != len(identities):
            raise ValueError("duplicate provider order identity")
        # An active remainder and an unresolved fill may refer to the same
        # economic order. Keep both; the marker does not clear exposure or
        # establish that a fill is reflected in the position.
        for rows in (self.orders, self.unresolved):
            references = tuple(row.economic_ref for row in rows if row.economic_ref is not None)
            if len(set(references)) != len(references):
                raise ValueError("duplicate economic reference")


@dataclass(frozen=True)
class AccountRiskCutClaim:
    """Declared joint cut; equality of fields never establishes source evidence.

    ``None`` batches and ``unknown`` coverage express missing facts. The order
    and position cut sequence has meaning only if an independent provider owner
    proves they share one sequence domain and captures all relevant events.
    """

    session: RiskAccountSessionClaim
    position_snapshot: PositionStreamSnapshot | None
    position_coverage: str
    order_cut: RiskOrderCutClaim | None
    position_cut_domain_ref: str | None = None
    instrument_units: tuple[RiskCutInstrumentUnit, ...] = ()

    def __post_init__(self) -> None:
        if type(self.session) is not RiskAccountSessionClaim:
            raise TypeError("session must be a RiskAccountSessionClaim")
        _coverage(self.position_coverage)
        if self.position_cut_domain_ref is not None:
            _reference(self.position_cut_domain_ref)
        snapshot = self.position_snapshot
        orders = self.order_cut
        if snapshot is None:
            if self.position_coverage != "unknown" or self.position_cut_domain_ref is not None:
                raise ValueError("missing position snapshot has unknown coverage")
        else:
            if type(snapshot) is not PositionStreamSnapshot:
                raise TypeError("position_snapshot must be PositionStreamSnapshot or None")
            binding = snapshot.binding
            session = self.session
            if binding.account_key != session.account_key or any(
                expected is not None and actual != expected
                for actual, expected in (
                    (binding.account_ref, session.account_ref),
                    (binding.route_ref, session.route_ref),
                    (binding.session_ref, session.session_ref),
                    (binding.connection_epoch, session.connection_epoch),
                )
            ):
                raise ValueError("position binding does not match risk cut")
            if len(snapshot.positions) > MAX_ACCOUNT_ROWS:
                raise ValueError("position cut exceeds row limit")
        if orders is not None:
            if type(orders) is not RiskOrderCutClaim:
                raise TypeError("order_cut must be RiskOrderCutClaim or None")
            if orders.session.account_key != self.session.account_key or any(
                left is not None and right is not None and left != right
                for left, right in (
                    (orders.session.account_ref, self.session.account_ref),
                    (orders.session.route_ref, self.session.route_ref),
                    (orders.session.session_ref, self.session.session_ref),
                    (orders.session.connection_epoch, self.session.connection_epoch),
                )
            ):
                raise ValueError("order session does not match risk cut")
            if snapshot is not None and any(
                declared is not None and actual != declared
                for actual, declared in (
                    (snapshot.binding.account_ref, orders.session.account_ref),
                    (snapshot.binding.route_ref, orders.session.route_ref),
                    (snapshot.binding.session_ref, orders.session.session_ref),
                    (snapshot.binding.connection_epoch, orders.session.connection_epoch),
                )
            ):
                raise ValueError("position and order sessions conflict")
            if snapshot is not None and self.position_cut_domain_ref is not None and orders.cut_domain_ref is not None:
                if self.position_cut_domain_ref != orders.cut_domain_ref:
                    raise ValueError("position and order cut domains differ")
                if orders.cut_sequence != snapshot.cut_sequence:
                    raise ValueError("position and order cut sequences differ")

        if type(self.instrument_units) is not tuple or len(self.instrument_units) > MAX_ACCOUNT_ROWS or any(
            type(row) is not RiskCutInstrumentUnit for row in self.instrument_units
        ):
            raise TypeError("instrument_units must be a bounded tuple of RiskCutInstrumentUnit")
        units = {}
        for row in self.instrument_units:
            key = row.instrument
            account = self.session.account_key
            if (key.provider != account.provider or key.environment != account.environment
                    or not account_venue_contains_instrument_venue(account, key.venue)):
                raise ValueError("instrument unit does not match risk cut account")
            if key in units:
                raise ValueError("duplicate instrument unit")
            units[key] = row.quantity_unit
        position_sides = {}
        if snapshot is not None:
            for row in snapshot.positions:
                AccountPositionObservation(self.session.account_key, row)
                key = (row.resource, row.instrument)
                sides = position_sides.setdefault(key, set())
                if row.side in sides or (row.side == "net" and sides) or (
                    row.side != "net" and "net" in sides
                ):
                    raise ValueError("duplicate or conflicting position side")
                sides.add(row.side)
                if row.instrument in units and units[row.instrument] != row.qty_unit:
                    raise ValueError("inconsistent quantity unit")
                units[row.instrument] = row.qty_unit
        if orders is not None:
            for entry in orders.orders:
                row = entry.observation.open_order
                if row.instrument in units and units[row.instrument] != row.qty_unit:
                    raise ValueError("inconsistent quantity unit")
                units[row.instrument] = row.qty_unit


__all__ = ("AccountRiskCutClaim", "RiskAccountSessionClaim", "RiskCutInstrumentUnit", "RiskCutOrder", "RiskCutUnresolvedOrder", "RiskOrderCutClaim")
