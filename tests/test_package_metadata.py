"""Tests for package metadata exposed to users."""

from __future__ import annotations

import bt_api_base
from bt_api_base._version import __version__


def test_package_exports_version() -> None:
    assert bt_api_base.__version__ == __version__
    assert bt_api_base.__version__
