"""Versioned MessagePack wire contract v1 for cross-process market data and fill facts.

Iteration 60, step 60.08. The Gateway path encodes the Base neutral
containers once on the publishing side and decodes them once on each
receiving process into the same frozen Base objects (``MarketTickPayload``,
``MarketBar``). The direct path never imports this module's codec dependency:
``msgpack`` is imported lazily inside :func:`encode_message` and
:func:`decode_message` only (plan INV-01).

Contract v1:

* Envelope: a map with exactly ``schema_id``, ``major``, ``minor``, ``kind``,
  ``stream`` (``stream_id``, ``epoch``, ``sequence``), ``data`` and an
  optional ``ext`` (provider-namespaced extensions). Unknown top-level or
  ``data`` keys are rejected: a field that could change the meaning of a
  message is never silently ignored. An unknown ``major`` is rejected; a
  newer ``minor`` is rejected unless the receiver supports it.
* Numbers: prices, sizes and other decimals travel as canonical decimal
  strings (``-?(0|[1-9][0-9]*)(\\.[0-9]*[1-9])?``): no exponent, no NaN or
  infinity, no ``-0``, no leading zeros, no trailing fractional zeros, at most
  40 significant characters. Binary floats are rejected anywhere in a message.
  Integers are limited to the signed 64-bit range.
* Strict decoding: exactly one complete object (trailing bytes rejected),
  text map keys only, duplicate keys rejected, MessagePack extension types
  rejected, bounded message size, nesting depth and container lengths.
* ``sequence`` is a positive 64-bit integer; a stream must change ``epoch``
  before it would wrap.

Field values are data, not proof: a decoded message does not authenticate its
source or grant trading permission (plan INV-05).
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import json
import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any

from bt_api_base.market_history_protocol import MarketBar
from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.market_tick_protocol import (
    MarketClockQuality,
    MarketFreshnessStatus,
    MarketTickPayload,
)
from bt_api_base.paper_fill_protocol import (
    MANAGED_PAPER_FILL_V2_FIELDS,
    MANAGED_PAPER_FILL_V2_SCHEMA,
)

__all__ = [
    "MAX_MESSAGE_BYTES",
    "SCHEMA_ID",
    "SUPPORTED_MAJOR",
    "SUPPORTED_MINOR",
    "StreamPosition",
    "WireCodecError",
    "WireMessageV1",
    "canonical_decimal",
    "codec_backend",
    "DEFAULT_DECIMAL_FIELDS",
    "command_fingerprint",
    "decode_message",
    "encode_message",
    "parse_decimal",
    "schema_digest",
]

SCHEMA_ID = "bt_api.wire.v1"
SUPPORTED_MAJOR = 1
SUPPORTED_MINOR = 0
MAX_MESSAGE_BYTES = 64 * 1024
MAX_DEPTH = 8
MAX_CONTAINER_LEN = 256
MAX_STR_LEN = 4096
_MAX_DECIMAL_CHARS = 40
_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1

_DECIMAL_RE = re.compile(r"-?(0|[1-9][0-9]*)(\.[0-9]*[1-9])?")
_EXT_KEY_RE = re.compile(r"[a-z][a-z0-9_]{0,63}")
_ENVELOPE_KEYS = frozenset({"schema_id", "major", "minor", "kind", "stream", "data"})
_STREAM_KEYS = frozenset({"stream_id", "epoch", "sequence"})


class WireCodecError(ValueError):
    """Finite, value-free wire contract failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclasses.dataclass(frozen=True)
class StreamPosition:
    """Stream identity carried with every message."""

    stream_id: str
    epoch: str
    sequence: int

    def __post_init__(self) -> None:
        for name in ("stream_id", "epoch"):
            value = getattr(self, name)
            if type(value) is not str or not value or len(value) > MAX_STR_LEN:
                raise WireCodecError("WIRE_STREAM_INVALID")
        if type(self.sequence) is not int or not 1 <= self.sequence <= _INT64_MAX:
            raise WireCodecError("WIRE_STREAM_INVALID")


@dataclasses.dataclass(frozen=True)
class WireMessageV1:
    """One decoded message: a frozen Base container plus its stream identity."""

    kind: str
    payload: Any
    stream: StreamPosition
    minor: int
    extensions: Mapping[str, Mapping[str, Any]]


# ---------------------------------------------------------------------------
# Decimal grammar
# ---------------------------------------------------------------------------


def canonical_decimal(value: Any) -> str:
    """Return the canonical v1 decimal lexeme for a finite number."""

    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal, str)):
        raise WireCodecError("WIRE_DECIMAL_INVALID")
    try:
        number = Decimal(repr(value)) if isinstance(value, float) else Decimal(value)
    except (InvalidOperation, ValueError):
        raise WireCodecError("WIRE_DECIMAL_INVALID") from None
    if not number.is_finite():
        raise WireCodecError("WIRE_DECIMAL_INVALID")
    if number == 0:
        return "0"
    text = format(number, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if not _DECIMAL_RE.fullmatch(text) or len(text) > _MAX_DECIMAL_CHARS:
        raise WireCodecError("WIRE_DECIMAL_INVALID")
    return text


def parse_decimal(text: Any) -> Decimal:
    """Parse a canonical v1 decimal lexeme; anything else is rejected."""

    if (
        type(text) is not str
        or len(text) > _MAX_DECIMAL_CHARS
        or text == "-0"
        or not _DECIMAL_RE.fullmatch(text)
    ):
        raise WireCodecError("WIRE_DECIMAL_INVALID")
    return Decimal(text)


# ---------------------------------------------------------------------------
# Kind registry
# ---------------------------------------------------------------------------

_TICK_FLOATS = frozenset(
    {
        "last_price",
        "bid_price",
        "ask_price",
        "bid_size",
        "ask_size",
        "lower_limit",
        "upper_limit",
        "turnover",
        "open_interest",
        "delta_volume",
        "cumulative_volume",
        "source_clock_error_ms",
        "receive_clock_error_ms",
    }
)
_TICK_ENUMS = {
    "source_clock_quality": MarketClockQuality,
    "receive_clock_quality": MarketClockQuality,
    "freshness_status": MarketFreshnessStatus,
}
_TICK_TUPLES = frozenset({"freshness_reason_codes", "quality_flags"})
_TICK_FIELDS = tuple(f.name for f in dataclasses.fields(MarketTickPayload))
_INSTRUMENT_FIELDS = tuple(f.name for f in dataclasses.fields(MarketInstrumentKey))
_BAR_FIELDS = tuple(f.name for f in dataclasses.fields(MarketBar))


def _encode_tick(payload: MarketTickPayload) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for name in _TICK_FIELDS:
        value = getattr(payload, name)
        if name == "instrument":
            data[name] = {key: getattr(value, key) for key in _INSTRUMENT_FIELDS}
        elif name in _TICK_FLOATS:
            data[name] = None if value is None else canonical_decimal(value)
        elif name in _TICK_ENUMS:
            data[name] = value.value
        elif name in _TICK_TUPLES:
            data[name] = list(value)
        else:
            data[name] = value
    return data


def _decode_tick(data: Mapping[str, Any]) -> MarketTickPayload:
    if set(data) != set(_TICK_FIELDS):
        raise WireCodecError("WIRE_FIELD_SET_INVALID")
    values: dict[str, Any] = {}
    for name in _TICK_FIELDS:
        raw = data[name]
        if name == "instrument":
            if not isinstance(raw, Mapping) or set(raw) != set(_INSTRUMENT_FIELDS):
                raise WireCodecError("WIRE_FIELD_SET_INVALID")
            values[name] = MarketInstrumentKey(**raw)
        elif name in _TICK_FLOATS:
            values[name] = None if raw is None else float(parse_decimal(raw))
        elif name in _TICK_ENUMS:
            try:
                values[name] = _TICK_ENUMS[name](raw)
            except ValueError:
                raise WireCodecError("WIRE_ENUM_INVALID") from None
        elif name in _TICK_TUPLES:
            if not isinstance(raw, list):
                raise WireCodecError("WIRE_VALUE_INVALID")
            values[name] = tuple(raw)
        else:
            values[name] = raw
    return MarketTickPayload(**values)


def _encode_bar(payload: MarketBar) -> dict[str, Any]:
    return {name: getattr(payload, name) for name in _BAR_FIELDS}


def _decode_bar(data: Mapping[str, Any]) -> MarketBar:
    if set(data) != set(_BAR_FIELDS):
        raise WireCodecError("WIRE_FIELD_SET_INVALID")
    for name in ("open", "high", "low", "close", "volume", "open_interest"):
        if data[name] is not None:
            parse_decimal(data[name])
    return MarketBar(**data)


_FILL_DECIMALS = ("quantity", "price", "commission")
_FILL_INTEGERS = ("match_time_ns", "event_sequence", "quote_cursor")


def _encode_fill(payload: Mapping[str, Any]) -> dict[str, Any]:
    if set(payload) != MANAGED_PAPER_FILL_V2_FIELDS:
        raise WireCodecError("WIRE_FIELD_SET_INVALID")
    if payload["schema"] != MANAGED_PAPER_FILL_V2_SCHEMA:
        raise WireCodecError("WIRE_SCHEMA_UNSUPPORTED")
    data = dict(payload)
    for name in _FILL_DECIMALS:
        data[name] = canonical_decimal(Decimal(data[name]) if type(data[name]) is str else data[name])
    return data


def _decode_fill(data: Mapping[str, Any]) -> Mapping[str, Any]:
    if set(data) != MANAGED_PAPER_FILL_V2_FIELDS:
        raise WireCodecError("WIRE_FIELD_SET_INVALID")
    if data["schema"] != MANAGED_PAPER_FILL_V2_SCHEMA:
        raise WireCodecError("WIRE_SCHEMA_UNSUPPORTED")
    for name in _FILL_DECIMALS:
        if parse_decimal(data[name]) < 0:
            raise WireCodecError("WIRE_DECIMAL_INVALID")
    for name in MANAGED_PAPER_FILL_V2_FIELDS:
        value = data[name]
        if name in _FILL_INTEGERS:
            if type(value) is not int or value < 0:
                raise WireCodecError("WIRE_VALUE_INVALID")
        elif type(value) is not str or not value:
            raise WireCodecError("WIRE_VALUE_INVALID")
    # Frozen view: received fill facts are shared read-only (INV-11).
    return MappingProxyType(dict(data))


class _FillFact:
    """Kind marker: encode a ``managed_paper_fill.v2`` mapping."""


_KINDS = {
    "tick": (MarketTickPayload, _encode_tick, _decode_tick),
    "bar": (MarketBar, _encode_bar, _decode_bar),
    "fill": (_FillFact, _encode_fill, _decode_fill),
}


def schema_digest() -> str:
    """Digest of the v1 kind registry, compared in the connection handshake.

    Two peers with the same version but different field tables must refuse
    to talk instead of interpreting messages differently.
    """

    registry = {
        "schema_id": SCHEMA_ID,
        "major": SUPPORTED_MAJOR,
        "minor": SUPPORTED_MINOR,
        "kinds": {
            "tick": {
                "fields": list(_TICK_FIELDS),
                "instrument": list(_INSTRUMENT_FIELDS),
                "decimals": sorted(_TICK_FLOATS),
                "enums": {k: [m.value for m in v] for k, v in sorted(_TICK_ENUMS.items())},
            },
            "bar": {"fields": list(_BAR_FIELDS)},
            "fill": {
                "schema": MANAGED_PAPER_FILL_V2_SCHEMA,
                "fields": sorted(MANAGED_PAPER_FILL_V2_FIELDS),
                "decimals": list(_FILL_DECIMALS),
                "integers": list(_FILL_INTEGERS),
            },
        },
    }
    blob = json.dumps(registry, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


# ---------------------------------------------------------------------------
# Encode / decode
# ---------------------------------------------------------------------------


def codec_backend() -> str:
    """Return ``"c"`` when msgpack's C extension is active, else ``"python"``.

    Wire contract v1 is only a performance improvement over JSON with the C
    extension (iteration 60.10 measurement); deployments should check this.
    """
    try:
        from msgpack import _cmsgpack  # noqa: F401
    except ImportError:
        return "python"
    return "c"


def _msgpack() -> Any:
    try:
        import msgpack
    except ImportError:  # pragma: no cover - exercised only without the extra
        raise WireCodecError("WIRE_CODEC_UNAVAILABLE") from None
    return msgpack


def _check_extensions(extensions: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(extensions, Mapping) or len(extensions) > 16:
        raise WireCodecError("WIRE_EXTENSION_INVALID")
    checked: dict[str, dict[str, Any]] = {}
    for provider, fields in extensions.items():
        if type(provider) is not str or not _EXT_KEY_RE.fullmatch(provider):
            raise WireCodecError("WIRE_EXTENSION_INVALID")
        if not isinstance(fields, Mapping) or len(fields) > 64:
            raise WireCodecError("WIRE_EXTENSION_INVALID")
        values: dict[str, Any] = {}
        for key, value in fields.items():
            if type(key) is not str or not _EXT_KEY_RE.fullmatch(key):
                raise WireCodecError("WIRE_EXTENSION_INVALID")
            if value is not None and type(value) not in (str, int, bool):
                raise WireCodecError("WIRE_EXTENSION_INVALID")
            values[key] = value
        checked[provider] = values
    return checked


def encode_message(
    kind: str,
    payload: Any,
    *,
    stream: StreamPosition,
    extensions: Mapping[str, Mapping[str, Any]] | None = None,
) -> bytes:
    """Encode one frozen Base container into a v1 MessagePack message."""

    entry = _KINDS.get(kind)
    if entry is None:
        raise WireCodecError("WIRE_KIND_INVALID")
    if entry[0] is _FillFact:
        if not isinstance(payload, Mapping):
            raise WireCodecError("WIRE_KIND_INVALID")
    elif type(payload) is not entry[0]:
        raise WireCodecError("WIRE_KIND_INVALID")
    if type(stream) is not StreamPosition:
        raise WireCodecError("WIRE_STREAM_INVALID")
    message: dict[str, Any] = {
        "schema_id": SCHEMA_ID,
        "major": SUPPORTED_MAJOR,
        "minor": SUPPORTED_MINOR,
        "kind": kind,
        "stream": {
            "stream_id": stream.stream_id,
            "epoch": stream.epoch,
            "sequence": stream.sequence,
        },
        "data": entry[1](payload),
    }
    if extensions:
        message["ext"] = _check_extensions(extensions)
    data = _msgpack().packb(message, use_bin_type=True)
    if len(data) > MAX_MESSAGE_BYTES:
        raise WireCodecError("WIRE_MESSAGE_TOO_LARGE")
    return data


def _no_duplicates(pairs: list[tuple[Any, Any]]) -> dict[Any, Any]:
    result: dict[Any, Any] = {}
    for key, value in pairs:
        if type(key) is not str:
            raise WireCodecError("WIRE_MAP_KEY_INVALID")
        if key in result:
            raise WireCodecError("WIRE_DUPLICATE_KEY")
        result[key] = value
    return result


def _reject_ext(code: int, data: bytes) -> Any:
    raise WireCodecError("WIRE_EXTENSION_TYPE_INVALID")


_PLAIN_SCALARS = frozenset({str, bool, type(None)})


def _check_values(root: Any) -> None:
    """Reject floats, binary, out-of-range integers and over-deep nesting.

    Iterative with a fast path for the common scalar types: this check runs
    on every received message, so it avoids per-value recursion.
    """
    stack = [(root, 0)]
    pop = stack.pop
    push = stack.append
    while stack:
        value, depth = pop()
        if depth > MAX_DEPTH:
            raise WireCodecError("WIRE_DEPTH_EXCEEDED")
        kind = type(value)
        if kind in _PLAIN_SCALARS:
            continue
        if kind is int:
            if not _INT64_MIN <= value <= _INT64_MAX:
                raise WireCodecError("WIRE_INTEGER_RANGE")
        elif kind is dict:
            child = depth + 1
            for item in value.values():
                push((item, child))
        elif kind is list:
            child = depth + 1
            for item in value:
                push((item, child))
        elif kind is float:
            raise WireCodecError("WIRE_FLOAT_FORBIDDEN")
        else:
            raise WireCodecError("WIRE_VALUE_INVALID")


def decode_message(
    data: bytes, *, supported_minor: int = SUPPORTED_MINOR
) -> WireMessageV1:
    """Strictly decode one v1 message into its frozen Base container."""

    if type(data) is not bytes:
        raise WireCodecError("WIRE_FRAME_INVALID")
    if len(data) > MAX_MESSAGE_BYTES:
        raise WireCodecError("WIRE_MESSAGE_TOO_LARGE")
    msgpack = _msgpack()
    try:
        message = msgpack.unpackb(
            data,
            raw=False,
            use_list=True,
            strict_map_key=False,  # key type is checked by _no_duplicates
            object_pairs_hook=_no_duplicates,
            ext_hook=_reject_ext,
            max_str_len=MAX_STR_LEN,
            max_bin_len=0,
            max_array_len=MAX_CONTAINER_LEN,
            max_map_len=MAX_CONTAINER_LEN,
            max_ext_len=0,
        )
    except WireCodecError:
        raise
    except msgpack.ExtraData:
        raise WireCodecError("WIRE_TRAILING_BYTES") from None
    except Exception:
        raise WireCodecError("WIRE_FRAME_INVALID") from None
    if not isinstance(message, dict):
        raise WireCodecError("WIRE_FRAME_INVALID")
    _check_values(message)

    keys = set(message)
    if not _ENVELOPE_KEYS.issubset(keys) or keys - _ENVELOPE_KEYS - {"ext"}:
        raise WireCodecError("WIRE_FIELD_SET_INVALID")
    if message["schema_id"] != SCHEMA_ID:
        raise WireCodecError("WIRE_SCHEMA_UNSUPPORTED")
    major, minor = message["major"], message["minor"]
    if type(major) is not int or major != SUPPORTED_MAJOR:
        raise WireCodecError("WIRE_MAJOR_UNSUPPORTED")
    if type(minor) is not int or minor < 0 or minor > supported_minor:
        raise WireCodecError("WIRE_MINOR_UNSUPPORTED")
    entry = _KINDS.get(message["kind"])
    if entry is None:
        raise WireCodecError("WIRE_KIND_INVALID")
    stream = message["stream"]
    if not isinstance(stream, dict) or set(stream) != _STREAM_KEYS:
        raise WireCodecError("WIRE_STREAM_INVALID")
    position = StreamPosition(stream["stream_id"], stream["epoch"], stream["sequence"])
    body = message["data"]
    if not isinstance(body, dict):
        raise WireCodecError("WIRE_FIELD_SET_INVALID")
    try:
        payload = entry[2](body)
    except WireCodecError:
        raise
    except Exception:
        # Base container validation rejected the values.
        raise WireCodecError("WIRE_PAYLOAD_INVALID") from None
    extensions = _check_extensions(message.get("ext", {}))
    return WireMessageV1(
        kind=message["kind"],
        payload=payload,
        stream=position,
        minor=minor,
        extensions=extensions,
    )


# ---------------------------------------------------------------------------
# Command identity
# ---------------------------------------------------------------------------


DEFAULT_DECIMAL_FIELDS = frozenset(
    {
        "quantity",
        "price",
        "limit_price",
        "stop_price",
        "trigger_price",
        "notional",
        "amount",
    }
)


def command_fingerprint(
    command: Mapping[str, Any], *, decimal_fields: frozenset[str] = DEFAULT_DECIMAL_FIELDS
) -> str:
    """Semantic fingerprint used for "same command ID, same content" checks.

    Equivalent encodings produce the same fingerprint: key order, absent vs.
    ``None`` optional fields, and numerically equal values of the declared
    ``decimal_fields`` (``"1.50"``, ``1.5``, ``Decimal("1.5")``) all agree.
    Every other string, including identifiers such as ``"007"``, is compared
    verbatim. Any change of account, route, strategy, command type or
    business parameter changes the fingerprint.
    """

    if not isinstance(command, Mapping):
        raise WireCodecError("WIRE_VALUE_INVALID")

    def normalize(value: Any, key: str | None) -> Any:
        if key in decimal_fields and value is not None and not isinstance(value, bool):
            return {"$d": canonical_decimal(value)}
        if isinstance(value, Mapping):
            if any(type(item) is not str for item in value):
                raise WireCodecError("WIRE_MAP_KEY_INVALID")
            return {k: normalize(v, k) for k, v in value.items() if v is not None}
        if isinstance(value, (list, tuple)):
            return [normalize(item, None) for item in value]
        if isinstance(value, enum.Enum):
            return value.value
        if value is None or isinstance(value, (bool, str, int)):
            return value
        if isinstance(value, (float, Decimal)):
            return {"$d": canonical_decimal(value)}
        raise WireCodecError("WIRE_VALUE_INVALID")

    canonical = normalize(dict(command), None)
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()
