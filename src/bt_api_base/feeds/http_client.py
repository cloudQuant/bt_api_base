"""
 HTTP
 httpx /， requests 。
、、。
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any, cast

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]

from bt_api_base.error import (
    ServerError,
    UnifiedAuthError,
    UnifiedRateLimitError,
)
from bt_api_base.exceptions import RequestFailedError
from bt_api_base.feeds.transport_safety import (
    sanitize_text,
    sanitize_url,
    sensitive_mapping_values,
)
from bt_api_base.logging_factory import get_logger

logger = get_logger("http_client")


class HttpClient:
    """HTTP"""

    def __init__(
        self,
        venue: str = "",
        timeout: float = 10.0,
        max_connections: int = 100,
        max_keepalive_connections: int = 20,
        verify: bool = True,
        proxies: str | dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        """__init__ method"""
        if httpx is None:
            raise ImportError(
                "httpx is required for HttpClient. Install it with: pip install httpx"
            )

        self._venue = venue
        self.timeout = timeout

        limits = httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive_connections,
        )

        # httpx expects proxy as a URL string, but callers may pass a
        # requests-style dict like {"http": "...", "https": "..."}.
        proxy_url = None
        explicit_proxy_config = proxies is not None
        if proxies:
            if isinstance(proxies, dict):
                proxy_url = proxies.get("https") or proxies.get("http") or proxies.get("all")
            else:
                proxy_url = proxies
        trust_env = not explicit_proxy_config

        transport_kwargs: dict[str, Any] = {}
        if proxy_url:
            transport_kwargs["proxy"] = proxy_url

        #
        self._sync_client = httpx.Client(
            timeout=timeout,
            limits=limits,
            verify=verify,
            follow_redirects=False,
            trust_env=trust_env,
            **transport_kwargs,
        )

        # （）
        self._async_client: httpx.AsyncClient | None = None
        self._async_kwargs: dict[str, Any] = {
            "timeout": timeout,
            "limits": limits,
            "verify": verify,
            "follow_redirects": False,
            "trust_env": trust_env,
        }
        if proxy_url:
            self._async_kwargs["proxy"] = proxy_url

    def _get_async_client(self) -> httpx.AsyncClient:
        """"""
        if self._async_client is None or self._async_client.is_closed:
            self._async_client = httpx.AsyncClient(**self._async_kwargs)
        return self._async_client

    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        data: Any | None = None,
        timeout: float | None = None,
        cookies: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """"""
        req_kwargs: dict[str, Any] = {}
        if headers:
            req_kwargs["headers"] = headers
        if params is not None:
            req_kwargs["params"] = params
        if json_data is not None:
            req_kwargs["json"] = json_data
        if data is not None:
            req_kwargs["content"] = data
        if timeout is not None:
            req_kwargs["timeout"] = timeout

        #  cookies  Cookie header  httpx
        if cookies:
            cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())
            if "headers" not in req_kwargs:
                req_kwargs["headers"] = {}
            req_kwargs["headers"]["Cookie"] = cookie_header

        failure: RequestFailedError | None = None
        try:
            response = self._sync_client.request(method, url, **req_kwargs)
        except httpx.TimeoutException as e:
            message = sanitize_text(str(e), sensitive_values=sensitive_mapping_values(headers))
            failure = RequestFailedError(venue=self._venue, message=f"Request timeout: {message}")
        except httpx.ConnectError as e:
            message = sanitize_text(str(e), sensitive_values=sensitive_mapping_values(headers))
            failure = RequestFailedError(venue=self._venue, message=f"Connection error: {message}")
        except httpx.RequestError as e:
            message = sanitize_text(str(e), sensitive_values=sensitive_mapping_values(headers))
            failure = RequestFailedError(venue=self._venue, message=f"HTTP client error: {message}")

        if failure is not None:
            raise failure

        return self._process_response(response)

    async def async_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        data: Any | None = None,
        timeout: float | None = None,
        cookies: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """"""
        client = self._get_async_client()

        req_kwargs: dict[str, Any] = {}
        if headers:
            req_kwargs["headers"] = headers
        if params is not None:
            req_kwargs["params"] = params
        if json_data is not None:
            req_kwargs["json"] = json_data
        if data is not None:
            req_kwargs["content"] = data
        if timeout is not None:
            req_kwargs["timeout"] = timeout

        #  cookies  Cookie header  httpx
        if cookies:
            cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())
            if "headers" not in req_kwargs:
                req_kwargs["headers"] = {}
            req_kwargs["headers"]["Cookie"] = cookie_header

        failure: RequestFailedError | None = None
        try:
            response = await client.request(method, url, **req_kwargs)
        except httpx.TimeoutException as e:
            message = sanitize_text(str(e), sensitive_values=sensitive_mapping_values(headers))
            failure = RequestFailedError(
                venue=self._venue, message=f"Async request timeout: {message}"
            )
        except httpx.ConnectError as e:
            message = sanitize_text(str(e), sensitive_values=sensitive_mapping_values(headers))
            failure = RequestFailedError(
                venue=self._venue, message=f"Async connection error: {message}"
            )
        except httpx.RequestError as e:
            message = sanitize_text(str(e), sensitive_values=sensitive_mapping_values(headers))
            failure = RequestFailedError(
                venue=self._venue, message=f"Async HTTP client error: {message}"
            )

        if failure is not None:
            raise failure

        return self._process_response(response)

    def _process_response(self, response: httpx.Response) -> dict[str, Any]:
        """，"""
        status = response.status_code

        # 2xx success
        if response.is_success:
            try:
                return cast("dict[str, Any]", response.json())
            except (ValueError, UnicodeDecodeError):
                return {"text": response.text, "status_code": status}

        # 4xx client errors: return JSON body for exchange-specific handling.
        # Many exchanges (OKX, Binance, etc.) return structured error info in
        # 4xx responses that exchange-specific code handles via RequestData.
        # This matches the old requests-based behavior where only 404/410 raised.
        if 400 <= status < 500 and status not in (404, 410):
            logger.warning(
                "HTTP %s response from %s: %s",
                status,
                sanitize_url(str(response.url)),
                sanitize_text(response.text[:200]),
            )
            try:
                return cast("dict[str, Any]", response.json())
            except (ValueError, UnicodeDecodeError):
                pass  # fall through to raise

        # 5xx server errors, 404/410, and non-JSON 4xx: raise
        raise self._handle_error(response)

    def _handle_error(self, response: httpx.Response) -> Exception:
        """"""
        status = response.status_code
        try:
            body = response.json()
        except (ValueError, UnicodeDecodeError):
            body = {"text": response.text}

        if status == 429:
            err = UnifiedRateLimitError(venue=self._venue, response=body)
            retry_after = response.headers.get("Retry-After")
            if retry_after is not None:
                with suppress(ValueError, TypeError):
                    err.retry_after = float(retry_after)
            return err
        elif status in (401, 403):
            message = body.get("msg", body.get("message", "Auth error"))
            return UnifiedAuthError(
                venue=self._venue,
                response=body,
                message=f"HTTP {status}: {sanitize_text(message)}",
            )
        elif status >= 500:
            return ServerError(venue=self._venue, status=status, response=body)
        else:
            message = body.get("msg", body.get("message", "Request failed"))
            return RequestFailedError(
                venue=self._venue,
                status_code=status,
                message=f"HTTP {status}: {sanitize_text(message)}",
            )

    def close(self) -> None:
        """"""
        if not self._sync_client.is_closed:
            self._sync_client.close()
        self._close_async_client()

    def _close_async_client(self) -> None:
        async_client = self._async_client
        self._async_client = None
        if async_client is None or async_client.is_closed:
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            try:
                asyncio.run(async_client.aclose())
            except Exception as exc:
                logger.warning(
                    f"Failed to close async HTTP client for {self._venue}: "
                    f"{type(exc).__name__}: {sanitize_text(exc)}"
                )
            return

        task = loop.create_task(async_client.aclose())
        task.add_done_callback(self._handle_async_close_result)

    def _handle_async_close_result(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.warning(
                f"Failed to close async HTTP client for {self._venue}: "
                f"{type(exc).__name__}: {sanitize_text(exc)}"
            )

    async def aclose(self) -> None:
        """"""
        if not self._sync_client.is_closed:
            self._sync_client.close()
        if self._async_client and not self._async_client.is_closed:
            await self._async_client.aclose()

    def __enter__(self) -> HttpClient:
        """__enter__ method"""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """__exit__ method"""
        self.close()

    async def __aenter__(self) -> HttpClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        await self.aclose()
