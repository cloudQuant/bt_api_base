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
* ``freeze()`` completes initialization and marks the container as published.
  After that point producers and consumers must treat it as read-only. The
  flag is not enforced on every attribute write because a ``__setattr__`` hook
  makes container construction several times slower; read-only behaviour is
  verified in tests with :func:`container_fingerprint`.
"""

from __future__ import annotations

import threading
from typing import Any

__all__ = ["AutoInitMixin", "container_fingerprint"]

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
        """Complete initialization and mark the container as published."""
        self._ensure_init()
        _object_getattribute(self, "__dict__")["_frozen"] = True
        return self

    def is_frozen(self) -> bool:
        """Return whether ``freeze()`` has published this container."""
        return bool(_object_getattribute(self, "__dict__").get("_frozen", False))


def container_fingerprint(container: Any) -> tuple[tuple[str, str], ...]:
    """Return a comparable snapshot of a container's instance state.

    Used by tests to prove that consumers did not mutate a published
    container. Values are compared through ``repr`` so nested lists and dicts
    are captured by content.
    """
    state = _object_getattribute(container, "__dict__")
    return tuple(sorted((key, repr(value)) for key, value in state.items()))
