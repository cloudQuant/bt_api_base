"""Tests for gateway runtime configuration."""

from __future__ import annotations

from bt_api_base.gateway.config import GatewayConfig


def test_gateway_config_from_kwargs_allocates_named_runtime() -> None:
    config = GatewayConfig.from_kwargs(
        exchange_type="ctp",
        asset_type="future",
        account_id="089763",
        runtime_name="ctp-future-089763",
    )

    assert config.runtime_name == "ctp-future-089763"
    assert config.exchange_type == "CTP"
    assert config.asset_type == "FUTURE"
    assert config.account_id == "089763"
    assert config.command_endpoint.startswith("tcp://")
    assert config.event_endpoint.startswith("tcp://")
    assert config.market_endpoint.startswith("tcp://")
