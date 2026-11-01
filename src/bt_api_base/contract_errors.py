"""Provider-neutral public errors for typed API contracts."""

from __future__ import annotations

from bt_api_base.exceptions import BtApiError


class BtApiContractError(BtApiError):
    """Base error for the v1 BtApi typed contract."""


class CapabilityNotSupportedError(BtApiContractError):
    """Raised when an operation is not supported by the selected venue."""

    def __init__(self, operation: str, *, detail: str = "", definite_reject: bool = False) -> None:
        message = f"capability not supported: {operation}"
        if detail:
            message = f"{message} — {detail}"
        super().__init__(message)
        self.operation = operation
        self.detail = detail
        self.definite_reject = definite_reject


__all__ = ("BtApiContractError", "CapabilityNotSupportedError")
