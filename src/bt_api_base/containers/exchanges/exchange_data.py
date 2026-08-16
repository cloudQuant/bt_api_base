"""ExchangeData."""

from __future__ import annotations

from typing import Any

from bt_api_base._compat import Never


class ExchangeData:
    """Class ExchangeData"""
    def __init__(self, config: dict | None = None) -> None:
        """__init__ method"""
        self.rate_limit_type = ""  # 
        self.interval = ""  # 
        self.interval_num = 0  # 
        self.limit = 0  # 
        self.server_time = 0.0  # 
        self.local_update_time = 0.0  # 
        self.timezone = ""  # 
        self.rate_limits: list[Any] = []  # 
        self.exchange_filters: list[Any] = []  # 
        self.symbols: list[Any] = []  # 
        self.exchange_name = ""  # 
        self.rest_url = ""
        self.acct_wss_url = ""
        self.wss_url = ""
        self.um_rest_url = ""
        self.um_wss_Url = ""
        self.rest_paths: dict[str, Any] = {}  # rest paths
        self.wss_paths: dict[str, Any] = {}  # wss paths
        self.kline_periods: dict[str, str] = {}  # kline periods
        self.reverse_kline_periods: dict[str, str] = {}
        self.status_dict: dict[str, Any] = {}  # 
        self.legal_currency: list[str] = []  # 
        self.api_key = ""  # API key for authentication
        self.api_secret = ""  # API secret for signing
        self.passphrase = ""  # Passphrase (used by some exchanges)

    def get_wss_url(self) -> Any:
        """get_wss_url method"""
        return self.wss_url

    def raise_path_error(self, *args) -> Never:
        """path
        Args: args: .
        """
        raise NotImplementedError(f"wbfAPI {args} ")

    def raise_timeout(self, timeout, *args) -> Never:
        """Raise .

        Args: timeout (int): ，s
            *args: Description

        """
        raise TimeoutError(f"{args} rest{timeout}s")

    def raise400(self, *args) -> Never:
        """Http 400
        Args: *args: Description.
        """
        raise RuntimeError(f"{args} rest<400>")

    def raise_proxy_error(self, *args) -> Never:
        """
        Args: *args: Description.
        """
        raise ConnectionError(f"{args} ")

    @staticmethod
    def update_info(exchange_info):
        """update_info method"""
        result = ExchangeData()
        for key in exchange_info:
            setattr(result, key, exchange_info[key])
        return result

    def to_dict(self):
        """to_dict method"""
        content = {
            key: getattr(self, key)
            for key in dir(self)
            if (
                (not key.startswith("__"))
                & (not key.startswith("update"))
                & (not key.startswith("to_dict"))
            )
        }
        return content
