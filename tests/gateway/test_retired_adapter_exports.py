from __future__ import annotations

import pytest

from bt_api_base.gateway import adapters


@pytest.mark.parametrize("name", ["BinanceGatewayAdapter", "OkxGatewayAdapter"])
def test_gateway_adapter_export_is_retired(name: str) -> None:
    with pytest.raises(AttributeError, match=name):
        getattr(adapters, name)
