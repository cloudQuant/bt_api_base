"""
Auto-init mixin for Container classes
 get_*  init_data()， None

:
   AutoInitMixin， get_*  init_data()

  class AccountData(AutoInitMixin):
      ...

  # :
  account.init_data()
  account.get_balance()
  # :
  account.get_balance()  #  init_data()
"""

from __future__ import annotations

__all__ = ["AutoInitMixin"]


class AutoInitMixin:
    """ mixin， init_data() 

     __getattribute__  get_* ， init_data()。
     init_data() ，。
    """

    def _ensure_init(self) -> AutoInitMixin:
        """， init_data()"""
        if not getattr(self, "_initialized", False):
            # Guard against re-entrant calls: init_data() may call get_*
            # methods on self, which would trigger _ensure_init() again.
            # Set flag BEFORE init_data() to prevent recursion, but track
            # success to handle exceptions properly.
            self._initialized = True
            try:
                self.init_data()
            except BaseException:
                # Reset flag if init_data() fails, allowing retry
                # BaseException catches all including KeyboardInterrupt/SystemExit
                # but we re-raise immediately, preserving the original exception
                self._initialized = False
                raise
        return self

    def __getattribute__(self, name: str) -> object:
        #  get_* （ get_event/get_event_type/get_data ）
        #  _ensure_init()
        attr = super().__getattribute__(name)
        if (
            name.startswith("get_")
            and name not in ("get_event", "get_event_type", "get_data")
            and callable(attr)
        ):
            try:
                initialized = object.__getattribute__(self, "_initialized")
            except AttributeError:
                initialized = False
            if not initialized:
                self._ensure_init()
        return attr
