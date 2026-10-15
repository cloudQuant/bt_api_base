"""Project a trusted Gateway market frame into a system telemetry request.

This module contains only shared wire validation and serialization. The caller
supplies the target event type and schema, so the base package does not depend
on a domain service. The projected event records that a consumer received a
Gateway frame; it does not assert that the Gateway retained the frame durably,
that the data is current, or that the market data is an authoritative exchange
fact. The append timestamp comes from Gateway ``sent_at_utc``; it is not a
measured local receipt time. The source quote payload and source/entitlement
references are deliberately omitted. Header identity and scope are claims;
callers must pass only frames received on an authenticated Gateway
``ServiceMarketClient`` subscription, because this projector does not
authenticate arbitrary envelopes.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from bt_api_base.market_protocol import (
    MARKET_EVENT_OPERATION,
    MARKET_EVENT_SCHEMA,
    MARKET_EVENT_SCHEMA_VERSION,
    MarketSubscriptionKey,
)
from bt_api_base.service_protocol import (
    MAX_REFERENCE_BYTES,
    WireEnvelope,
    WireIdentity,
    WireRole,
    WireScope,
    validate_event,
)

_EVENT_ID_PREFIX = "gateway-market-observation-v1:"


class SystemTelemetryProjectionError(ValueError):
    """A finite validation error for one trusted Gateway telemetry frame."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class GatewaySystemTelemetryProjector:
    """Convert an exact Gateway market event to bounded append arguments.

    ``expected_identity`` and ``expected_scope`` must come from trusted SDK
    service composition. The scope is required to be account-free; projected
    events are always system observations. The target event type and schema
    are supplied by the caller. The caller may retry the returned append
    request because its event ID binds the Gateway service, stream, epoch,
    sequence, and configured system/process.
    """

    def __init__(
        self,
        expected_identity: WireIdentity,
        expected_scope: WireScope,
        *,
        system_ref: str,
        process_ref: str,
        event_type: str,
        observation_schema: str,
    ) -> None:
        if (
            type(expected_identity) is not WireIdentity
            or expected_identity.role is not WireRole.SERVICE
            or expected_identity.delegate_ref is not None
            or type(expected_scope) is not WireScope
            or not _is_system_scope(expected_scope)
        ):
            raise SystemTelemetryProjectionError("INVALID_TRUSTED_BINDING")
        _validate_reference(system_ref)
        _validate_reference(process_ref)
        _validate_reference(event_type)
        _validate_reference(observation_schema)

        self._expected_identity = expected_identity
        self._expected_scope = expected_scope
        self._system_ref = system_ref
        self._process_ref = process_ref
        self._event_type = event_type
        self._observation_schema = observation_schema

    def project(self, event: WireEnvelope) -> dict[str, object]:
        """Return one JSON-ready telemetry append request or a finite error."""

        if type(event) is not WireEnvelope:
            raise SystemTelemetryProjectionError("INVALID_EVENT")
        header = event.header
        if header.identity != self._expected_identity:
            raise SystemTelemetryProjectionError("IDENTITY_MISMATCH")
        if header.scope != self._expected_scope:
            raise SystemTelemetryProjectionError("SCOPE_MISMATCH")
        try:
            validate_event(event, expected_scope=self._expected_scope)
        except Exception:
            raise SystemTelemetryProjectionError("INVALID_EVENT") from None
        if (
            header.operation != MARKET_EVENT_OPERATION
            or header.schema_id != MARKET_EVENT_SCHEMA
            or header.schema_version != MARKET_EVENT_SCHEMA_VERSION
        ):
            raise SystemTelemetryProjectionError("UNSUPPORTED_GATEWAY_EVENT")

        if set(event.payload) != {"key", "data"}:
            raise SystemTelemetryProjectionError("INVALID_MARKET_EVENT")
        raw_key = event.payload["key"]
        raw_data = event.payload["data"]
        if not isinstance(raw_key, Mapping) or not isinstance(raw_data, Mapping):
            raise SystemTelemetryProjectionError("INVALID_MARKET_EVENT")
        try:
            key = MarketSubscriptionKey.from_dict(raw_key)
        except (TypeError, ValueError):
            raise SystemTelemetryProjectionError("INVALID_MARKET_EVENT") from None
        if header.stream_id != key.stream_id:
            raise SystemTelemetryProjectionError("STREAM_KEY_MISMATCH")
        if type(header.stream_epoch) is not str or type(header.sequence) is not int:
            raise SystemTelemetryProjectionError("INVALID_EVENT")

        occurred_at = _timestamp_seconds(header.sent_at_utc)
        source = {
            "service_ref": header.identity.principal_ref,
            "stream_epoch": header.stream_epoch,
            "sequence": header.sequence,
            "gateway_sent_at_utc": header.sent_at_utc,
        }
        event_id = _stable_event_id(
            header.identity,
            header.stream_id,
            header.stream_epoch,
            header.sequence,
            self._system_ref,
            self._process_ref,
        )
        return {
            "schema_version": 1,
            "event_id": event_id,
            "event_type": self._event_type,
            "occurred_at": occurred_at,
            "data": {
                "schema": self._observation_schema,
                "scope_type": "system",
                "system_ref": self._system_ref,
                "process_ref": self._process_ref,
                "observation_kind": "consumer_received_frame",
                "source": source,
                "market": {
                    "instrument": key.instrument.to_dict(),
                    "channel": key.channel,
                    "depth": key.depth,
                    "timeframe": key.timeframe,
                },
            },
        }


def _is_system_scope(scope: WireScope) -> bool:
    return (
        scope.account_ref is None
        and not scope.account_refs
        and scope.strategy_ref is None
        and scope.run_id is None
        and scope.manual_book_ref is None
        and scope.portfolio_ref is None
        and scope.group_id is None
        and scope.leg_id is None
    )


def _validate_reference(value: Any) -> None:
    if type(value) is not str:
        raise SystemTelemetryProjectionError("INVALID_TRUSTED_BINDING")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        raise SystemTelemetryProjectionError("INVALID_TRUSTED_BINDING") from None
    if (
        not encoded
        or len(encoded) > MAX_REFERENCE_BYTES
        or value != value.strip()
        or not value.isprintable()
    ):
        raise SystemTelemetryProjectionError("INVALID_TRUSTED_BINDING")


def _timestamp_seconds(value: str) -> float:
    try:
        result = datetime.fromisoformat(value[:-1] + "+00:00").timestamp()
    except (OverflowError, OSError, ValueError):
        raise SystemTelemetryProjectionError("INVALID_SOURCE_TIME") from None
    if not math.isfinite(result):
        raise SystemTelemetryProjectionError("INVALID_SOURCE_TIME")
    return result


def _stable_event_id(
    identity: WireIdentity,
    stream_id: str,
    stream_epoch: str,
    sequence: int,
    system_ref: str,
    process_ref: str,
) -> str:
    canonical_identity = json.dumps(
        [
            identity.role.value,
            identity.principal_ref,
            identity.actor_ref,
            identity.delegate_ref,
            stream_id,
            stream_epoch,
            sequence,
            system_ref,
            process_ref,
        ],
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    return _EVENT_ID_PREFIX + hashlib.sha256(canonical_identity).hexdigest()


__all__ = [
    "GatewaySystemTelemetryProjector",
    "SystemTelemetryProjectionError",
]
