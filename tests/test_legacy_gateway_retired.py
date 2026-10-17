"""The retired standalone gateway runtime is absent from bt_api_base."""

from __future__ import annotations

import importlib
from pathlib import Path

import bt_api_base
import pytest


_RETIRED_SUBMODULES = (
    "bt_api_base.gateway.adapters.base",
    "bt_api_base.gateway.adapters.plugin_adapter",
    "bt_api_base.gateway.config",
    "bt_api_base.gateway.health",
    "bt_api_base.gateway.models",
    "bt_api_base.gateway.order_identity_map",
    "bt_api_base.gateway.order_ref_allocator",
    "bt_api_base.gateway.protocol",
    "bt_api_base.gateway.registrar",
    "bt_api_base.gateway.runtime",
    "bt_api_base.gateway.runtime_remote",
    "bt_api_base.gateway.storage.tick_writer",
    "bt_api_base.gateway.subscription_manager",
)


def test_standalone_gateway_has_no_runtime_modules() -> None:
    package_root = Path(next(iter(bt_api_base.__path__)))
    gateway_root = package_root / "gateway"
    assert not tuple(gateway_root.rglob("*.py"))

    try:
        package = importlib.import_module("bt_api_base.gateway")
    except ModuleNotFoundError:
        return

    # An ignored __pycache__ directory can leave an empty namespace package in
    # an existing checkout; fresh installs do not carry that directory.
    assert package.__file__ is None
    assert not tuple(Path(next(iter(package.__path__))).rglob("*.py"))


@pytest.mark.parametrize("module_name", _RETIRED_SUBMODULES)
def test_legacy_gateway_modules_cannot_be_imported(module_name: str) -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module_name)
