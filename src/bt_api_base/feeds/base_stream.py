"""
 —  WebSocket / CTP SPI / IB TWS 
， connect/disconnect/subscribe_topics/_run_loop 
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

from bt_api_base.logging_factory import get_logger


class ConnectionState(Enum):
    """"""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    AUTHENTICATED = "authenticated"
    ERROR = "error"


class BaseDataStream(ABC):
    """

    :
      - connect(): 
      - disconnect(): 
      - subscribe_topics(topics): 
      - _run_loop(): （）
    """

    def __init__(self, data_queue: Any = None, **kwargs: Any) -> None:
        """__init__ method"""
        self.data_queue = data_queue
        self.stream_name = kwargs.get("stream_name", self.__class__.__name__)
        self._running = False
        self._state = ConnectionState.DISCONNECTED
        self._thread: threading.Thread | None = None
        self.logger = get_logger("unknown")

    @property
    def state(self) -> ConnectionState:
        """state method"""
        return self._state

    @state.setter
    def state(self, new_state: ConnectionState) -> None:
        """state method"""
        old_state = self._state
        self._state = new_state
        self.on_state_change(old_state, new_state)

    def on_state_change(self, old_state: ConnectionState, new_state: ConnectionState) -> None:
        """，"""
        self.logger.info(f"{self.stream_name} state: {old_state.value} -> {new_state.value}")

    @abstractmethod
    def connect(self) -> None:
        """"""
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """"""
        ...

    @abstractmethod
    def subscribe_topics(self, topics: list[dict[str, Any]]) -> None:
        """
        :param topics: list of topic dicts, e.g. [{"topic": "kline", "symbol": "BTC-USDT", "period": "1m"}]
        """
        ...

    @abstractmethod
    def _run_loop(self) -> None:
        """， daemon """
        ...

    def start(self) -> None:
        """"""
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """"""
        self._running = False
        self.disconnect()

    def is_running(self) -> bool:
        """is_running method"""
        return self._running

    def push_data(self, data: Any) -> None:
        """"""
        if self.data_queue is not None:
            self.data_queue.put(data)
        else:
            self.logger.warning(f"{self.stream_name}: data_queue is None, data dropped")

    def wait_connected(self, timeout: float = 30, interval: float = 0.5) -> bool:
        """
        :param timeout: 
        :param interval: 
        :return: True if connected, False if timeout
        """
        import time

        elapsed = 0.0
        while elapsed < timeout:
            if self._state in (ConnectionState.CONNECTED, ConnectionState.AUTHENTICATED):
                return True
            time.sleep(interval)
            elapsed += interval
        self.logger.warning(f"{self.stream_name}: wait_connected timeout after {timeout}s")
        return False
