"""bt_api_base functions 工具模块黄金向量测试（B-15）。"""

from __future__ import annotations

import re

from bt_api_base.functions.signers import sign_hmac_sha256_b64, sign_hmac_sha256_hex
from bt_api_base.functions.timestamps import utc_now_iso8601


def test_sign_hmac_sha256_b64_golden_vector() -> None:
    """OKX V5 签名黄金向量：Base64(HMAC-SHA256(timestamp+method+path+body, secret))。

    复算命令：
    python3 -c "import hmac,hashlib,base64; s='F0E1D2C3B4A5968778695A4B3C2D1E0F'; pre='2020-12-08T09:08:57.715ZGET/api/v5/account/balance'; print(base64.b64encode(hmac.new(s.encode(),pre.encode(),hashlib.sha256).digest()).decode())"
    """
    secret = "F0E1D2C3B4A5968778695A4B3C2D1E0F"
    payload = "2020-12-08T09:08:57.715ZGET/api/v5/account/balance"
    assert (
        sign_hmac_sha256_b64(secret, payload)
        == "ymzav0cu8v4AhecjpRnt8sRQ8vOk/6+BT89eeU/sIjQ="
    )


def test_sign_hmac_sha256_hex_golden_vector() -> None:
    """Binance 签名黄金向量：HMAC-SHA256 hexdigest（占位密钥）。

    复算命令：
    python3 -c "import hmac; from urllib.parse import urlencode; c=urlencode({'recvWindow':3000,'timestamp':1709265105581,'symbol':'OPUSDT'}); k='0'*64; print(hmac.new(k.encode(),c.encode(),digestmod='sha256').hexdigest())"
    """
    from urllib.parse import urlencode

    content = urlencode({"recvWindow": 3000, "timestamp": 1709265105581, "symbol": "OPUSDT"})
    placeholder_key = "0" * 64
    assert (
        sign_hmac_sha256_hex(placeholder_key, content)
        == "aafc6c7eea21da4aad680c83027560efb234c6919f5dbeec152b2c10ad1fd684"
    )


def test_utc_now_iso8601_format() -> None:
    """utc_now_iso8601 必须符合 ISO 8601 毫秒格式。"""
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", utc_now_iso8601())
