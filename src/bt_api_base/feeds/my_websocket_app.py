"""Module documentation"""

from __future__ import annotations

import datetime
import math
import os
import random
import ssl
import threading
import time
import traceback
from typing import Any

import websocket
from websocket import _app as websocket_app_module
from websocket._handshake import SUPPORTED_REDIRECT_STATUSES

from bt_api_base.feeds.transport_safety import (
    sanitize_text,
    sanitize_url,
    sanitize_value,
)
from bt_api_base.functions.utils import get_project_log_path
from bt_api_base.logging_factory import get_logger

_PROXY_ENV_KEYS = (
    "HTTPS_PROXY",
    "https_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "ALL_PROXY",
    "all_proxy",
    "SOCKS_PROXY",
    "socks_proxy",
)


class _NoRedirectWebSocket(websocket_app_module.WebSocket):
    """WebSocketApp transport that rejects every HTTP redirect before callbacks run."""

    _btapi_redirects_disabled = True

    def connect(self, url: str, **options: Any) -> None:
        # WebSocketApp does not expose redirect_limit. Passing zero prevents the
        # library from opening the redirect target, and the explicit status
        # check prevents a 30x response from being treated as an open socket.
        options["redirect_limit"] = 0
        super().connect(url, **options)
        response = self.handshake_response
        if response is None or response.status not in SUPPORTED_REDIRECT_STATUSES:
            return
        sock = self.sock
        if sock is not None:
            sock.close()
        self.sock = None
        self.connected = False
        raise websocket.WebSocketException("WebSocket redirects are disabled")


if not getattr(websocket_app_module.WebSocket, "_btapi_redirects_disabled", False):
    # WebSocketApp resolves this module global whenever it creates its socket.
    # Installing the fail-closed transport once covers all SDK streams without
    # changing websocket-client or holding a lock for the connection lifetime.
    websocket_app_module.WebSocket = _NoRedirectWebSocket


class WebSocketSubscriptionError(RuntimeError):
    """A deterministic subscription rejection that must stop automatic retries."""

    def __init__(self, message: str, *, code: Any = None) -> None:
        self.code = sanitize_text(code) if code is not None else None
        self.fatal = True
        super().__init__(sanitize_text(message))


# from bt_api_base.containers.exchanges.binance_swap_exchange_data import BinanceExchangeData
# from bt_api_base.containers.exchanges.okx_swap_exchange_data import OkxSwapExchangeData


class MyWebsocketApp:
    """Class MyWebsocketApp"""

    def __init__(self, data_queue: Any = None, **kwargs: Any) -> None:
        """__init__ method"""
        self.ws: websocket.WebSocketApp | None = None
        self.data_queue = data_queue
        self.wss_name = kwargs.get("wss_name", "default_name")
        self._stream_role = kwargs.get("stream_role", "market")
        self._connection_generation = 0
        self._params = kwargs.get("exchange_data")
        self.wss_url = kwargs.get("wss_url")
        if self.wss_url is None:
            assert self._params is not None, "exchange_data required when wss_url not provided"
            self.wss_url = self._params.get_wss_url()
        self.ping_interval = kwargs.get("ping_interval", 10)
        self.ping_timeout = kwargs.get("ping_timeout", 5)
        self.sslopt = dict(kwargs.get("sslopt") or {})
        cert_reqs = self.sslopt.setdefault("cert_reqs", ssl.CERT_REQUIRED)
        check_hostname = self.sslopt.setdefault("check_hostname", True)
        if cert_reqs != ssl.CERT_REQUIRED or check_hostname is not True:
            raise ValueError("WebSocket TLS certificate and hostname verification are required")
        self.start_config = {
            "ping_interval": self.ping_interval,
            "ping_timeout": self.ping_timeout,
            "sslopt": self.sslopt,
        }
        self.restart_gap = kwargs.get("restart_gap", 0)
        self.http_proxy_host = kwargs.get("http_proxy_host")
        self.http_proxy_port = kwargs.get("http_proxy_port")
        if self.http_proxy_host is None:
            try:
                import urllib.request
                from urllib.parse import urlparse

                system_proxies = urllib.request.getproxies()
                proxy_url = system_proxies.get("http") or system_proxies.get("https")
                if proxy_url:
                    parsed = urlparse(proxy_url)
                    if parsed.scheme in ("http", "https"):
                        self.http_proxy_host = parsed.hostname
                        self.http_proxy_port = parsed.port
            except Exception as e:
                get_logger("my_websocket_app").debug(
                    "Failed to parse system proxy: %s", e, exc_info=True
                )
        default_log = get_project_log_path("my_websocket_app.log")
        self.log_file_name = kwargs.get("log_file_name", default_log)
        self.wss_logger = get_logger("unknown")
        self._running_flag = False  # ，
        self._restart_flag = True
        self._stop_event = threading.Event()
        self._shutdown_timeout = float(kwargs.get("shutdown_timeout", 5.0))
        raw_idle_timeout = kwargs.get("message_idle_timeout", 0.0)
        if isinstance(raw_idle_timeout, bool):
            raise ValueError("message_idle_timeout must be a finite nonnegative number")
        self.message_idle_timeout = float(raw_idle_timeout)
        if not math.isfinite(self.message_idle_timeout) or self.message_idle_timeout < 0:
            raise ValueError("message_idle_timeout must be a finite nonnegative number")
        raw_readiness_timeout = kwargs.get("readiness_timeout", 30.0)
        if isinstance(raw_readiness_timeout, bool):
            raise ValueError("readiness_timeout must be a finite nonnegative number")
        self.readiness_timeout = float(raw_readiness_timeout)
        if not math.isfinite(self.readiness_timeout) or self.readiness_timeout < 0:
            raise ValueError("readiness_timeout must be a finite nonnegative number")
        self._last_message_at: float | None = None
        self._awaiting_ready = False
        self._tracking_subscription_batch = False
        self._pending_subscription_acks = 0
        self._subscription_batch_send_count = 0
        self._idle_close_requested = False
        self._readiness_deadline: float | None = None
        self._readiness_generation = 0
        self._readiness_ws: websocket.WebSocketApp | None = None
        self._subscription_lock = threading.Lock()
        self._watchdog_process: threading.Thread | None = None
        self._readiness_watchdog_process: threading.Thread | None = None
        self._restart_process: threading.Thread | None = None
        self.process = threading.Thread(target=self.run, daemon=True)

        # ──  ──────────────────────────────────────
        self._reconnect_base_delay = kwargs.get("reconnect_base_delay", 1.0)
        self._reconnect_max_delay = kwargs.get("reconnect_max_delay", 60.0)
        self._max_reconnect_attempts = kwargs.get("max_reconnect_attempts", 0)  # 0=
        self._reconnect_attempt = 0
        self._current_delay = self._reconnect_base_delay

        # ── EventBus （） ────────────────────────────────
        self._event_bus = kwargs.get("event_bus")

    # noinspection PyMethodMayBeStatic
    def get_timestamp(self, time_str) -> Any:
        """get_timestamp method"""
        dt = datetime.datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%S.%fZ")
        timestamp = int((time.mktime(dt.timetuple()) + dt.microsecond / 1000000) * 1000)
        return timestamp

    def subscribe(self, **kwargs):
        """subscribe method"""
        if self._params is None:
            raise ValueError("exchange_data (params) is required for subscribe")
        req = self._params.get_wss_path(**kwargs)
        if self.ws is None:
            raise ConnectionError("WebSocket connection not established")
        tracked = False
        with self._subscription_lock:
            if self._tracking_subscription_batch:
                self._pending_subscription_acks += 1
                self._subscription_batch_send_count += 1
                tracked = True
        try:
            self.ws.send(req)
        except Exception:
            if tracked:
                with self._subscription_lock:
                    self._pending_subscription_acks = max(0, self._pending_subscription_acks - 1)
                    self._subscription_batch_send_count = max(
                        0, self._subscription_batch_send_count - 1
                    )
            raise
        # time.sleep(0.3)

    def _begin_subscription_batch(self) -> None:
        """Track exchange acknowledgements for subscriptions sent in one batch."""
        with self._subscription_lock:
            self._awaiting_ready = True
            self._tracking_subscription_batch = True
            self._pending_subscription_acks = 0
            self._subscription_batch_send_count = 0

    def _end_subscription_batch(self) -> bool:
        """Finish sending a batch and report whether no acknowledgement is needed."""
        with self._subscription_lock:
            self._tracking_subscription_batch = False
            return self._pending_subscription_acks == 0

    def _subscription_acknowledged(self) -> None:
        """Mark one tracked subscription ready and publish readiness after the last ACK."""
        with self._subscription_lock:
            if self._pending_subscription_acks <= 0:
                return
            self._pending_subscription_acks -= 1
            ready = self._pending_subscription_acks == 0 and not self._tracking_subscription_batch
        if ready:
            self._mark_ready()

    def _mark_ready(self) -> None:
        """Publish readiness once the transport and requested subscriptions are active."""
        with self._subscription_lock:
            already_ready = self._running_flag and not self._awaiting_ready
            self._awaiting_ready = False
            self._idle_close_requested = False
            self._readiness_deadline = None
            self._last_message_at = time.monotonic()
            self._running_flag = True
        self._reset_backoff()
        if not already_ready:
            self._emit_event("ws.connected")

    def _emit_event(self, event_type, **payload):
        """EventBus  WebSocket （）."""
        if self._event_bus is not None:
            params = getattr(self, "_params", None)
            safe_payload = sanitize_value(payload)
            self._event_bus.emit(
                event_type,
                {
                    **safe_payload,
                    "wss_name": sanitize_text(getattr(self, "wss_name", "unknown")),
                    "wss_url": sanitize_url(getattr(self, "wss_url", None)),
                    "exchange_name": sanitize_text(getattr(params, "exchange_name", "unknown")),
                    "asset_type": sanitize_text(getattr(self, "asset_type", "unknown")),
                    "stream_role": sanitize_text(getattr(self, "_stream_role", "unknown")),
                    "connection_generation": getattr(self, "_connection_generation", 0),
                },
            )

    def _safe_failure(self, error: Any) -> str:
        return sanitize_text(error, sensitive_values=self._credential_values())

    def _safe_traceback(self) -> str:
        return sanitize_text(traceback.format_exc(), sensitive_values=self._credential_values())

    def _credential_values(self) -> tuple[Any, ...]:
        values = []
        params = getattr(self, "_params", None)
        for name in (
            "public_key",
            "private_key",
            "api_key",
            "api_secret",
            "secret_key",
            "passphrase",
            "listen_key",
        ):
            for owner in (self, params):
                value = getattr(owner, name, None) if owner is not None else None
                if value not in (None, ""):
                    values.append(value)
        return tuple(dict.fromkeys(str(value) for value in values))

    def _log_callback_failure(self, error: Any) -> None:
        self.wss_logger.warning(
            f"{sanitize_text(self.wss_name)},{sanitize_url(self.wss_url)},"
            f"{self._safe_failure(error)},{self._safe_traceback()}"
        )

    def _backoff_delay(self):
        """（），."""
        jitter = random.uniform(0, self._current_delay * 0.1)
        delay = min(self._current_delay + jitter, self._reconnect_max_delay)
        self._current_delay = min(self._current_delay * 2, self._reconnect_max_delay)
        return delay

    def _reset_backoff(self):
        """."""
        self._reconnect_attempt = 0
        self._current_delay = self._reconnect_base_delay

    def on_open(self, _ws):
        """on_open method"""
        self._connection_generation += 1
        opened_at = time.monotonic()
        with self._subscription_lock:
            self._last_message_at = opened_at
            self._awaiting_ready = True
            self._idle_close_requested = False
            self._readiness_generation = self._connection_generation
            self._readiness_ws = _ws
            self._readiness_deadline = (
                opened_at + self.readiness_timeout if self.readiness_timeout > 0 else None
            )
        try:
            ready = self.open_rsp()
        except Exception as e:
            self._log_callback_failure(e)
            self._running_flag = False
            with self._subscription_lock:
                self._awaiting_ready = False
                self._readiness_deadline = None
            payload = {"error": self._safe_failure(e)}
            if isinstance(e, WebSocketSubscriptionError):
                payload["fatal"] = True
                if e.code is not None:
                    payload["code"] = e.code
                self._stop_event.set()
            self._emit_event("ws.subscription_error", **payload)
            ws = self.ws or _ws
            if ws is not None:
                try:
                    ws.close()
                except Exception as close_error:
                    self._log_callback_failure(close_error)
            return
        if ready is False:
            self._emit_event(
                "ws.subscription_pending",
                pending=self._pending_subscription_acks,
            )
            return
        self._mark_ready()

    def open_rsp(self):
        """open_rsp method"""

    def on_message(self, _ws, message):
        """on_message method"""
        self._last_message_at = time.monotonic()
        try:
            self.message_rsp(message)
        except Exception as e:
            self._log_callback_failure(e)
            subscription_error = isinstance(e, WebSocketSubscriptionError)
            event_type = "ws.subscription_error" if subscription_error else "ws.message_error"
            payload = {"error": self._safe_failure(e)}
            if subscription_error:
                payload["fatal"] = True
                if e.code is not None:
                    payload["code"] = e.code
                self._stop_event.set()
            self._emit_event(event_type, **payload)
            self._running_flag = False
            with self._subscription_lock:
                self._awaiting_ready = False
                self._readiness_deadline = None
            ws = self.ws or _ws
            if ws is not None:
                try:
                    ws.close()
                except Exception as close_error:
                    self._log_callback_failure(close_error)

    # noinspection PyMethodMayBeStatic
    def message_rsp(self, message):
        """message_rsp method"""
        self.wss_logger.debug(message)

    def on_error(self, _ws, error):
        """on_error method"""
        safe_error = self._safe_failure(error)
        try:
            self.error_rsp(f"error: {safe_error}")
        except Exception as e:
            self._log_callback_failure(e)
        self._emit_event("ws.error", error=safe_error)

    # noinspection PyMethodMayBeStatic
    def error_rsp(self, error):
        """error_rsp method"""
        self.wss_logger.warning(
            f"name: {sanitize_text(self.wss_name)}, url: {sanitize_url(self.wss_url)}, "
            f"error: {self._safe_failure(error)}"
        )

    def on_close(self, _ws, _close_status_code, _close_msg):
        """on_close method"""
        self._running_flag = False
        with self._subscription_lock:
            self._awaiting_ready = False
            self._tracking_subscription_batch = False
            self._pending_subscription_acks = 0
            self._subscription_batch_send_count = 0
            self._idle_close_requested = False
            self._readiness_deadline = None
        self._last_message_at = None
        self._emit_event("ws.disconnected", code=_close_status_code, msg=_close_msg)
        try:
            self.close_rsp(self._restart_flag)
        except Exception as e:
            self._log_callback_failure(e)

    def on_ping(self, _ws, ping):
        """on_ping method"""
        self.wss_logger.info(
            f"===== {time.strftime('%Y-%m-%d %H:%M:%S')} Websocket ping {ping} ====="
        )

    def on_pong(self, _ws, pong):
        """on_pong method"""
        self.wss_logger.info(
            f"===== {time.strftime('%Y-%m-%d %H:%M:%S')} Websocket pong {pong} ====="
        )

    # noinspection PyMethodMayBeStatic
    def close_rsp(self, _is_restart):
        """close_rsp method"""
        self._restart_flag = False
        self.wss_logger.info(
            f"===== {time.strftime('%Y-%m-%d %H:%M:%S')} Websocket Disconnected ====="
        )

    def _clear_proxy_env(self) -> None:
        for key in _PROXY_ENV_KEYS:
            os.environ.pop(key, None)

    def _create_websocket_app(self) -> websocket.WebSocketApp:
        if self.wss_url is None:
            raise ValueError("wss_url is required for WebSocket connection")
        return websocket.WebSocketApp(
            self.wss_url,
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
            on_ping=self.on_ping,
            on_pong=self.on_pong,
        )

    def run(self):
        """Run the socket, reconnecting only while the stream remains active."""
        websocket.setdefaulttimeout(self.ping_timeout)
        if self.wss_url is None:
            raise ValueError("wss_url is required for WebSocket connection")
        stop_event = self._stop_event
        while not stop_event.is_set():
            if (
                self._max_reconnect_attempts > 0
                and self._reconnect_attempt >= self._max_reconnect_attempts
            ):
                self.wss_logger.warning(
                    f"{self.wss_name}: max reconnect attempts ({self._max_reconnect_attempts}) reached, giving up"
                )
                self._emit_event("ws.max_reconnect", attempts=self._reconnect_attempt)
                break

            try:
                ws = self._create_websocket_app()
                self.ws = ws
                run_kwargs = {
                    "ping_interval": self.ping_interval,
                    "ping_timeout": self.ping_timeout,
                    "sslopt": self.sslopt,
                }
                if self.http_proxy_host:
                    run_kwargs["http_proxy_host"] = self.http_proxy_host
                    run_kwargs["proxy_type"] = "http"
                    if self.http_proxy_port:
                        run_kwargs["http_proxy_port"] = self.http_proxy_port
                elif self.http_proxy_host == "":
                    self._clear_proxy_env()
                    run_kwargs["http_no_proxy"] = ["*"]
                if not stop_event.is_set():
                    ws.run_forever(**run_kwargs)
                self.wss_logger.info("----------wss running----------------")
            except Exception as e:
                self._log_callback_failure(e)

            if stop_event.is_set():
                break
            self._reconnect_attempt += 1
            delay = self._backoff_delay()
            self._emit_event("ws.reconnecting", attempt=self._reconnect_attempt, delay=delay)
            self.wss_logger.info(
                f"{self.wss_name}: reconnecting in {delay:.1f}s (attempt {self._reconnect_attempt})"
            )
            stop_event.wait(delay)
        self._running_flag = False
        stop_event.set()

    def start(self, connect_timeout=30):
        """start method"""
        if self._params is None:
            raise ValueError("exchange_data (params) is required to start WebSocket")
        if isinstance(connect_timeout, bool):
            raise ValueError("connect_timeout must be a finite nonnegative number")
        connect_timeout = float(connect_timeout)
        if not math.isfinite(connect_timeout) or connect_timeout < 0:
            raise ValueError("connect_timeout must be a finite nonnegative number")
        worker_running = self.process.is_alive()
        if worker_running:
            if self._stop_event.is_set():
                raise RuntimeError("Previous WebSocket worker has not stopped")
        else:
            for old_worker in (
                self._restart_process,
                self._watchdog_process,
                self._readiness_watchdog_process,
            ):
                if old_worker is not None and old_worker.is_alive():
                    old_worker.join(timeout=self._shutdown_timeout)
                    if old_worker.is_alive():
                        raise RuntimeError("Previous WebSocket helper worker has not stopped")
            self._stop_event = threading.Event()
            self._restart_flag = True
            self._running_flag = False
            self._reset_backoff()
            self.process = threading.Thread(target=self.run, daemon=True)
            self.process.start()
            if self.message_idle_timeout > 0:
                self._watchdog_process = threading.Thread(
                    target=self._message_idle_watchdog,
                    daemon=True,
                )
                self._watchdog_process.start()
            if self.readiness_timeout > 0:
                self._readiness_watchdog_process = threading.Thread(
                    target=self._readiness_watchdog,
                    daemon=True,
                )
                self._readiness_watchdog_process.start()
        ready_deadline = time.monotonic() + connect_timeout
        while not self._running_flag and not self._stop_event.is_set():
            self.wss_logger.info(
                f"===== {time.strftime('%Y-%m-%d %H:%M:%S')} "
                f"Wait {self._params.exchange_name} Websocket Connecting... ====="
            )
            remaining = ready_deadline - time.monotonic()
            if remaining <= 0:
                self.wss_logger.warning(
                    f"===== {time.strftime('%Y-%m-%d %H:%M:%S')} "
                    f"{self._params.exchange_name} Websocket Connect Timeout ({connect_timeout}s)! ====="
                )
                self.stop()
                raise TimeoutError(
                    f"{self._params.exchange_name} WebSocket was not ready within connect_timeout"
                )
            self._stop_event.wait(min(0.5, remaining))
        if not self._running_flag:
            raise ConnectionError(f"{self._params.exchange_name} WebSocket stopped before ready")
        if (
            self.restart_gap
            and not self._stop_event.is_set()
            and (self._restart_process is None or not self._restart_process.is_alive())
        ):
            self._restart_process = threading.Thread(target=self.restart_timer, daemon=True)
            self._restart_process.start()

    def restart(self):
        # ws, ws
        """restart method"""
        self.wss_logger.info(f"===== {time.strftime('%Y-%m-%d %H:%M:')}, ws")
        self.stop()
        # ws
        self.start()

    def stop(self):
        """Close the socket and stop reconnect/timer workers within a bounded wait."""
        self._restart_flag = False
        self._running_flag = False
        self._stop_event.set()
        ws = self.ws
        if ws is not None:
            ws.close()
        current = threading.current_thread()
        deadline = time.monotonic() + self._shutdown_timeout
        for worker in (
            self.process,
            self._restart_process,
            self._watchdog_process,
            self._readiness_watchdog_process,
        ):
            if worker is not None and worker is not current and worker.is_alive():
                worker.join(timeout=max(0.0, deadline - time.monotonic()))
                if worker.is_alive():
                    raise RuntimeError("WebSocket worker did not stop within shutdown_timeout")
            self.ws = None

    def _readiness_watchdog(self):
        """Reconnect a transport that never completes login or subscription setup."""
        timeout = self.readiness_timeout
        if timeout <= 0:
            return
        interval = min(0.5, max(0.01, timeout / 4.0))
        stop_event = self._stop_event
        while not stop_event.wait(interval):
            with self._subscription_lock:
                deadline = self._readiness_deadline
                expected_ws = self._readiness_ws
                generation = self._readiness_generation
                awaiting_ready = self._awaiting_ready
            if not awaiting_ready or deadline is None or expected_ws is None:
                continue
            if time.monotonic() <= deadline:
                continue
            with self._subscription_lock:
                if (
                    not self._awaiting_ready
                    or self._readiness_deadline != deadline
                    or self._readiness_generation != generation
                    or self._readiness_ws is not expected_ws
                    or self.ws is not expected_ws
                ):
                    continue
                self._awaiting_ready = False
                self._running_flag = False
                self._readiness_deadline = None
            self._emit_event(
                "ws.readiness_timeout",
                timed_out_generation=generation,
                timeout_seconds=timeout,
            )
            try:
                expected_ws.close()
            except Exception as error:
                self._log_callback_failure(error)

    def _message_idle_watchdog(self):
        """Reconnect an open socket whose application messages have gone silent."""
        timeout = self.message_idle_timeout
        if timeout <= 0:
            return
        interval = min(1.0, max(0.05, timeout / 4.0))
        stop_event = self._stop_event
        while not stop_event.wait(interval):
            with self._subscription_lock:
                last_message_at = self._last_message_at
                expected_ws = self.ws
                generation = self._connection_generation
                active = self._running_flag or self._awaiting_ready
            if not active or last_message_at is None or expected_ws is None:
                continue
            idle_seconds = time.monotonic() - last_message_at
            if idle_seconds <= timeout:
                continue
            # Latch the close request before close so a slow callback cannot
            # trigger repeated closes. run_forever owns the reconnect.
            with self._subscription_lock:
                if (
                    self._idle_close_requested
                    or self.ws is not expected_ws
                    or self._connection_generation != generation
                    or self._last_message_at != last_message_at
                ):
                    continue
                self._idle_close_requested = True
                self._running_flag = False
                self._awaiting_ready = False
                self._readiness_deadline = None
            self._emit_event(
                "ws.message_idle",
                idle_seconds=idle_seconds,
                timeout_seconds=timeout,
                timed_out_generation=generation,
            )
            try:
                expected_ws.close()
            except Exception as error:
                self._log_callback_failure(error)

    def restart_timer(self):
        """Periodically reconnect the socket, exiting promptly when stopped."""
        time_gap = self.restart_gap
        stop_event = self._stop_event
        while not stop_event.wait(time_gap):
            try:
                self.wss_logger.info("restartTimer Working....")
                ws = self.ws
                if ws is not None:
                    ws.close()
            except Exception as e:
                self._log_callback_failure(e)


if __name__ == "__main__":

    def restart(task: list, timeout1=5000, _timeout2=8000):
        while True:
            time.sleep(int(timeout1 / 1000) - 1)
            try:
                for exc in task:
                    # print(exc.wss_name, "begin_to_run")
                    exc.start()
            except Exception as e:
                get_logger("my_websocket_app").debug(
                    "WebSocket restart task error: %s", sanitize_text(e)
                )
