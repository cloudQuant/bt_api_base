"""统一时间戳工具（B-15：15+ 处时间戳转换收敛为一份实现）。"""

from __future__ import annotations

import time
from datetime import datetime, timezone


def utc_now_iso8601() -> str:
    """按 ISO 8601 规范生成毫秒时间戳（UTC，如 2020-12-08T09:08:57.715Z）。"""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}" + "Z"


def utc_now_epoch_ms() -> int:
    """当前 epoch 毫秒时间戳。"""
    return int(time.time() * 1000)


def utc_now_epoch_s() -> int:
    """当前 epoch 秒时间戳。"""
    return int(time.time())
