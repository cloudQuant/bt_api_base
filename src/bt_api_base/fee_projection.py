"""Explicit marker for a provider's legacy generic fee projection."""

from __future__ import annotations


def legacy_fee_projection() -> None:
    """Select existing generic fee normalization without claiming fee support.

    The SDK recognizes the function by identity. It is a registration marker,
    not a provider implementation or evidence of account fee capability.
    """


__all__ = ("legacy_fee_projection",)
