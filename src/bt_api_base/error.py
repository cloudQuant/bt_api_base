"""

、。
。

:
    bt_api_base :
    - exceptions.py:  (RateLimitError, RequestError )，
    - error.py ():  (UnifiedError )，

     (UnifiedRateLimitError, UnifiedAuthError ) ，
     ``except RateLimitError``  ``UnifiedRateLimitError``。
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from enum import Enum, unique
from typing import TYPE_CHECKING, Any, ClassVar

from bt_api_base._compat import StrEnum
from bt_api_base.exceptions import (
    AuthenticationError,
    BtApiError,
    RateLimitError,
    RequestFailedError,
)

# ──  ─────────────────────────────────────────────────


@unique
class ErrorCategory(StrEnum):
    """Class ErrorCategory"""
    NETWORK = "network"
    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    BUSINESS = "business"
    SYSTEM = "system"
    CAPABILITY = "capability"
    VALIDATION = "validation"
    API = "api"
    ORDER = "order"
    TRADE = "trade"
    ACCOUNT = "account"


# ──  ────────────────────────────────────────────────


@unique
class UnifiedErrorCode(int, Enum):
    #  (1xxx)
    """Class UnifiedErrorCode"""
    NETWORK_TIMEOUT = 1001
    NETWORK_DISCONNECTED = 1002
    DNS_ERROR = 1003
    CONNECTION_REFUSED = 1004

    #  (2xxx)
    INVALID_API_KEY = 2001
    INVALID_SIGNATURE = 2002
    EXPIRED_TIMESTAMP = 2003
    PERMISSION_DENIED = 2004
    SESSION_EXPIRED = 2005

    #  (3xxx)
    RATE_LIMIT_EXCEEDED = 3001
    IP_BANNED = 3002
    TOO_MANY_REQUESTS = 3003

    #  (4xxx)
    INVALID_SYMBOL = 4001
    INVALID_PRICE = 4002
    INVALID_VOLUME = 4003
    INSUFFICIENT_BALANCE = 4004
    INSUFFICIENT_MARGIN = 4005
    ORDER_NOT_FOUND = 4006
    ORDER_ALREADY_FILLED = 4007
    ORDER_CANCELLED = 4008
    ORDER_TIMEOUT = 4009
    MARKET_CLOSED = 4010
    POSITION_NOT_FOUND = 4011
    DUPLICATE_ORDER = 4012
    INVALID_ORDER = 4013
    MIN_NOTIONAL = 4014
    MINIMUM_NOT_MET = 4015
    PRECISION_ERROR = 4016
    ORDER_CANCEL_FAILED = 4017
    INVALID_SIDE = 4018
    INVALID_ORDER_TYPE = 4019
    WITHDRAWAL_FAILED = 4020
    DEPOSIT_FAILED = 4021
    TRANSFER_FAILED = 4022
    ACCOUNT_SUSPENDED = 4023

    #  (5xxx)
    EXCHANGE_MAINTENANCE = 5001
    EXCHANGE_OVERLOADED = 5002
    INTERNAL_ERROR = 5003
    UNSUPPORTED_OPERATION = 5004

    #  (6xxx)
    NOT_SUPPORTED = 6001
    NOT_IMPLEMENTED = 6002

    #  (7xxx)
    INVALID_PARAMETER = 7001
    MISSING_PARAMETER = 7002
    PARAMETER_OUT_OF_RANGE = 7003

    #  (8xxx) — 
    API_ERROR = 8001
    ORDER_ERROR = 8002
    TRADE_ERROR = 8003
    ACCOUNT_ERROR = 8004


# ──  ──────────────────────────────────────────────────


@dataclass
class UnifiedError(BtApiError):
    """， BtApiError """

    code: UnifiedErrorCode
    category: ErrorCategory
    venue: str
    message: str
    original_error: str | None = None
    context: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{self.venue}] {self.code.name}: {self.message}"

    def __repr__(self) -> str:
        return f"UnifiedError(code={self.code.name}, venue={self.venue}, message={self.message!r})"

    def to_dict(self) -> dict[str, Any]:
        """to_dict method"""
        return {
            "code": self.code.value,
            "code_name": self.code.name,
            "category": self.category.value,
            "venue": self.venue,
            "message": self.message,
            "original_error": self.original_error,
            "context": self.context,
        }


# ──  ──────────────────────────────────────────────


class UnifiedRateLimitError(UnifiedError, RateLimitError):
    """

     UnifiedError  exceptions.RateLimitError，
     ``except RateLimitError`` 。
    """

    def __init__(
        self,
        venue: str,
        response: Any = None,
        message: str = "Rate limit exceeded",
    ) -> None:
        """__init__ method"""
        UnifiedError.__init__(
            self,
            code=UnifiedErrorCode.RATE_LIMIT_EXCEEDED,
            category=ErrorCategory.RATE_LIMIT,
            venue=venue,
            message=message,
            context={"raw_response": response} if response else {},
        )
        # exceptions.RateLimitError 
        self.exchange_name = venue
        self.retry_after = None


class UnifiedAuthError(UnifiedError, AuthenticationError):
    """

     UnifiedError  exceptions.AuthenticationError，
     ``except AuthenticationError`` 。
    """

    def __init__(
        self,
        venue: str,
        response: Any = None,
        message: str = "Authentication failed",
    ) -> None:
        """__init__ method"""
        UnifiedError.__init__(
            self,
            code=UnifiedErrorCode.INVALID_API_KEY,
            category=ErrorCategory.AUTH,
            venue=venue,
            message=message,
            context={"raw_response": response} if response else {},
        )
        # exceptions.AuthenticationError 
        self.exchange_name = venue


class ServerError(UnifiedError):
    """"""

    def __init__(
        self,
        venue: str,
        status: int = 500,
        response: Any = None,
        message: str = "Server error",
    ) -> None:
        """__init__ method"""
        super().__init__(
            code=UnifiedErrorCode.INTERNAL_ERROR,
            category=ErrorCategory.SYSTEM,
            venue=venue,
            message=message,
            context={"status": status, "raw_response": response},
        )


class UnifiedRequestFailedError(UnifiedError, RequestFailedError):
    """（）

     UnifiedError  exceptions.RequestFailedError，
     ``except RequestFailedError`` 。
    """

    def __init__(
        self,
        venue: str,
        status: int = 0,
        response: Any = None,
        message: str = "Request failed",
    ) -> None:
        """__init__ method"""
        UnifiedError.__init__(
            self,
            code=UnifiedErrorCode.INTERNAL_ERROR,
            category=ErrorCategory.SYSTEM,
            venue=venue,
            message=message,
            context={"status": status, "raw_response": response},
        )
        # exceptions.RequestFailedError 
        self.exchange_name = venue
        self.status_code = status


# ──  ────────────────────────────────────────────────


class ErrorTranslator:
    """"""

    # : {: (UnifiedErrorCode, )}
    ERROR_MAP: ClassVar[dict[Any, tuple[UnifiedErrorCode | None, str]]] = {}

    #  HTTP 
    HTTP_STATUS_MAP: ClassVar[dict[int, tuple[UnifiedErrorCode, str]]] = {
        400: (UnifiedErrorCode.INVALID_PARAMETER, "Invalid request parameters"),
        401: (UnifiedErrorCode.INVALID_API_KEY, "Invalid API key"),
        403: (UnifiedErrorCode.PERMISSION_DENIED, "Permission denied"),
        404: (UnifiedErrorCode.INVALID_SYMBOL, "Resource not found"),
        429: (UnifiedErrorCode.RATE_LIMIT_EXCEEDED, "Rate limit exceeded"),
        500: (UnifiedErrorCode.INTERNAL_ERROR, "Internal server error"),
        503: (UnifiedErrorCode.EXCHANGE_OVERLOADED, "Service unavailable"),
        504: (UnifiedErrorCode.NETWORK_TIMEOUT, "Gateway timeout"),
    }

    @classmethod
    def translate(cls, raw_error: dict[str, Any], venue: str) -> UnifiedError | None:
        """

        :param raw_error:  (code, msg/message, status )
        :param venue: 
        :return: UnifiedError
        """
        code = raw_error.get("code")
        msg = raw_error.get("msg", raw_error.get("message", ""))
        status = raw_error.get("status")

        # 1. 
        if code is not None and code in cls.ERROR_MAP:
            unified_code, default_msg = cls.ERROR_MAP[code]
            if unified_code is None:
                return None  # （ CTP  0）
            return UnifiedError(
                code=unified_code,
                category=cls._get_category(unified_code),
                venue=venue,
                message=msg or default_msg,
                original_error=f"{code}: {msg}",
                context={"raw_response": raw_error},
            )

        # 2.  HTTP 
        if status and status in cls.HTTP_STATUS_MAP:
            unified_code, default_msg = cls.HTTP_STATUS_MAP[status]
            return UnifiedError(
                code=unified_code,
                category=cls._get_category(unified_code),
                venue=venue,
                message=msg or default_msg,
                original_error=f"HTTP {status}: {msg}",
                context={"raw_response": raw_error},
            )

        # 3. 
        return UnifiedError(
            code=UnifiedErrorCode.INTERNAL_ERROR,
            category=ErrorCategory.SYSTEM,
            venue=venue,
            message=msg or "Unknown error",
            original_error=str(raw_error),
            context={"raw_response": raw_error},
        )

    @classmethod
    def _get_category(cls, code: UnifiedErrorCode) -> ErrorCategory:
        """"""
        v = code.value
        if 1000 <= v < 2000:
            return ErrorCategory.NETWORK
        elif 2000 <= v < 3000:
            return ErrorCategory.AUTH
        elif 3000 <= v < 4000:
            return ErrorCategory.RATE_LIMIT
        elif 4000 <= v < 5000:
            return ErrorCategory.BUSINESS
        elif 5000 <= v < 6000:
            return ErrorCategory.SYSTEM
        elif 6000 <= v < 7000:
            return ErrorCategory.CAPABILITY
        else: return ErrorCategory.VALIDATION


class OKXErrorTranslator(ErrorTranslator):
    """OKX API """

    ERROR_MAP = {
        "0": (None, "Success"),
        "50000": (UnifiedErrorCode.INTERNAL_ERROR, "Body can not be empty"),
        "50001": (UnifiedErrorCode.EXCHANGE_MAINTENANCE, "Service temporarily unavailable"),
        "50004": (UnifiedErrorCode.NETWORK_TIMEOUT, "Endpoint request timeout"),
        "50011": (UnifiedErrorCode.RATE_LIMIT_EXCEEDED, "Rate limit reached"),
        "50013": (UnifiedErrorCode.EXCHANGE_OVERLOADED, "System busy"),
        "50014": (UnifiedErrorCode.INVALID_PARAMETER, "Parameter error"),
        "50100": (UnifiedErrorCode.INVALID_API_KEY, "API frozen"),
        "50101": (UnifiedErrorCode.INVALID_API_KEY, "API key does not match"),
        "50102": (UnifiedErrorCode.EXPIRED_TIMESTAMP, "Timestamp expired"),
        "50103": (UnifiedErrorCode.INVALID_SIGNATURE, "Signature invalid"),
        "50104": (UnifiedErrorCode.PERMISSION_DENIED, "No permission"),
        "50105": (UnifiedErrorCode.PERMISSION_DENIED, "IP not whitelisted"),
        "51000": (UnifiedErrorCode.INVALID_PARAMETER, "Parameter error"),
        "51001": (UnifiedErrorCode.INVALID_SYMBOL, "Instrument ID does not exist"),
        "51004": (UnifiedErrorCode.INVALID_VOLUME, "Order amount too small"),
        "51008": (UnifiedErrorCode.INSUFFICIENT_BALANCE, "Insufficient balance"),
        "51009": (UnifiedErrorCode.INSUFFICIENT_MARGIN, "Insufficient margin"),
        "51010": (UnifiedErrorCode.INVALID_PRICE, "Price not meeting post-only rule"),
        "51020": (UnifiedErrorCode.ORDER_NOT_FOUND, "Order does not exist"),
        "51023": (UnifiedErrorCode.DUPLICATE_ORDER, "Duplicate order"),
        "51024": (UnifiedErrorCode.ORDER_ALREADY_FILLED, "Order already filled"),
        "51503": (UnifiedErrorCode.INVALID_PARAMETER, "Reduce-only parameter error"),
    }

    @classmethod
    def translate(cls, raw_error: dict, venue: str) -> UnifiedError | None:
        """OKX ，"""
        code = raw_error.get("code", raw_error.get("sCode", ""))
        msg = raw_error.get("msg", raw_error.get("sMsg", ""))
        code_str = str(code) if code is not None else ""

        if code_str in cls.ERROR_MAP:
            unified_code, default_msg = cls.ERROR_MAP[code_str]
            if unified_code is None:
                return None
            return UnifiedError(
                code=unified_code,
                category=cls._get_category(unified_code),
                venue=venue,
                message=msg or default_msg,
                original_error=f"{code}: {msg}",
                context={"raw_response": raw_error},
            )

        return super().translate(raw_error, venue)


_TRANSLATOR_EXPORTS: dict[str, tuple[str, str]] = {
    "BinanceErrorTranslator": (
        "bt_api_binance.errors.binance_translator",
        "BinanceErrorTranslator",
    )
}


def __getattr__(name: str) -> type[Any]:
    """Lazy re-export installed translator plugins."""
    if name in _TRANSLATOR_EXPORTS:
        module_name, attr = _TRANSLATOR_EXPORTS[name]
        try:
            module = importlib.import_module(module_name)
            value = getattr(module, attr)
            globals()[name] = value
            return value
        except (ImportError, AttributeError):
            pass
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if TYPE_CHECKING:
    # For type checkers and IDEs, make exports visible without importing at runtime.
    from bt_api_binance.errors.binance_translator import (
        BinanceErrorTranslator as BinanceErrorTranslator,
    )

__all__ = [
    # 
    "ErrorCategory",
    "UnifiedErrorCode",
    "UnifiedError",
    "UnifiedRateLimitError",
    "UnifiedAuthError",
    "ServerError",
    "UnifiedRequestFailedError",
    "ErrorTranslator",
    "OKXErrorTranslator",
    # （；）
    "BinanceErrorTranslator",
]
