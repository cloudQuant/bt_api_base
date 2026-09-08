"""Process-local receive-clock metadata shared by venue event containers."""

from __future__ import annotations

import hashlib
import os
import socket
import time

_SEED = f"{socket.gethostname()}:{os.getpid()}:{time.monotonic_ns()}"
CLOCK_DOMAIN_ID = hashlib.sha256(_SEED.encode("utf-8")).hexdigest()[:24]


def capture_receive_clock() -> tuple[float, int, str]:
    """Capture comparable wall/monotonic values at one SDK ingress boundary."""
    return time.time(), time.monotonic_ns(), CLOCK_DOMAIN_ID


__all__ = ["CLOCK_DOMAIN_ID", "capture_receive_clock"]
