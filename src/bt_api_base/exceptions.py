"""
bt_api_base 
， assert / raise Exception / ConnectionError
"""

from __future__ import annotations

__all__ = [
    "BtApiError",
    "ExchangeNotFoundError",
    "ExchangeConnectionError",
    "ExchangeConnectionAlias",
    "AuthenticationError",
    "RequestTimeoutError",
    "RequestError",
    "RequestFailedError",
    "OrderError",
    "SubscribeError",
    "DataParseError",
    "RateLimitError",
    "NetworkError",
    "InvalidSymbolError",
    "InsufficientBalanceError",
    "InvalidOrderError",
    "OrderNotFoundError",
    "ConfigurationError",
    "WebSocketError",
    "CurrencyNotFoundError",
    "QueueNotInitializedError",
    "is_network_error",
    "is_auth_error",
    "is_rate_limit_error",
    "is_order_error",
    "is_user_recoverable",
]


def is_network_error(error: Exception) -> bool:
    """Check if error is network-related (connection, timeout, etc.)."""
    return isinstance(error, (NetworkError, RequestTimeoutError, WebSocketError, ConnectionError))


def is_auth_error(error: Exception) -> bool:
    """Check if error is authentication-related."""
    return isinstance(error, AuthenticationError)


def is_rate_limit_error(error: Exception) -> bool:
    """Check if error is rate-limit-related."""
    return isinstance(error, RateLimitError)


def is_order_error(error: Exception) -> bool:
    """Check if error is order-related (insufficient balance, invalid order, etc.)."""
    return isinstance(error, OrderError)


def is_user_recoverable(error: Exception) -> bool:
    """Check if error can be recovered by user action (e.g., fix params, retry later)."""
    recoverable_types = (
        InvalidSymbolError,
        InsufficientBalanceError,
        InvalidOrderError,
        ConfigurationError,
        RateLimitError,
    )
    return isinstance(error, recoverable_types)


class BtApiError(Exception):
    """bt_api_base """

    __slots__ = ()

    def __repr__(self) -> str:
        cls_name = self.__class__.__name__
        args = []
        for cls in type(self).__mro__:
            slots = getattr(cls, "__slots__", ())
            for slot in slots:
                if hasattr(self, slot):
                    args.append(f"{slot}={getattr(self, slot)!r}")
        return f"{cls_name}({', '.join(args)})" if args else f"{cls_name}()"


class ExchangeNotFoundError(BtApiError):
    """"""

    __slots__ = ("exchange_name", "available")

    def __init__(self, exchange_name: str, available: str | list[str] | None = None) -> None:
        """__init__ method"""
        msg = f"Exchange not found: {exchange_name}"
        if available:
            msg += f". Available: {available}"
        super().__init__(msg)
        self.exchange_name = exchange_name
        self.available = available


class ExchangeConnectionError(BtApiError):
    """"""

    __slots__ = ("exchange_name",)

    def __init__(self, exchange_name: str, detail: str = "") -> None:
        """__init__ method"""
        msg = f"Connection failed: {exchange_name}"
        if detail:
            msg += f" — {detail}"
        super().__init__(msg)
        self.exchange_name = exchange_name


# （， ExchangeConnectionError）
# ： ConnectionError， Python 
ExchangeConnectionAlias = ExchangeConnectionError


class AuthenticationError(ExchangeConnectionError):
    """（API Key /  / ）"""

    __slots__ = ()


class RequestTimeoutError(BtApiError):
    """REST / """

    __slots__ = ("exchange_name", "url", "timeout")

    def __init__(self, exchange_name: str, url: str = "", timeout: int | float = 0) -> None:
        """__init__ method"""
        msg = f"{exchange_name} request timeout ({timeout}s)"
        if url:
            msg += f": {url}"
        super().__init__(msg)
        self.exchange_name = exchange_name
        self.url = url
        self.timeout = timeout


class RequestError(BtApiError):
    """REST （）"""

    __slots__ = ("exchange_name",)

    def __init__(self, exchange_name: str, url: str = "", detail: str = "") -> None:
        """__init__ method"""
        msg = f"{exchange_name} request error"
        if url:
            msg += f": {url}"
        if detail:
            msg += f" — {detail}"
        super().__init__(msg)
        self.exchange_name = exchange_name


class OrderError(BtApiError):
    """ / """

    __slots__ = ("exchange_name", "symbol")

    def __init__(self, exchange_name: str, symbol: str = "", detail: str = "") -> None:
        """__init__ method"""
        msg = f"{exchange_name} order error"
        if symbol:
            msg += f" [{symbol}]"
        if detail:
            msg += f": {detail}"
        super().__init__(msg)
        self.exchange_name = exchange_name
        self.symbol = symbol


class SubscribeError(BtApiError):
    """"""

    __slots__ = ("exchange_name",)

    def __init__(self, exchange_name: str, detail: str = "") -> None:
        """__init__ method"""
        msg = f"{exchange_name} subscribe error"
        if detail:
            msg += f": {detail}"
        super().__init__(msg)
        self.exchange_name = exchange_name


class DataParseError(BtApiError):
    """"""

    __slots__ = ("container_class", "detail")

    def __init__(self, container_class: str = "", detail: str = "") -> None:
        """__init__ method"""
        msg = "Data parse error"
        if container_class:
            msg += f" in {container_class}"
        if detail:
            msg += f": {detail}"
        super().__init__(msg)
        self.container_class = container_class
        self.detail = detail


class RateLimitError(BtApiError):
    """API """

    __slots__ = ("exchange_name", "retry_after")

    def __init__(
        self, exchange_name: str, retry_after: int | float | None = None, detail: str = ""
    ) -> None:
        """__init__ method"""
        msg = f"{exchange_name} rate limit exceeded"
        if retry_after:
            msg += f" (retry after {retry_after}s)"
        if detail:
            msg += f": {detail}"
        super().__init__(msg)
        self.exchange_name = exchange_name
        self.retry_after = retry_after


class NetworkError(BtApiError):
    """（、DNS ）"""

    __slots__ = ("exchange_name",)

    def __init__(self, exchange_name: str, detail: str = "") -> None:
        """__init__ method"""
        msg = f"{exchange_name} network error"
        if detail:
            msg += f": {detail}"
        super().__init__(msg)
        self.exchange_name = exchange_name


class InvalidSymbolError(BtApiError):
    """"""

    __slots__ = ("exchange_name", "symbol")

    def __init__(self, exchange_name: str, symbol: str, detail: str = "") -> None:
        """__init__ method"""
        msg = f"{exchange_name} invalid symbol: {symbol}"
        if detail:
            msg += f" — {detail}"
        super().__init__(msg)
        self.exchange_name = exchange_name
        self.symbol = symbol


class InsufficientBalanceError(OrderError):
    """"""

    __slots__ = ("required", "available")

    def __init__(
        self,
        exchange_name: str,
        symbol: str = "",
        required: float | None = None,
        available: float | None = None,
    ) -> None:
        """__init__ method"""
        detail = "Insufficient balance"
        if required is not None and available is not None:
            detail += f" (required: {required}, available: {available})"
        super().__init__(exchange_name, symbol, detail)
        self.required = required
        self.available = available


class InvalidOrderError(OrderError):
    """（、）"""

    __slots__ = ()


class OrderNotFoundError(OrderError):
    """"""

    __slots__ = ("order_id",)

    def __init__(self, exchange_name: str, order_id: str, symbol: str = "") -> None:
        """__init__ method"""
        detail = f"Order not found: {order_id}"
        super().__init__(exchange_name, symbol, detail)
        self.order_id = order_id


class ConfigurationError(BtApiError):
    """（、）"""

    __slots__ = ("detail",)

    def __init__(self, detail: str = "") -> None:
        """__init__ method"""
        msg = "Configuration error"
        if detail:
            msg += f": {detail}"
        super().__init__(msg)
        self.detail = detail


class WebSocketError(BtApiError):
    """WebSocket """

    __slots__ = ("exchange_name",)

    def __init__(self, exchange_name: str, detail: str = "") -> None:
        """__init__ method"""
        msg = f"{exchange_name} WebSocket error"
        if detail:
            msg += f": {detail}"
        super().__init__(msg)
        self.exchange_name = exchange_name


class CurrencyNotFoundError(BtApiError):
    """Currency not found in exchange account."""

    __slots__ = ("exchange_name", "currency")

    def __init__(self, exchange_name: str, currency: str) -> None:
        """__init__ method"""
        msg = f"Currency '{currency}' not found in {exchange_name}"
        super().__init__(msg)
        self.exchange_name = exchange_name
        self.currency = currency


class QueueNotInitializedError(DataParseError):
    """Raised when data_queue is not initialized before data parsing."""

    __slots__ = ("queue_name",)

    def __init__(self, queue_name: str = "", detail: str = "") -> None:
        """__init__ method"""
        msg = "Data queue not initialized"
        if queue_name:
            msg += f": {queue_name}"
        if detail:
            msg += f" — {detail}"
        super().__init__(container_class="DataQueue", detail=msg)
        self.queue_name = queue_name


class RequestFailedError(RequestError):
    """（ HTTP ）"""

    __slots__ = ("venue", "status_code")

    def __init__(
        self,
        exchange_name: str | None = None,
        url: str = "",
        detail: str = "",
        *,
        venue: str = "",
        message: str = "",
        status_code: int | None = None,
    ) -> None:
        # Backward compatibility:
        # - Old call sites: RequestFailedError(exchange_name, url=..., detail=...)
        # - New call sites (HttpClient): RequestFailedError(venue=..., message=..., status_code=...)
        """__init__ method"""
        name = exchange_name or venue or ""
        msg = message or detail or "Request failed"
        if status_code is not None:
            msg = f"{msg} (HTTP {status_code})"

        super().__init__(exchange_name=name or "unknown", url=url, detail=msg)
        self.venue = name
        self.status_code = status_code
