from __future__ import annotations


class PluginError(Exception):
    pass


class PluginNotFoundError(PluginError):
    pass


class PluginVersionMismatchError(PluginError):
    pass


class PluginRegistrationError(PluginError):
    pass
