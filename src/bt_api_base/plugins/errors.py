"""Module-level docstring."""

from __future__ import annotations


class PluginError(Exception):
    """Class PluginError"""



class PluginNotFoundError(PluginError):
    """Class PluginNotFoundError"""



class PluginVersionMismatchError(PluginError):
    """Class PluginVersionMismatchError"""



class PluginRegistrationError(PluginError):
    """Class PluginRegistrationError"""



class PluginOptionalDependencyError(PluginRegistrationError):
    pass
