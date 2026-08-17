"""统一 HMAC 签名工具（B-15：39 处 hmac 签名收敛为一份实现）。"""

from __future__ import annotations

import base64
import hashlib
import hmac


def sign_hmac_sha256_hex(secret: str, payload: str) -> str:
    """HMAC-SHA256 hex 摘要（Binance 等用 hexdigest）。"""
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def sign_hmac_sha256_b64(secret: str, payload: str) -> str:
    """HMAC-SHA256 base64 摘要（OKX 等用 base64）。"""
    digest = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()
