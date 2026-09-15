"""Stopping a demo feed must stop reconnecting, not only close its socket."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from bt_api_base.feeds.my_websocket_app import MyWebsocketApp, WebSocketSubscriptionError


class _EventBus:
    def __init__(self):
        self.events = []

    def emit(self, event_type, payload):
        self.events.append((event_type, payload))


def _app(**kwargs):
    return MyWebsocketApp(
        wss_url="wss://example.invalid/ws",
        exchange_data=SimpleNamespace(exchange_name="TEST"),
        shutdown_timeout=1.0,
        **kwargs,
    )


def test_stop_interrupts_reconnect_backoff_without_another_connection():
    app = _app(reconnect_base_delay=60.0)
    backing_off = threading.Event()
    socket = SimpleNamespace(run_forever=Mock(), close=Mock())
    app._create_websocket_app = lambda: socket
    app._backoff_delay = lambda: backing_off.set() or 60.0
    app.process = threading.Thread(target=app.run, daemon=True)
    app.process.start()
    assert backing_off.wait(1.0)

    app.stop()

    assert not app.process.is_alive()
    socket.run_forever.assert_called_once()
    socket.close.assert_called_once()
    assert app.ws is None
    assert not app._running_flag


def test_stop_closes_active_socket_and_does_not_reconnect():
    app = _app()
    connected = threading.Event()
    closed = threading.Event()

    def run_forever(**kwargs):
        connected.set()
        assert closed.wait(2.0)

    socket = SimpleNamespace(run_forever=Mock(side_effect=run_forever), close=closed.set)
    app._create_websocket_app = lambda: socket
    app.process = threading.Thread(target=app.run, daemon=True)
    app.process.start()
    assert connected.wait(1.0)

    app.stop()

    assert not app.process.is_alive()
    socket.run_forever.assert_called_once()


def test_stop_interrupts_restart_timer_and_is_idempotent():
    app = _app(restart_gap=60.0)
    socket = SimpleNamespace(close=Mock())
    app.ws = socket
    app._restart_process = threading.Thread(target=app.restart_timer, daemon=True)
    app._restart_process.start()

    app.stop()
    app.stop()

    assert not app._restart_process.is_alive()
    socket.close.assert_called_once()


def test_start_validates_configuration_before_spawning_worker():
    app = MyWebsocketApp(wss_url="wss://example.invalid/ws")

    with pytest.raises(ValueError, match="exchange_data"):
        app.start(connect_timeout=0)

    assert not app.process.is_alive()


def test_stop_from_worker_callback_does_not_join_itself():
    app = _app()
    socket = SimpleNamespace(close=Mock())
    app.ws = socket
    failures = []

    def callback():
        try:
            app.stop()
        except Exception as exc:
            failures.append(exc)

    app.process = threading.Thread(target=callback, daemon=True)
    app.process.start()
    app.process.join(1.0)

    assert not app.process.is_alive()
    assert failures == []
    socket.close.assert_called_once()


def test_open_subscription_failure_closes_socket_and_never_reports_connected():
    event_bus = _EventBus()
    app = _app(event_bus=event_bus)
    socket = SimpleNamespace(close=Mock())
    app.ws = socket
    app.open_rsp = Mock(side_effect=RuntimeError("subscription rejected"))

    app.on_open(socket)

    assert not app._running_flag
    socket.close.assert_called_once()
    assert [event_type for event_type, _ in event_bus.events] == ["ws.subscription_error"]


def test_fatal_subscription_failure_stops_reconnect_loop():
    event_bus = _EventBus()
    app = _app(event_bus=event_bus)
    socket = SimpleNamespace(close=Mock())
    app.ws = socket
    app.open_rsp = Mock(
        side_effect=WebSocketSubscriptionError("subscription rejected", code="fixture")
    )

    app.on_open(socket)

    assert app._stop_event.is_set()
    socket.close.assert_called_once_with()
    event, payload = event_bus.events[-1]
    assert event == "ws.subscription_error"
    assert payload["fatal"] is True
    assert payload["code"] == "fixture"


def test_connection_is_not_ready_until_last_subscription_acknowledgement():
    event_bus = _EventBus()
    app = _app(event_bus=event_bus)
    socket = SimpleNamespace(close=Mock())
    app.ws = socket

    def subscribe_pending():
        app._pending_subscription_acks = 1
        return False

    app.open_rsp = subscribe_pending
    app.on_open(socket)

    assert not app._running_flag
    assert app._awaiting_ready
    assert [event_type for event_type, _ in event_bus.events] == ["ws.subscription_pending"]

    app._subscription_acknowledged()

    assert app._running_flag
    assert not app._awaiting_ready
    assert [event_type for event_type, _ in event_bus.events] == [
        "ws.subscription_pending",
        "ws.connected",
    ]
    connected = event_bus.events[-1][1]
    assert connected["exchange_name"] == "TEST"
    assert connected["stream_role"] == "market"
    assert connected["connection_generation"] == 1


def test_immediate_subscription_ack_cannot_race_ahead_of_pending_count():
    app = _app()
    app._params.get_wss_path = Mock(return_value="subscribe")

    def send_and_ack(_request):
        app._subscription_acknowledged()

    app.ws = SimpleNamespace(send=send_and_ack)
    app._begin_subscription_batch()

    app.subscribe(topic="depth", symbol="BTC-USDT")

    assert app._end_subscription_batch() is True
    assert app._pending_subscription_acks == 0


def test_failed_subscription_send_rolls_back_pending_count():
    app = _app()
    app._params.get_wss_path = Mock(return_value="subscribe")
    app.ws = SimpleNamespace(send=Mock(side_effect=ConnectionError("send failed")))
    app._begin_subscription_batch()

    with pytest.raises(ConnectionError, match="send failed"):
        app.subscribe(topic="depth", symbol="BTC-USDT")

    assert app._end_subscription_batch() is True
    assert app._pending_subscription_acks == 0


def test_start_timeout_stops_worker_and_raises_instead_of_succeeding():
    app = _app()
    app.run = lambda: app._stop_event.wait()

    with pytest.raises(TimeoutError, match="not ready"):
        app.start(connect_timeout=0.01)

    assert app._stop_event.is_set()
    assert not app.process.is_alive()


def test_second_start_waits_for_existing_worker_to_become_ready():
    app = _app()
    app.process = threading.Thread(target=app._stop_event.wait, daemon=True)
    app.process.start()

    with pytest.raises(TimeoutError, match="not ready"):
        app.start(connect_timeout=0.01)

    assert app._stop_event.is_set()
    assert not app.process.is_alive()


def test_manual_start_after_reconnect_exhaustion_gets_a_fresh_attempt_budget():
    app = _app(max_reconnect_attempts=1, reconnect_base_delay=0.0)
    socket = SimpleNamespace(run_forever=Mock(), close=Mock())
    app._create_websocket_app = Mock(return_value=socket)
    app._backoff_delay = Mock(return_value=0.0)

    app.run()
    assert socket.run_forever.call_count == 1
    assert app._stop_event.is_set()

    with pytest.raises(ConnectionError, match="stopped before ready"):
        app.start(connect_timeout=1.0)

    assert socket.run_forever.call_count == 2


def test_message_idle_watchdog_closes_open_socket_for_run_loop_reconnect():
    event_bus = _EventBus()
    app = _app(event_bus=event_bus, message_idle_timeout=0.05)
    socket = SimpleNamespace(close=Mock())
    app.ws = socket
    app._running_flag = True
    app._last_message_at = time.monotonic() - 1.0
    worker = threading.Thread(target=app._message_idle_watchdog, daemon=True)
    worker.start()

    deadline = time.monotonic() + 1.0
    while not socket.close.called and time.monotonic() < deadline:
        time.sleep(0.01)
    app._stop_event.set()
    worker.join(1.0)

    socket.close.assert_called_once()
    assert not app._running_flag
    assert [event_type for event_type, _ in event_bus.events] == ["ws.message_idle"]


def test_pending_subscription_idle_watchdog_requests_close_only_once():
    event_bus = _EventBus()
    app = _app(event_bus=event_bus, message_idle_timeout=0.05)
    socket = SimpleNamespace(close=Mock())
    app.ws = socket
    app._awaiting_ready = True
    app._last_message_at = time.monotonic() - 1.0
    worker = threading.Thread(target=app._message_idle_watchdog, daemon=True)
    worker.start()

    time.sleep(0.2)
    app._stop_event.set()
    worker.join(1.0)

    socket.close.assert_called_once()
    assert [event_type for event_type, _ in event_bus.events] == ["ws.message_idle"]


def test_idle_timeout_never_closes_a_new_socket_installed_during_event_delivery():
    class SwapSocketBus(_EventBus):
        def emit(self, event_type, payload):
            super().emit(event_type, payload)
            if event_type == "ws.message_idle":
                app.ws = new_socket
                app._connection_generation = 2

    old_socket = SimpleNamespace(close=Mock())
    new_socket = SimpleNamespace(close=Mock())
    event_bus = SwapSocketBus()
    app = _app(event_bus=event_bus, message_idle_timeout=0.05)
    app.ws = old_socket
    app._connection_generation = 1
    app._running_flag = True
    app._last_message_at = time.monotonic() - 1.0
    worker = threading.Thread(target=app._message_idle_watchdog, daemon=True)
    worker.start()

    deadline = time.monotonic() + 1.0
    while not old_socket.close.called and time.monotonic() < deadline:
        time.sleep(0.01)
    app._stop_event.set()
    worker.join(1.0)

    old_socket.close.assert_called_once_with()
    new_socket.close.assert_not_called()
    assert event_bus.events[0][1]["timed_out_generation"] == 1


def test_readiness_watchdog_closes_only_the_generation_that_misses_its_ack():
    event_bus = _EventBus()
    app = _app(event_bus=event_bus, readiness_timeout=0.05)
    first_socket = SimpleNamespace(close=Mock())
    app.ws = first_socket
    app.open_rsp = Mock(return_value=True)
    app.on_open(first_socket)
    assert app._running_flag

    second_socket = SimpleNamespace(close=Mock())
    app.ws = second_socket
    app.open_rsp = Mock(return_value=False)
    app.on_open(second_socket)
    worker = threading.Thread(target=app._readiness_watchdog, daemon=True)
    worker.start()

    deadline = time.monotonic() + 1.0
    while not second_socket.close.called and time.monotonic() < deadline:
        time.sleep(0.01)
    app._stop_event.set()
    worker.join(1.0)

    first_socket.close.assert_not_called()
    second_socket.close.assert_called_once_with()
    event, payload = event_bus.events[-1]
    assert event == "ws.readiness_timeout"
    assert payload["timed_out_generation"] == 2
    assert payload["connection_generation"] == 2


def test_new_generation_replaces_old_readiness_deadline_without_stale_close(monkeypatch):
    app = _app(readiness_timeout=0.12)
    old_socket = SimpleNamespace(close=Mock())
    app.ws = old_socket
    app.open_rsp = Mock(return_value=False)
    clock = {"now": 0.0}
    monkeypatch.setattr("bt_api_base.feeds.my_websocket_app.time.monotonic", lambda: clock["now"])
    app.on_open(old_socket)

    new_socket = SimpleNamespace(close=Mock())

    class _StopAfterOneCheck:
        def __init__(self):
            self.calls = 0

        def wait(self, _interval):
            self.calls += 1
            if self.calls == 1:
                clock["now"] = 0.07
                app.ws = new_socket
                app.on_open(new_socket)
                clock["now"] = 0.13
                return False
            return True

    app._stop_event = _StopAfterOneCheck()
    app._readiness_watchdog()

    old_socket.close.assert_not_called()
    new_socket.close.assert_not_called()
    assert app._readiness_generation == 2
    assert app._readiness_deadline == 0.19


def test_on_ping_does_not_send_a_second_pong():
    app = _app()
    socket = SimpleNamespace(sock=SimpleNamespace(pong=Mock()))
    app.ws = socket

    app.on_ping(socket, b"ping")

    socket.sock.pong.assert_not_called()


@pytest.mark.parametrize("value", [True, -1, float("inf"), float("nan")])
def test_message_idle_timeout_must_be_finite_and_nonnegative(value):
    with pytest.raises(ValueError, match="message_idle_timeout"):
        _app(message_idle_timeout=value)


@pytest.mark.parametrize("value", [True, -1, float("inf"), float("nan")])
def test_readiness_timeout_must_be_finite_and_nonnegative(value):
    with pytest.raises(ValueError, match="readiness_timeout"):
        _app(readiness_timeout=value)
