"""Module-level docstring."""
from __future__ import annotations

from typing import Any


class TimerData:
    """Class TimerData"""
    def __init__(self, data: Any) -> None:
        """__init__ method"""
        self.event_type = "Timer_update"
        self.data = data

    def get_data(self) -> Any:
        """get_data method"""
        return self.data

    def __str__(self) -> str:
        return str(self.data)
