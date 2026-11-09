"""Bounded public execution observations; these values grant no authority.

Identity key digests hash each UTF-8 key. The trade key digest hashes the ASCII
JSON encoding of its list representation (ensure_ascii=True, compact separators).
The fact digest remains an opaque label for the original, unredacted fact.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields
from typing import Any

from bt_api_base.direct_write_protocol import (
    DirectExecutionEventKind,
    DirectOrderStatus,
    NativeOrderIdentity,
)
from bt_api_base.gateway_direct_protocol import GatewayCommandBinding
from bt_api_base.gateway_execution_protocol import GatewayReturnFact, _text
from bt_api_base.market_protocol import MarketInstrumentKey


class GatewayExecutionStreamProtocolError(ValueError):
    """Finite validation failure; no input values appear in the error."""

    def __init__(self, code: str) -> None:
        self.code = code if code in {"INVALID_STREAM", "BINDING_MISMATCH"} else "INVALID_STREAM"
        super().__init__(self.code)


def _fail(code: str = "INVALID_STREAM") -> None:
    raise GatewayExecutionStreamProtocolError(code)


def _digest(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _number(value: object, *, positive: bool = False) -> bool:
    return type(value) is int and (1 if positive else 0) <= value < 2**63


def _mapping(value: object, names: set[str]) -> dict[str, Any]:
    if type(value) is not dict or any(type(key) is not str for key in value) or set(value) != names:
        _fail()
    return dict(value)


def _validate_binding(binding: object) -> None:
    if type(binding) is not GatewayCommandBinding or not all(
        _text(getattr(binding, name))
        for name in ("journal_id", "account_scope", "strategy_scope", "principal")
    ):
        _fail()


def _binding_mapping(binding: GatewayCommandBinding) -> dict[str, str]:
    return {
        name: getattr(binding, name)
        for name in ("journal_id", "account_scope", "strategy_scope", "principal")
    }


def _consumer(value: object) -> bool:
    return type(value) is str and value.startswith("gexec:") and _digest(value[6:])


def gateway_execution_consumer_ref(
    *,
    principal_ref: str,
    actor_ref: str,
    execution_domain_ref: str,
    account_scope: str,
    strategy_scope: str,
) -> str:
    """Stable consumer identity independent of registration and run."""
    values = (principal_ref, actor_ref, execution_domain_ref, account_scope, strategy_scope)
    if not all(_text(value) for value in values):
        _fail()
    payload = [
        1,
        "strategy_client",
        principal_ref,
        actor_ref,
        None,
        execution_domain_ref,
        account_scope,
        strategy_scope,
    ]
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    return "gexec:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class GatewayExecutionObservation:
    account_scope: str
    route: str
    instrument: MarketInstrumentKey
    trading_day: str
    kind: DirectExecutionEventKind
    native_identity_digest: str | None = None
    identity_key_digests: tuple[str, ...] = ()
    binding_key_digests: tuple[str, ...] = ()
    venue_key_digest: str | None = None
    trade_key_digest: str | None = None
    status: DirectOrderStatus | None = None
    side: str | None = None
    offset: str | None = None
    order_quantity: str | None = None
    filled_quantity: str | None = None
    remaining_quantity: str | None = None
    limit_price: str | None = None
    trade_quantity: str | None = None
    trade_price: str | None = None
    trade_time: str | None = None
    error_code: str | None = None
    schema_version: int = 1
    trade_date: str | None = None
    trade_metadata_only: bool = False

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not int
            or self.schema_version not in (1, 2)
            or type(self.trade_metadata_only) is not bool
            or (
                self.schema_version == 1
                and (self.trade_date is not None or self.trade_metadata_only)
            )
            or (self.schema_version == 2 and self.kind is not DirectExecutionEventKind.TRADE)
            or (self.trade_metadata_only and self.trade_date is None)
            or (
                self.trade_metadata_only
                and any(
                    value is None
                    for value in (
                        self.trade_key_digest,
                        self.trade_quantity,
                        self.trade_price,
                        self.side,
                        self.venue_key_digest,
                    )
                )
            )
        ):
            _fail()
        for keys in (self.identity_key_digests, self.binding_key_digests):
            if (
                type(keys) is not tuple
                or len(keys) > 16
                or any(not _digest(k) for k in keys)
                or keys != tuple(sorted(set(keys)))
            ):
                _fail()
        if (
            (self.native_identity_digest is not None and not _digest(self.native_identity_digest))
            or (self.identity_key_digests and self.native_identity_digest is None)
            or not set(self.binding_key_digests).issubset(self.identity_key_digests)
            or (
                self.venue_key_digest is not None
                and (
                    not _digest(self.venue_key_digest)
                    or self.venue_key_digest not in self.identity_key_digests
                )
            )
            or (self.trade_key_digest is not None and not _digest(self.trade_key_digest))
        ):
            _fail()
        # Reuse the exact existing fact validation for dates, enum, identity,
        # and decimal semantics; digest placeholders never leave this object.
        data = {name: getattr(self, name) for name in _ECONOMIC_FIELDS}
        try:
            fact = GatewayReturnFact(
                **data,
                schema_version=4 if self.schema_version == 2 else 1,
                trade_date=self.trade_date,
                source_ref="public-observation",
                identity=None
                if self.native_identity_digest is None
                else NativeOrderIdentity(
                    self.route, None, {"public_digest": self.native_identity_digest}, None
                ),
                identity_keys=self.identity_key_digests,
                binding_keys=self.binding_key_digests,
                venue_key=self.venue_key_digest,
                trade_key=None
                if self.trade_key_digest is None
                else ("digest", self.trade_key_digest),
            )
        except Exception:
            _fail()
        object.__setattr__(self, "instrument", fact.instrument)

    def to_mapping(self) -> dict[str, Any]:
        self.__post_init__()
        result = {name: getattr(self, name) for name in _ECONOMIC_FIELDS}
        result.update(
            schema_version=self.schema_version,
            instrument=self.instrument.to_dict(),
            kind=self.kind.value,
            native_identity_digest=self.native_identity_digest,
            status=None if self.status is None else self.status.value,
            identity_key_digests=list(self.identity_key_digests),
            binding_key_digests=list(self.binding_key_digests),
            venue_key_digest=self.venue_key_digest,
            trade_key_digest=self.trade_key_digest,
        )
        if self.schema_version == 2:
            result.update(trade_date=self.trade_date, trade_metadata_only=self.trade_metadata_only)
        return result

    @classmethod
    def from_mapping(cls, raw: object) -> GatewayExecutionObservation:
        try:
            if type(raw) is not dict:
                _fail()
            version = raw.get("schema_version")
            if type(version) is not int or version not in (1, 2):
                _fail()
            names = {f.name for f in fields(cls)}
            if version == 1:
                names -= {"trade_date", "trade_metadata_only"}
            data = _mapping(raw, names)
            data.pop("schema_version")
            trade_date = data.pop("trade_date", None)
            trade_metadata_only = data.pop("trade_metadata_only", False)
            keys = data.pop("identity_key_digests")
            binding = data.pop("binding_key_digests")
            venue, trade = data.pop("venue_key_digest"), data.pop("trade_key_digest")
            native_identity_digest = data.pop("native_identity_digest")
            if (native_identity_digest is not None and not _digest(native_identity_digest)) or (
                keys and native_identity_digest is None
            ):
                _fail()
            if type(keys) is not list or type(binding) is not list:
                _fail()
            # The existing strict mapping decoder also validates nested shapes.
            placeholder = (
                None
                if native_identity_digest is None
                else {
                    "exchange_name": data["route"],
                    "client_order_id": None,
                    "fields": {"public_digest": native_identity_digest},
                    "session_generation": None,
                }
            )
            fact_data = dict(
                data,
                schema_version=4 if version == 2 else 1,
                source_ref="public-observation",
                session_generation=None,
                identity=placeholder,
                identity_keys=keys,
                binding_keys=binding,
                venue_key=venue,
                trade_key=None if trade is None else ["digest", trade],
            )
            if version == 2:
                fact_data["trade_date"] = trade_date
            fact = GatewayReturnFact.from_mapping(fact_data)
            return cls(
                **{name: getattr(fact, name) for name in _ECONOMIC_FIELDS},
                schema_version=version,
                trade_date=trade_date,
                trade_metadata_only=trade_metadata_only,
                native_identity_digest=native_identity_digest,
                identity_key_digests=tuple(keys),
                binding_key_digests=tuple(binding),
                venue_key_digest=venue,
                trade_key_digest=trade,
            )
        except GatewayExecutionStreamProtocolError:
            raise
        except Exception:
            _fail()


_ECONOMIC_FIELDS = tuple(
    # Only observation fields are projected; v2 fact cancel_request_key is
    # intentionally absent and never becomes a public economic field.
    f.name
    for f in fields(GatewayExecutionObservation)
    if f.name
    not in {
        "native_identity_digest",
        "identity_key_digests",
        "binding_key_digests",
        "venue_key_digest",
        "trade_key_digest",
        "schema_version",
        "trade_date",
        "trade_metadata_only",
    }
)


def project_gateway_execution_observation(
    fact: GatewayReturnFact, *, trade_metadata_only: bool = False
) -> GatewayExecutionObservation:
    """Redact a validated fact; digests are correlation tags, not provenance."""
    if type(fact) is not GatewayReturnFact or type(trade_metadata_only) is not bool:
        _fail()
    try:
        fact = GatewayReturnFact.from_mapping(fact.to_mapping())
    except Exception:
        _fail()
    native_identity_digest = (
        None
        if fact.identity is None
        else hashlib.sha256(
            json.dumps(
                fact.identity.to_dict(), ensure_ascii=True, sort_keys=True, separators=(",", ":")
            ).encode("ascii")
        ).hexdigest()
    )

    def key_digest(key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    trade = (
        None
        if fact.trade_key is None
        else hashlib.sha256(
            json.dumps(list(fact.trade_key), ensure_ascii=True, separators=(",", ":")).encode(
                "ascii"
            )
        ).hexdigest()
    )
    return GatewayExecutionObservation(
        **{name: getattr(fact, name) for name in _ECONOMIC_FIELDS},
        schema_version=2 if fact.schema_version == 4 else 1,
        trade_date=fact.trade_date,
        trade_metadata_only=trade_metadata_only,
        native_identity_digest=native_identity_digest,
        identity_key_digests=tuple(sorted({key_digest(key) for key in fact.identity_keys})),
        binding_key_digests=tuple(sorted({key_digest(key) for key in fact.binding_keys})),
        venue_key_digest=None if fact.venue_key is None else key_digest(fact.venue_key),
        trade_key_digest=trade,
    )


@dataclass(frozen=True, slots=True)
class GatewayCancelErrorAttribution:
    """Public correlation to one persisted attempt; not source authority."""

    operation_id: str
    attempt_id: str
    prepared_digest: str

    def __post_init__(self) -> None:
        if (
            not _text(self.operation_id)
            or not _text(self.attempt_id)
            or not _digest(self.prepared_digest)
        ):
            _fail()

    def to_mapping(self) -> dict[str, str]:
        self.__post_init__()
        return {
            "operation_id": self.operation_id,
            "attempt_id": self.attempt_id,
            "prepared_digest": self.prepared_digest,
        }

    @classmethod
    def from_mapping(cls, raw: object) -> GatewayCancelErrorAttribution:
        return cls(**_mapping(raw, {"operation_id", "attempt_id", "prepared_digest"}))


@dataclass(frozen=True, slots=True)
class GatewayPlaceErrorAttribution:
    """Public digest of one persisted preparation; not source authority."""

    prepared_digest: str

    def __post_init__(self) -> None:
        if not _digest(self.prepared_digest):
            _fail()

    def to_mapping(self) -> dict[str, str]:
        self.__post_init__()
        return {"prepared_digest": self.prepared_digest}

    @classmethod
    def from_mapping(cls, raw: object) -> GatewayPlaceErrorAttribution:
        return cls(**_mapping(raw, {"prepared_digest"}))


@dataclass(frozen=True, slots=True)
class GatewayExecutionStreamEvent:
    sequence: int
    request_key: str
    reservation_id: str
    command_digest: str
    command_principal: str
    fact_digest: str
    observation: GatewayExecutionObservation
    cancel_attribution: GatewayCancelErrorAttribution | None = None
    place_attribution: GatewayPlaceErrorAttribution | None = None

    def __post_init__(self) -> None:
        if (
            not _number(self.sequence, positive=True)
            or not all(
                _text(x) for x in (self.request_key, self.reservation_id, self.command_principal)
            )
            or not _digest(self.command_digest)
            or not _digest(self.fact_digest)
            or type(self.observation) is not GatewayExecutionObservation
            or (
                self.cancel_attribution is not None
                and (
                    type(self.cancel_attribution) is not GatewayCancelErrorAttribution
                    or self.observation.kind is not DirectExecutionEventKind.CANCEL_ERROR
                )
            )
            or (
                self.place_attribution is not None
                and (
                    type(self.place_attribution) is not GatewayPlaceErrorAttribution
                    or self.observation.kind is not DirectExecutionEventKind.ORDER_ERROR
                    or self.observation.status is not None
                    or self.cancel_attribution is not None
                )
            )
        ):
            _fail()
        if self.cancel_attribution is not None:
            self.cancel_attribution.__post_init__()
        if self.place_attribution is not None:
            self.place_attribution.__post_init__()

    def to_mapping(self, *, schema_version: int = 3) -> dict[str, Any]:
        self.__post_init__()
        if type(schema_version) is not int or schema_version not in (1, 2, 3):
            _fail()
        if schema_version == 1 and self.cancel_attribution is not None:
            _fail()
        if schema_version in (1, 2) and self.place_attribution is not None:
            _fail()
        result = {
            name: (self.observation.to_mapping() if name == "observation" else getattr(self, name))
            for name in (
                f.name
                for f in fields(self)
                if f.name not in {"cancel_attribution", "place_attribution"}
            )
        }
        if schema_version >= 2:
            result["cancel_attribution"] = (
                None if self.cancel_attribution is None else self.cancel_attribution.to_mapping()
            )
        if schema_version == 3:
            result["place_attribution"] = (
                None if self.place_attribution is None else self.place_attribution.to_mapping()
            )
        return result

    @classmethod
    def from_mapping(cls, raw: object, *, schema_version: int = 3) -> GatewayExecutionStreamEvent:
        if type(schema_version) is not int or schema_version not in (1, 2, 3):
            _fail()
        names = {f.name for f in fields(cls)}
        if schema_version == 1:
            names.remove("cancel_attribution")
        if schema_version < 3:
            names.remove("place_attribution")
        data = _mapping(raw, names)
        data["observation"] = GatewayExecutionObservation.from_mapping(data["observation"])
        if schema_version >= 2 and data["cancel_attribution"] is not None:
            data["cancel_attribution"] = GatewayCancelErrorAttribution.from_mapping(
                data["cancel_attribution"]
            )
        if schema_version == 3 and data["place_attribution"] is not None:
            data["place_attribution"] = GatewayPlaceErrorAttribution.from_mapping(
                data["place_attribution"]
            )
        return cls(**data)


def _validate_progress(
    binding: GatewayCommandBinding,
    consumer_ref: str,
    epoch: str,
    offered_sequence: int,
    acknowledged_sequence: int,
) -> None:
    _validate_binding(binding)
    if (
        not _consumer(consumer_ref)
        or not _digest(epoch)
        or not _number(offered_sequence)
        or not _number(acknowledged_sequence)
        or acknowledged_sequence > offered_sequence
    ):
        _fail()


def _parse_outer(
    cls: type,
    raw: object,
    expected_binding: GatewayCommandBinding,
    expected_consumer_ref: str | None,
    allowed_versions: tuple[int, ...] = (1,),
) -> dict[str, Any]:
    _validate_binding(expected_binding)
    if expected_consumer_ref is not None and not _consumer(expected_consumer_ref):
        _fail()
    data = _mapping(raw, {f.name for f in fields(cls)} | {"schema_version"})
    version = data.pop("schema_version")
    if type(version) is not int or version not in allowed_versions:
        _fail()
    binding_data = _mapping(
        data["binding"], {"journal_id", "account_scope", "strategy_scope", "principal"}
    )
    try:
        binding = GatewayCommandBinding(**binding_data)
    except Exception:
        _fail()
    _validate_binding(binding)
    if binding != expected_binding or (
        expected_consumer_ref is not None and data["consumer_ref"] != expected_consumer_ref
    ):
        _fail("BINDING_MISMATCH")
    data["binding"] = binding
    return data


@dataclass(frozen=True, slots=True)
class GatewayExecutionStreamProgress:
    binding: GatewayCommandBinding
    consumer_ref: str
    epoch: str
    offered_sequence: int
    acknowledged_sequence: int

    def __post_init__(self) -> None:
        _validate_progress(
            self.binding,
            self.consumer_ref,
            self.epoch,
            self.offered_sequence,
            self.acknowledged_sequence,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "binding": _binding_mapping(self.binding),
            "consumer_ref": self.consumer_ref,
            "epoch": self.epoch,
            "offered_sequence": self.offered_sequence,
            "acknowledged_sequence": self.acknowledged_sequence,
        }

    @classmethod
    def from_mapping(
        cls,
        raw: object,
        *,
        expected_binding: GatewayCommandBinding,
        expected_consumer_ref: str | None = None,
    ) -> GatewayExecutionStreamProgress:
        return cls(**_parse_outer(cls, raw, expected_binding, expected_consumer_ref))


@dataclass(frozen=True, slots=True)
class GatewayExecutionStreamPage:
    binding: GatewayCommandBinding
    consumer_ref: str
    epoch: str
    offered_sequence: int
    acknowledged_sequence: int
    has_more: bool
    events: tuple[GatewayExecutionStreamEvent, ...]

    def __post_init__(self) -> None:
        _validate_progress(
            self.binding,
            self.consumer_ref,
            self.epoch,
            self.offered_sequence,
            self.acknowledged_sequence,
        )
        if (
            type(self.has_more) is not bool
            or type(self.events) is not tuple
            or len(self.events) > 256
            or (self.has_more and not self.events)
        ):
            _fail()
        previous = 0
        for event in self.events:
            if (
                type(event) is not GatewayExecutionStreamEvent
                or event.sequence <= previous
                or event.sequence > self.offered_sequence
                or event.observation.account_scope != self.binding.account_scope
            ):
                _fail()
            previous = event.sequence

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": 3,
            "binding": _binding_mapping(self.binding),
            "consumer_ref": self.consumer_ref,
            "epoch": self.epoch,
            "offered_sequence": self.offered_sequence,
            "acknowledged_sequence": self.acknowledged_sequence,
            "has_more": self.has_more,
            "events": [event.to_mapping(schema_version=3) for event in self.events],
        }

    @classmethod
    def from_mapping(
        cls,
        raw: object,
        *,
        expected_binding: GatewayCommandBinding,
        expected_consumer_ref: str | None = None,
    ) -> GatewayExecutionStreamPage:
        data = _parse_outer(cls, raw, expected_binding, expected_consumer_ref, (1, 2, 3))
        if type(data["events"]) is not list or len(data["events"]) > 256:
            _fail()
        data["events"] = tuple(
            GatewayExecutionStreamEvent.from_mapping(event, schema_version=raw["schema_version"])
            for event in data["events"]
        )
        return cls(**data)
