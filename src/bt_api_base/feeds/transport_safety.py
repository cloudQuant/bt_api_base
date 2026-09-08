"""Redaction helpers for transport logs, events, and exception messages."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REDACTED = "***"

_SENSITIVE_KEY_PARTS = (
    "apikey",
    "accesskey",
    "secret",
    "token",
    "signature",
    "password",
    "passphrase",
    "authorization",
    "privatekey",
    "publickey",
    "listenkey",
)
_SENSITIVE_EXACT_KEYS = {"nonce", "timestamp"}
_URL_PATTERN = re.compile(r"(?:https?|wss?)://[^\s<>\"']+", re.IGNORECASE)
_KEY_VALUE_PATTERN = re.compile(
    r"(?ix)"
    r"(?P<prefix>"
    r"(?:api[-_ ]?key|access[-_ ]?key|secret|token|signature|password|passphrase|"
    r"authorization|private[-_ ]?key|public[-_ ]?key|listen[-_ ]?key|nonce|timestamp|"
    r"x-mbx-apikey|ok-access-sign|kc-api-sign|cb-access-sign)"
    r"\s*[\"']?\s*[:=]\s*[\"']?"
    r")"
    r"(?P<value>[^\s,;}&\"']+)",
)
_BEARER_PATTERN = re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]+")


def is_sensitive_key(key: Any) -> bool:
    """Return whether a mapping/query/header key can carry credentials."""
    normalized = str(key).replace("-", "").replace("_", "").replace(" ", "").lower()
    return (
        normalized in _SENSITIVE_EXACT_KEYS
        or normalized.endswith("sign")
        or any(part in normalized for part in _SENSITIVE_KEY_PARTS)
    )


def _redact_user_info(parsed: Any) -> str:
    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    if parsed.port is not None:
        hostname = f"{hostname}:{parsed.port}"
    if parsed.username is not None or parsed.password is not None:
        return f"{REDACTED}@{hostname}"
    return hostname


def _redact_websocket_path(path: str, scheme: str) -> str:
    if scheme not in {"ws", "wss"}:
        return path
    parts = path.split("/")
    for marker in ("ws", "stream"):
        try:
            marker_index = parts.index(marker)
        except ValueError:
            continue
        if marker_index + 1 < len(parts) and parts[marker_index + 1]:
            parts[marker_index + 1] = REDACTED
            return "/".join(parts)
    return path


def sanitize_url(url: Any) -> Any:
    """Redact credentials in an HTTP/WebSocket URL while preserving its route."""
    if not isinstance(url, str):
        return url
    try:
        parsed = urlsplit(url)
        if parsed.scheme.lower() not in {"http", "https", "ws", "wss"}:
            return url
        query = urlencode(
            [
                (key, REDACTED if is_sensitive_key(key) else value)
                for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            ],
            doseq=True,
        )
        return urlunsplit(
            (
                parsed.scheme,
                _redact_user_info(parsed),
                _redact_websocket_path(parsed.path, parsed.scheme.lower()),
                query,
                parsed.fragment,
            )
        )
    except (TypeError, ValueError):
        return "<redacted-invalid-url>"


def _trim_url_punctuation(candidate: str) -> tuple[str, str]:
    suffix = ""
    while candidate and candidate[-1] in ".,;:)]}":
        suffix = candidate[-1] + suffix
        candidate = candidate[:-1]
    return candidate, suffix


def sanitize_text(value: Any, *, sensitive_values: Iterable[Any] = ()) -> str:
    """Redact credential-like material from arbitrary transport text."""
    text = str(value)

    def replace_url(match: re.Match[str]) -> str:
        candidate, suffix = _trim_url_punctuation(match.group(0))
        return f"{sanitize_url(candidate)}{suffix}"

    text = _URL_PATTERN.sub(replace_url, text)
    text = _KEY_VALUE_PATTERN.sub(lambda match: f"{match.group('prefix')}{REDACTED}", text)
    text = _BEARER_PATTERN.sub(rf"\1{REDACTED}", text)
    for secret in sensitive_values:
        if secret is None:
            continue
        secret_text = str(secret)
        if secret_text:
            text = text.replace(secret_text, REDACTED)
    return text


def sensitive_mapping_values(value: Mapping[Any, Any] | None) -> tuple[Any, ...]:
    """Collect values from credential-bearing mapping keys for exception cleanup."""
    if not value:
        return ()
    return tuple(item for key, item in value.items() if is_sensitive_key(key))


def _collect_sensitive_values(value: Any) -> tuple[str, ...]:
    collected: list[str] = []

    def add(item: Any) -> None:
        if isinstance(item, bytes):
            item = item.decode(errors="ignore")
        if isinstance(item, str):
            if len(item) >= 4:
                collected.append(item)
        elif isinstance(item, int) and len(str(abs(item))) >= 8:
            collected.append(str(item))

    def walk(item: Any) -> None:
        if isinstance(item, Mapping):
            for key, nested in item.items():
                if is_sensitive_key(key):
                    add(nested)
                walk(nested)
        elif isinstance(item, (list, tuple)):
            for nested in item:
                walk(nested)

    walk(value)
    return tuple(dict.fromkeys(collected))


def sanitize_value(value: Any) -> Any:
    """Recursively redact mappings and sanitize strings for external observability."""
    sensitive_values = _collect_sensitive_values(value)

    def sanitize(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {
                key: REDACTED if is_sensitive_key(key) else sanitize(nested)
                for key, nested in item.items()
            }
        if isinstance(item, list):
            return [sanitize(nested) for nested in item]
        if isinstance(item, tuple):
            return tuple(sanitize(nested) for nested in item)
        if isinstance(item, str):
            return sanitize_text(item, sensitive_values=sensitive_values)
        return item

    return sanitize(value)
