"""Module-level docstring."""
from __future__ import annotations


class PluginError(Exception):
    """Class PluginError"""
    pass


class PluginNotFoundError(PluginError):
    """Class PluginNotFoundError"""
    pass


class PluginVersionMismatchError(PluginError):
    """Class PluginVersionMismatchError"""
    pass


class PluginRegistrationError(PluginError):
    """Class PluginRegistrationError"""
    pass
