"""R2-A (iteration 60): strict v3 decoding keeps the 62fcb89 semantics.

The decode path now reuses the last parsed identity/scope for equal decoded
maps, memoizes stream-constant header text checks, compares key sets at C
level and inlines scalar freezing. Randomized differential tests compare every
outcome (decoded header/payload or the stable error code and field) with a
frozen copy of the previous module, including interleavings that exercise
cache hits right before invalid or differently typed variants.
"""

from __future__ import annotations

import math
import random
import uuid

import msgpack
import pytest
from r2a_reference import service_protocol_62fcb89 as ref

from bt_api_base import service_protocol as new


def _header_wire(sequence: int = 1) -> dict:
    return {
        "protocol_version": 3,
        "kind": "event",
        "message_id": uuid.uuid4().hex,
        "correlation_id": None,
        "identity": {
            "role": "service",
            "principal_ref": "gateway-market-hub",
            "actor_ref": "ctp-provider",
            "delegate_ref": None,
        },
        "scope": {
            "execution_domain_ref": "public:ctp-market",
            "account_ref": None,
            "account_refs": [],
            "strategy_ref": None,
            "run_id": None,
            "manual_book_ref": None,
            "portfolio_ref": None,
            "group_id": None,
            "leg_id": None,
        },
        "operation": "market.event",
        "schema_id": "sdk.market.event",
        "schema_version": 1,
        "sent_at_utc": "2026-11-04T01:02:03.456789Z",
        "owner_epoch": None,
        "stream_id": "market-" + "a" * 64,
        "stream_epoch": "epoch-1",
        "sequence": sequence,
    }


def _payload() -> dict:
    return {
        "key": {"a": 1, "b": [1, 2.5, "x"], "c": {"d": None, "e": True}},
        "data": {"price": 1500.0, "flags": [], "nested": [{"x": 1}, []], "text": "é"},
    }


_POOL = (
    None,
    0,
    1,
    -3,
    True,
    1.5,
    math.nan,
    math.inf,
    "",
    " pad",
    "ok",
    "\x07bell",
    "x" * 300,
    "service",
    "strategy_client",
    "request",
    "reply",
    "event",
    "2026-11-04T01:02:03Z",
    "2026-13-04T01:02:03Z",
    "2026-11-04 01:02:03Z",
    [],
    ["acct-1"],
    ["acct-1", "acct-1"],
    [1],
    {},
    {"k": 1},
    b"bytes",
    "acct-1",
    "strategy-1",
    "group-1",
    "pf-1",
)


def _mutate(rng: random.Random, sequence: int):
    envelope = {
        "contract": new.wire_contract_digest(),
        "header": _header_wire(sequence),
        "payload": _payload(),
    }
    for _ in range(rng.choice((0, 1, 1, 2, 3))):
        target = rng.random()
        header = envelope.get("header")
        header = header if type(header) is dict else {}
        payload = envelope.get("payload")
        payload = payload if type(payload) is dict else {}
        if target < 0.35:
            node = header
        elif target < 0.55:
            node = header.get("identity")
        elif target < 0.8:
            node = header.get("scope")
        elif target < 0.9:
            node = payload.get("data")
        else:
            node = envelope
        if type(node) is not dict or not node:  # an earlier mutation replaced it
            continue
        action = rng.random()
        if action < 0.82:
            node[rng.choice(sorted(node))] = rng.choice(_POOL)
        elif action < 0.9:
            del node[rng.choice(sorted(node))]
        else:
            node["extra"] = 1
    return envelope


def _outcome(module, data: bytes):
    try:
        envelope = module.decode_envelope(data)
    except module.WireValidationError as exc:
        return ("error", exc.code.value, exc.field.value)
    header = envelope.header
    return (
        "ok",
        module._header_to_wire(header),
        type(header.identity.role).__name__,
        header.scope.account_refs,
        module._thaw_json_value(envelope.payload),
        repr(envelope.payload),
    )


def _pack(value) -> bytes:
    return msgpack.packb(value, use_bin_type=True)


def test_decode_matches_the_previous_implementation_on_randomized_envelopes() -> None:
    rng = random.Random(20261104)
    kinds = {"ok": 0, "error": 0}
    for index in range(6000):
        data = _pack(_mutate(rng, index + 1))
        expected = _outcome(ref, data)
        actual = _outcome(new, data)
        assert actual[0] == expected[0], (index, data)
        if expected[0] == "ok":
            # message ids differ per call only through the input: compare all.
            assert actual == expected, index
        else:
            assert actual == expected, (index, data)
        kinds[expected[0]] += 1
    assert kinds["ok"] > 1000 and kinds["error"] > 2000


def test_interleaved_cache_hits_never_accept_an_invalid_variant() -> None:
    rng = random.Random(3)
    valid = _pack(
        {"contract": new.wire_contract_digest(), "header": _header_wire(), "payload": _payload()}
    )
    for index in range(4000):
        data = valid if index % 2 == 0 else _pack(_mutate(rng, index + 1))
        assert _outcome(new, data) == _outcome(ref, data), index


def test_duplicate_keys_trailing_bytes_and_extensions_are_still_refused() -> None:
    good = {"contract": new.wire_contract_digest(), "header": _header_wire(), "payload": _payload()}
    data = _pack(good)
    new.decode_envelope(data)  # seeds the identity/scope cache
    duplicate = msgpack.Packer(use_bin_type=True).pack_map_pairs(
        [
            ("contract", new.wire_contract_digest()),
            ("header", good["header"]),
            ("payload", good["payload"]),
            ("payload", {}),
        ]
    )
    cases = [
        data + b"\x00",
        duplicate,
        _pack(dict(good, payload={"x": msgpack.ExtType(1, b"x")})),
        _pack(dict(good, payload={"x": float("nan")})),
        _pack(dict(good, payload={"x": b"raw"})),
        b"\x81\xa1a",  # truncated
    ]
    nested = {"x": 1}
    for _ in range(70):
        nested = {"x": nested}
    cases.append(_pack(dict(good, payload=nested)))
    for case in cases:
        expected = _outcome(ref, case)
        assert expected[0] == "error"
        assert _outcome(new, case) == expected


class _StrSub(str):
    pass


def test_non_decode_parsers_do_not_use_the_decoded_claim_cache() -> None:
    header = _header_wire()
    data = _pack({"contract": new.wire_contract_digest(), "header": header, "payload": {}})
    new.decode_envelope(data)  # cache now holds this identity/scope
    sneaky = dict(header)
    sneaky["identity"] = dict(header["identity"], principal_ref=_StrSub("gateway-market-hub"))
    for module in (new, ref):
        with pytest.raises(module.WireValidationError) as caught:
            module.envelope_from_wire_mapping({"header": sneaky, "payload": {}})
        assert caught.value.code.value == "invalid_type"


def test_repeated_text_memo_refuses_subclasses_and_is_bounded() -> None:
    header = new.decode_envelope(
        _pack({"contract": new.wire_contract_digest(), "header": _header_wire(), "payload": {}})
    ).header
    assert header.operation in new._CHECKED_TEXT
    for module in (new, ref):
        with pytest.raises(module.WireValidationError) as caught:
            module.WireHeader(
                protocol_version=3,
                kind=module.WireMessageKind.EVENT,
                message_id="m",
                correlation_id=None,
                identity=module.WireIdentity(module.WireRole.SERVICE, "p", "a"),
                scope=module.WireScope(execution_domain_ref="d"),
                operation=_StrSub("market.event"),
                schema_id="sdk.market.event",
                schema_version=1,
                sent_at_utc="2026-11-04T01:02:03Z",
                stream_id="s",
                stream_epoch="e",
                sequence=1,
            )
        assert (caught.value.code.value, caught.value.field.value) == ("invalid_type", "operation")
    for module in (new, ref):
        with pytest.raises(module.WireValidationError) as caught:
            module.WireHeader(
                protocol_version=3,
                kind=module.WireMessageKind.REQUEST,
                message_id="m",
                correlation_id=None,
                identity=module.WireIdentity(module.WireRole.SERVICE, "p", "a"),
                scope=module.WireScope(execution_domain_ref="d"),
                operation=None,
                schema_id="x",
                schema_version=1,
                sent_at_utc="2026-11-04T01:02:03Z",
            )
        assert (caught.value.code.value, caught.value.field.value) == ("invalid_type", "operation")
    new._CHECKED_TEXT.clear()
    for index in range(new._CHECKED_TEXT_LIMIT + 5):
        new._check_repeated_text(f"op-{index}", new.WireField.OPERATION)
    assert len(new._CHECKED_TEXT) <= new._CHECKED_TEXT_LIMIT


def test_freeze_inline_scalars_match_previous_freeze() -> None:
    rng = random.Random(11)
    leaves = (None, True, 0, -5, 2.5, math.inf, math.nan, "a", "é", "\ud800", b"x", object())
    for index in range(3000):
        value = {f"k{i}": rng.choice(leaves) for i in range(rng.randint(0, 6))}
        if rng.random() < 0.3:
            value["nested"] = {"x": rng.choice(leaves), "y": [rng.choice(leaves)]}
        if rng.random() < 0.05:
            value[1] = "non-text key"

        def run(module):
            try:
                frozen = module._freeze_payload(value)
            except module.WireValidationError as exc:
                return ("error", exc.code.value)
            return ("ok", repr(module._thaw_json_value(frozen)))

        assert run(new) == run(ref), (index, value)
