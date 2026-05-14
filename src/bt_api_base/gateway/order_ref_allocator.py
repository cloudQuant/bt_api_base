"""Persistent CTP OrderRef allocator."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_STATE_KEY = "last_order_ref"


class OrderRefAllocator:
    def __init__(
        self,
        account_id: str,
        state_dir: str | Path = "/tmp/bt_gateway_state",  # nosec B108
        initial_value: int = 0,
    ) -> None:
        self._account_id = account_id
        self._state_dir = Path(state_dir)
        self._state_file = self._state_dir / f"gateway_{account_id}_state.json"
        self._lock = threading.RLock()
        self._value: int = initial_value
        self._load()

    def next(self) -> str:
        with self._lock:
            self._value += 1
            value = self._value
            self._persist_locked()
            return str(value)

    def current(self) -> int:
        with self._lock:
            return self._value

    def align_with_max(self, max_order_ref: int | str) -> None:
        max_val = int(max_order_ref)
        with self._lock:
            if max_val > self._value:
                logger.info(
                    "OrderRefAllocator[%s]: aligning %d -> %d",
                    self._account_id,
                    self._value,
                    max_val,
                )
                self._value = max_val
            self._persist_locked()

    def reset(self, value: int = 0) -> None:
        with self._lock:
            self._value = value
            self._persist_locked()

    def _load(self) -> None:
        if not self._state_file.exists():
            return
        try:
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise TypeError(f"state payload must be an object, got {type(data).__name__}")
            saved = int(data.get(_STATE_KEY, 0) or 0)
            with self._lock:
                if saved > self._value:
                    self._value = saved
            logger.info(
                "OrderRefAllocator[%s]: loaded last_order_ref=%d from %s",
                self._account_id,
                self._value,
                self._state_file,
            )
        except (TypeError, ValueError, json.JSONDecodeError, OSError) as exc:
            logger.warning("OrderRefAllocator[%s]: failed to load state: %s", self._account_id, exc)

    def _persist_locked(self) -> None:
        try:
            self._state_dir.mkdir(parents=True, exist_ok=True)
            existing: dict[str, Any] = {}
            if self._state_file.exists():
                try:
                    loaded = json.loads(self._state_file.read_text(encoding="utf-8"))
                    if not isinstance(loaded, dict):
                        raise TypeError(
                            f"state payload must be an object, got {type(loaded).__name__}"
                        )
                    existing = loaded
                except (TypeError, json.JSONDecodeError, OSError) as exc:
                    logger.warning(
                        "OrderRefAllocator[%s]: failed to read existing state during persist: %s",
                        self._account_id,
                        exc,
                    )
            existing[_STATE_KEY] = int(self._value)
            tmp_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    delete=False,
                    dir=self._state_dir,
                    prefix=f"{self._state_file.stem}_",
                    suffix=".tmp",
                    encoding="utf-8",
                ) as handle:
                    json.dump(existing, handle, indent=2)
                    tmp_path = Path(handle.name)
                os.replace(str(tmp_path), str(self._state_file))
            finally:
                if tmp_path is not None and tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError as exc:
                        logger.warning(
                            "OrderRefAllocator[%s]: failed to clean up temp state file %s: %s",
                            self._account_id,
                            tmp_path,
                            exc,
                        )
        except (TypeError, ValueError, OSError) as exc:
            logger.warning(
                "OrderRefAllocator[%s]: failed to persist state: %s",
                self._account_id,
                exc,
            )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "account_id": self._account_id,
                "last_order_ref": self._value,
                "state_file": str(self._state_file),
            }
