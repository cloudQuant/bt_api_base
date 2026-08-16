"""
 —  Feed 

: BaseDataStream  ConnectionState ， Mixin。
 Mixin  Feed（REST ）。
HTTP  connect/disconnect  no-op（）。
"""

from __future__ import annotations

import threading
from enum import Enum, unique


@unique
class FeedConnectionState(Enum):
    """Feed 

     base_stream.py  ConnectionState ，
     Feed  DataStream 。
    """

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    AUTHENTICATED = "authenticated"
    ERROR = "error"


class ConnectionMixin:
    """ —  Feed 

    HTTP （CEX/CEX DEX）：connect/disconnect  no-op。
     HTTP （CTP/IB/QMT）：。
    """

    def __init_connection__(self) -> None:
        """ —  Feed.__init__ """
        self._conn_state = FeedConnectionState.DISCONNECTED
        self._conn_lock = threading.Lock()

    @property
    def connection_state(self) -> FeedConnectionState:
        """connection_state method"""
        lock = getattr(self, "_conn_lock", None)
        if lock:
            with lock:
                return self._conn_state
        return getattr(self, "_conn_state", FeedConnectionState.DISCONNECTED)

    def _set_connection_state(self, new_state: FeedConnectionState) -> None:
        lock = getattr(self, "_conn_lock", None)
        if lock:
            with lock:
                self._conn_state = new_state
        else:
            self._conn_state = new_state

    def connect(self) -> None:
        """ — HTTP  no-op，CTP/IB/QMT """
        self._set_connection_state(FeedConnectionState.CONNECTED)

    def disconnect(self) -> None:
        """ — HTTP  no-op，CTP/IB/QMT """
        self._set_connection_state(FeedConnectionState.DISCONNECTED)

    def is_connected(self) -> bool:
        """"""
        return self.connection_state in (
            FeedConnectionState.CONNECTED,
            FeedConnectionState.AUTHENTICATED,
        )
