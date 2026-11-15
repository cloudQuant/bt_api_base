"""Versioned cancel-attempt observation, without source or send authority.

The Gateway journal supplies the record and, from dispatch onward, the
prepared digest. The complete instrument and the trading day of *this state
fact* must be supplied by their owners; their Gateway publication and source
binding are not yet implemented. An input shape does not prove either fact.
In particular NOT_SENT alone is not authoritative proof for releasing an
attempt or reservation, including across owner generations.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from bt_api_base.gateway_cancel_protocol import GatewayCancelRecord
from bt_api_base.gateway_direct_protocol import GatewayCommandBinding, GatewayDirectProtocolError
from bt_api_base.gateway_execution_protocol import _text
from bt_api_base.market_protocol import MarketInstrumentKey


class GatewayCancelAttemptEventError(ValueError):
    """Finite error with no untrusted input values."""

    def __init__(self, code: str = "INVALID_CANCEL_ATTEMPT_EVENT") -> None:
        self.code = code
        super().__init__(code)


def _invalid() -> None:
    raise GatewayCancelAttemptEventError()


def _digest(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _day(value: object) -> bool:
    if type(value) is not str or len(value) != 8 or not value.isascii() or not value.isdigit():
        return False
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return False
    return True


@dataclass(frozen=True, slots=True)
class GatewayCancelAttemptEvent:
    """One versioned attempt state; its business key is account/journal/attempt.

    ``trading_day`` is the day of this particular fact, not the order's
    creation day. Event transport order is not part of the business identity.
    """

    schema_version: int
    record: GatewayCancelRecord
    instrument: MarketInstrumentKey
    trading_day: str
    prepared_digest: str | None

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            _invalid()
        if (
            type(self.record) is not GatewayCancelRecord
            or type(self.instrument) is not MarketInstrumentKey
        ):
            _invalid()
        try:
            self.record.__post_init__()
            self.instrument.__post_init__()
        except (ValueError, TypeError):
            _invalid()
        binding = self.record.binding
        # Existing record references have a weaker printable/byte constraint.
        if not all(
            _text(getattr(binding, n))
            for n in ("journal_id", "account_scope", "strategy_scope", "principal")
        ):
            _invalid()
        if not all(
            _text(getattr(self.record, n))
            for n in (
                "operation_id",
                "attempt_id",
                "request_key",
                "target_reservation_id",
                "owner_generation",
                "attempt_generation",
            )
        ):
            _invalid()
        if not _day(self.trading_day):
            _invalid()
        if self.record.state == "REQUESTED":
            if self.prepared_digest is not None:
                _invalid()
        elif not _digest(self.prepared_digest):
            _invalid()

    @property
    def business_key(self) -> tuple[str, str, str]:
        return (
            self.record.binding.account_scope,
            self.record.binding.journal_id,
            self.record.attempt_id,
        )

    def to_mapping(self) -> dict[str, Any]:
        self.__post_init__()
        return {
            "schema_version": self.schema_version,
            "record": self.record.to_mapping(),
            "instrument": self.instrument.to_dict(),
            "trading_day": self.trading_day,
            "prepared_digest": self.prepared_digest,
        }

    @classmethod
    def from_mapping(
        cls, value: object, *, expected_binding: GatewayCommandBinding
    ) -> GatewayCancelAttemptEvent:
        if (
            type(value) is not dict
            or set(value)
            != {"schema_version", "record", "instrument", "trading_day", "prepared_digest"}
            or any(type(key) is not str for key in value)
        ):
            _invalid()
        if (
            type(value["record"]) is not dict
            or type(value["instrument"]) is not dict
            or type(value["record"].get("binding")) is not dict
        ):
            _invalid()
        try:
            record = GatewayCancelRecord.from_mapping(
                value["record"], expected_binding=expected_binding
            )
            instrument = MarketInstrumentKey.from_dict(value["instrument"])
            return cls(
                value["schema_version"],
                record,
                instrument,
                value["trading_day"],
                value["prepared_digest"],
            )
        except (GatewayDirectProtocolError, TypeError, ValueError):
            _invalid()

    def check_successor(self, successor: GatewayCancelAttemptEvent) -> None:
        """Reject contradictory replay or incompatible state progress.

        Gaps are allowed: a consumer must separately establish stream coverage.
        The current owner generation is an observation and can change even at
        the same version. A later version cannot move the fact day backwards;
        correction requires a separate trusted correction contract. This check
        establishes neither authenticity nor completeness.
        """
        self.__post_init__()
        if type(successor) is not GatewayCancelAttemptEvent:
            _invalid()
        successor.__post_init__()
        old, new = self.record, successor.record
        immutable = (
            "binding",
            "operation_id",
            "attempt_id",
            "request_key",
            "target_reservation_id",
            "target_digest",
            "attempt_generation",
        )
        if (
            self.business_key != successor.business_key
            or self.instrument != successor.instrument
            or any(getattr(old, name) != getattr(new, name) for name in immutable)
            or new.version < old.version
            or (
                new.version == old.version
                and self
                != replace(
                    successor,
                    record=replace(
                        new,
                        owner_generation=old.owner_generation,
                        generation_current=old.generation_current,
                    ),
                )
            )
            or (new.version > old.version and successor.trading_day < self.trading_day)
            or (
                self.prepared_digest is not None
                and self.prepared_digest != successor.prepared_digest
            )
        ):
            raise GatewayCancelAttemptEventError("CANCEL_ATTEMPT_CONFLICT")
