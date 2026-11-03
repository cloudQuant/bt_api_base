"""Auto-init mixin for container classes.

Containers parse their raw provider payload lazily in ``init_data()``. Any
public ``get_*`` accessor (except ``get_event``, ``get_event_type`` and
``get_data``) triggers that parse once before returning::

    class AccountData(AutoInitMixin):
        ...

    account.get_balance()  # runs init_data() on first access

Publication contract (iteration 60, decisions D60-12/D60-13):

* Initialization is thread-safe. Two threads that first access the same
  uninitialized container never observe a half-initialized object: the first
  thread runs ``init_data()`` under a lock and the other waits for it.
  ``init_data()`` may call ``get_*`` on ``self`` re-entrantly.
* ``freeze()`` completes initialization and publishes the container. From
  then on it is enforced read-only (acceptance report 2026-11-03 F1):

  - setting or deleting any attribute raises ``FrozenContainerError``;
  - the instance dictionary is detached from any pre-publication aliases and
    exposed read-only; built-in mappings, sequences and sets are replaced by a
    read-only copy (``MappingProxyType`` over a private dict, ``tuple``,
    ``frozenset``), recursively, so no consumer can change what another
    consumer sees through those values; byte arrays become bytes and unknown
    public payload objects, cyclic and excessively deep values are rejected;
  - the one derived cache a reader may create, ``all_data``/``_all_data``
    memoized by ``get_all_data()``, can be set once (from ``None``) and is
    stored read-only; ``get_all_data()`` then returns a new plain ``dict``
    copy on every call, so its result stays JSON-serializable and private.

  Enforcement costs nothing while a container is built: a ``__setattr__`` hook
  on every container class makes construction about 4.5x slower (measured
  3.8 -> 17.2 us for a CTP ticker), so ``freeze()`` instead moves the instance
  to a cached read-only subclass of its own class. ``isinstance`` checks,
  ``type(x).__name__`` and pickling keep working; ``type(x) is Cls`` does not
  hold for a frozen container. Exact-type checks use
  :func:`container_class` instead: it maps a frozen instance back to its
  class only through this module's own variant registry, so a hand-made
  subclass cannot pass as the original.

This contract is for ordinary in-process consumers, not a Python security
sandbox. Opaque private provider identity/receipt references are retained by
identity; they do not acquire a recursive immutability guarantee.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Any

__all__ = ["AutoInitMixin", "FrozenContainerError", "container_class", "container_fingerprint"]


class FrozenContainerError(AttributeError):
    """A published (frozen) container was written to."""

# One re-entrant lock serializes first-time initialization. It is only taken
# while a container is still uninitialized, so steady-state reads never touch
# it; contention is limited to concurrent first accesses.
_INIT_LOCK = threading.RLock()
_SKIP_AUTO_INIT = frozenset({"get_event", "get_event_type", "get_data"})
_object_getattribute = object.__getattribute__


class AutoInitMixin:
    """Run ``init_data()`` once before the first ``get_*`` accessor."""

    def _ensure_init(self) -> AutoInitMixin:
        """Run ``init_data()`` once; safe for concurrent first access."""
        state = _object_getattribute(self, "__dict__")
        if state.get("_initialized", False):
            return self
        with _INIT_LOCK:
            if state.get("_initialized", False) or state.get("_initializing", False):
                # Already done by another thread, or a re-entrant get_* call
                # made by init_data() on this thread.
                return self
            state["_initializing"] = True
            try:
                self.init_data()
            finally:
                state["_initializing"] = False
            # Mark success only after init_data() completed; a failure leaves
            # the container uninitialized so a later access retries.
            state["_initialized"] = True
        return self

    def __getattribute__(self, name: str) -> Any:
        # Fast path: skip the super() proxy and only consult the instance
        # dict for public accessors.
        if name[:4] == "get_" and name not in _SKIP_AUTO_INIT:
            state = _object_getattribute(self, "__dict__")
            if not state.get("_initialized", False):
                attr = _object_getattribute(self, name)
                if callable(attr):
                    _object_getattribute(self, "_ensure_init")()
                return attr
        return _object_getattribute(self, name)

    def freeze(self) -> AutoInitMixin:
        """Complete initialization and publish the container read-only."""
        self._ensure_init()
        cls = type(self)
        if _FROZEN_VARIANTS.get(cls.__dict__.get("_frozen_variant_of")) is cls:
            return self
        with _INIT_LOCK:
            if type(self) is not cls:  # frozen concurrently
                return self
            state = _instance_state(self)
            # Replace, rather than mutate, the original dictionary.  Producer
            # code may have retained a reference to the pre-publication dict.
            # Build the complete snapshot first so an error cannot publish a
            # partially frozen object.
            frozen_state = {
                key: _read_only(value, allow_opaque=key.startswith("_"))
                for key, value in state.items()
            }
            frozen_state["_frozen"] = True
            variant = _frozen_variant(cls)
            _INSTANCE_DICT.__set__(self, frozen_state)
            try:
                object.__setattr__(self, "__class__", variant)
            except BaseException:
                _INSTANCE_DICT.__set__(self, state)
                raise
        return self

    def is_frozen(self) -> bool:
        """Return whether ``freeze()`` has published this container."""
        return bool(_object_getattribute(self, "__dict__").get("_frozen", False))


_FROZEN_VARIANTS: dict[type, type] = {}
_INSTANCE_DICT = AutoInitMixin.__dict__["__dict__"]
_CACHE_CONTEXT = threading.local()
_IMMUTABLE_VALUES = frozenset(
    {type(None), bool, int, float, complex, str, bytes, Decimal, date, datetime, time, timedelta}
)


def _instance_state(instance: Any) -> dict:
    # Access the underlying slot directly: the frozen subclass exposes only a
    # mapping proxy through the public ``__dict__`` attribute.
    return _INSTANCE_DICT.__get__(instance)


def _read_only(value: Any, depth: int = 0, *, allow_opaque: bool = False) -> Any:
    kind = type(value)
    if depth > 32:
        raise FrozenContainerError("container nesting exceeds frozen depth limit")
    if isinstance(value, Mapping):
        try:
            frozen = {
                _read_only(key, depth + 1): _read_only(item, depth + 1)
                for key, item in value.items()
            }
        except TypeError:
            raise FrozenContainerError("container mapping contains an unsupported key") from None
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_read_only(item, depth + 1) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_read_only(item, depth + 1) for item in value)
    if isinstance(value, (bytearray, memoryview)):
        return bytes(value)
    if kind in _IMMUTABLE_VALUES or isinstance(value, Enum) or allow_opaque:
        # Enum members are process-wide singletons with read-only values.
        # Private provider identity/receipt objects may carry intentional
        # object identity.  They are not claimed to be recursively immutable.
        return value
    raise FrozenContainerError("container contains an unsupported mutable value")


_DERIVED_CACHES = frozenset({"all_data", "_all_data"})


def _deny_write(self: Any, name: str, value: Any = None) -> None:
    state = _instance_state(self)
    if (
        name in _DERIVED_CACHES
        and getattr(_CACHE_CONTEXT, "container", None) is self
        and state.get(name, None) is None
        and value is not None
    ):
        state[name] = _read_only(value)  # memoized once by get_all_data()
        return
    raise FrozenContainerError(f"published container is read-only: {name}")


def _deny_delete(self: Any, name: str) -> None:
    raise FrozenContainerError(f"published container is read-only: {name}")


def _thawed(value: Any) -> Any:
    """A new plain copy for a caller: dicts and lists, never shared."""
    kind = type(value)
    if kind is MappingProxyType or kind is dict:
        return {key: _thawed(item) for key, item in value.items()}
    if kind is tuple or kind is list:
        return [_thawed(item) for item in value]
    if kind is frozenset:
        return set(value)
    return value


def _plain(value: Any) -> Any:
    """Picklable copy of a read-only value (read-only again on restore)."""
    kind = type(value)
    if kind is MappingProxyType:
        return {key: _plain(item) for key, item in value.items()}
    if kind is tuple:
        return tuple(_plain(item) for item in value)
    return value


def _restore_frozen(cls: type, state: dict) -> Any:
    instance = cls.__new__(cls)
    _instance_state(instance).update(
        {key: _read_only(value, allow_opaque=key.startswith("_")) for key, value in state.items()}
    )
    object.__setattr__(instance, "__class__", _frozen_variant(cls))
    return instance


def _reduce_frozen(self: Any, protocol: int = 2) -> tuple:
    base = type(self).__dict__["_frozen_variant_of"]
    state = _instance_state(self)
    return _restore_frozen, (base, {key: _plain(value) for key, value in state.items()})


def _frozen_variant(cls: type) -> type:
    variant = _FROZEN_VARIANTS.get(cls)
    if variant is None:
        namespace = {
            "__module__": cls.__module__,
            "__qualname__": cls.__qualname__,
            "__setattr__": _deny_write,
            "__delattr__": _deny_delete,
            "__reduce_ex__": _reduce_frozen,
            "__dict__": property(lambda self: MappingProxyType(_instance_state(self))),
            "_frozen_variant_of": cls,
        }
        original = getattr(cls, "get_all_data", None)
        if callable(original):

            def get_all_data(self, *args, _original=original, **kwargs):
                previous = getattr(_CACHE_CONTEXT, "container", None)
                _CACHE_CONTEXT.container = self
                try:
                    return _thawed(_original(self, *args, **kwargs))
                finally:
                    _CACHE_CONTEXT.container = previous

            get_all_data.__doc__ = original.__doc__
            namespace["get_all_data"] = get_all_data
        variant = type(cls.__name__, (cls,), namespace)
        _FROZEN_VARIANTS[cls] = variant
    return variant


def container_class(container: Any) -> type:
    """The exact class of ``container``, the same before and after ``freeze()``."""
    kind = type(container)
    base = kind.__dict__.get("_frozen_variant_of")
    if base is not None and _FROZEN_VARIANTS.get(base) is kind:
        return base
    return kind


def container_fingerprint(container: Any) -> tuple[tuple[str, str], ...]:
    """Return a comparable snapshot of a container's instance state.

    Used by tests to prove that consumers did not mutate a published
    container. Values are compared through ``repr`` so nested lists and dicts
    are captured by content.
    """
    state = _object_getattribute(container, "__dict__")
    return tuple(sorted((key, repr(value)) for key, value in state.items()))
