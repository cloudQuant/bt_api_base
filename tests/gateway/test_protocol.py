"""Tests for gateway/protocol.py."""

from __future__ import annotations

from datetime import datetime, timezone

from bt_api_base.gateway.models import GatewayTick


class TestProtocol:
    """Tests for gateway protocol."""

    def test_module_exists(self):
        """Test module can be imported."""
        from bt_api_base.gateway import protocol

        assert protocol is not None

    def test_quote_v2_tick_round_trip_retains_execution_evidence(self):
        event_time = datetime(2026, 9, 9, 1, 30, 1, tzinfo=timezone.utc)
        receive_time = datetime(2026, 9, 9, 1, 30, 2, tzinfo=timezone.utc)
        tick = GatewayTick(
            timestamp=event_time.timestamp(),
            symbol="SA701C1080",
            asset_type="option",
            price=60.0,
            bid_price=59.0,
            ask_price=61.0,
            bid_volume=2.0,
            ask_volume=3.0,
            schema_version="ctp.quote.v2",
            volume_semantics="delta",
            cum_volume=107.0,
            delta_volume=7.0,
            volume_complete=True,
            volume_quality="CONTINUOUS",
            continuity_status="continuous",
            quality_flags=(),
            lower_limit_price=1.0,
            upper_limit_price=100.0,
            event_time_utc=event_time,
            recv_time_utc=receive_time,
            recv_monotonic_ns=123,
            connection_generation=3,
            ingest_seq=8,
            subscription_epoch=2,
            rules_hash="rules-sha256",
            clock_domain_id="ctp-md-clock-a",
            source="ctp.native.md",
            event_time_source="action_day",
            source_clock_quality="verified",
            receive_clock_quality="verified",
            source_clock_error_ms=1.0,
            receive_clock_error_ms=1.0,
            freshness_verified=True,
            execution_eligible=True,
        )

        payload = tick.to_dict()
        restored = GatewayTick.from_dict(payload)

        assert payload["event_time_utc"] == event_time.isoformat()
        assert payload["recv_time_utc"] == receive_time.isoformat()
        assert restored.asset_type == "option"
        assert restored.subscription_epoch == 2
        assert restored.rules_hash == "rules-sha256"
        assert restored.source_clock_quality == "verified"
        assert restored.execution_eligible is True
