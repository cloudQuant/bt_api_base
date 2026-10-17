from __future__ import annotations

import pytest

from bt_api_base.gateway import adapters


def test_binance_gateway_adapter_export_is_retired() -> None:
    with pytest.raises(AttributeError, match="BinanceGatewayAdapter"):
        getattr(adapters, "BinanceGatewayAdapter")
