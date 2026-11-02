"""Project explicitly supplied identity fields using a selected field policy.

Field presence is not source authenticity, order confirmation or authority.
Provider-native field names are supplied separately by the selected policy.
"""

from enum import Enum

from .order_identity_fields import LEGACY_ORDER_IDENTITY_FIELDS


def explicit_execution_identity_fields(row, policy):
    """Return semantic names present in a row or its configured nested row."""
    nested_field = policy.identity_nested_field
    nested_value = row.get(nested_field) if nested_field is not None else None
    nested = nested_value if isinstance(nested_value, dict) else {}
    fields = set()
    for semantic, names in policy.identity_fields.items():
        if any(row.get(name) not in (None, "") for name in names):
            fields.add(semantic)
    for semantic, names in policy.nested_identity_fields.items():
        if any(nested.get(name) not in (None, "") for name in names):
            fields.add(semantic)
    return sorted(fields)



def unsupported_order_identity_aliases(row, policy):
    """Find known identity aliases outside a selected provider contract."""
    known = {name for names in LEGACY_ORDER_IDENTITY_FIELDS.values() for name in names}
    selected = {name for names in policy.identity_fields.values() for name in names}
    return tuple(sorted(name for name in known - selected if row.get(name) not in (None, "")))


def normalize_side_candidates(candidates, *, position=False):
    """Project selected provider candidates into neutral order or position side."""
    accepted = {"long", "short", "net"} if position else {"buy", "sell"}
    for value in candidates:
        if isinstance(value, Enum):
            value = value.value
        if not isinstance(value, str):
            continue
        value = value.lower()
        if position:
            value = {"both": "net", "buy": "long", "sell": "short"}.get(value, value)
        if value in accepted:
            return value
    return None


def normalize_position_mode(row, policy, *, default=None, pick):
    """Project provider-selected position-mode fields into neutral values."""
    flag = policy.position_mode_boolean_field
    if flag is not None and flag in row:
        value = row[flag]
    else:
        value = pick(row, *policy.position_mode_fields, default=default)
    value = getattr(value, "value", value)
    if isinstance(value, bool):
        return "dual_side" if value else "net"
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip().lower().replace("-", "_").replace(" ", "_")
    return policy.position_mode_aliases.get(value, value)


def semantic_identity_value(key, value, exchange_name=None, *, native_unit_resolver):
    """Canonicalize one already-projected order identity for comparison."""
    if value is None or value == "":
        return value
    value = getattr(value, "value", value)
    if key == "position_mode" and isinstance(value, bool):
        return "dual_side" if value else "net"
    text = str(value).strip().casefold().replace("-", "_").replace(" ", "_")
    if key == "position_side":
        return {"both": "net", "buy": "long", "sell": "short"}.get(text, text)
    if key == "offset":
        return {"closetoday": "close_today", "closeyesterday": "close_yesterday"}.get(text, text)
    if key == "position_mode":
        return {
            "net_mode": "net", "oneway": "net", "one_way": "net",
            "long_short_mode": "dual_side", "hedge": "dual_side", "hedge_mode": "dual_side",
        }.get(text, text)
    if key == "quantity_unit":
        text = {"contract": "contracts", "lot": "lots"}.get(text, text)
        if text == "native":
            venue = str(exchange_name or "").strip().upper()
            if venue:
                return native_unit_resolver(venue)
        return text
    return text


def explicit_ledger_identity_fields(row, *, semantic_fields, explicit_fields_key):
    """Return ledger identity fields backed by the row rather than defaults."""
    fields = row.get(explicit_fields_key)
    if fields is None:
        return {key for key in semantic_fields if row.get(key) not in (None, "")}
    if not isinstance(fields, (list, tuple, set, frozenset)):
        return set()
    return {str(key) for key in fields if key in semantic_fields}


def order_identity_conflict_code(
    state, row, *, semantic_fields, explicit_fields_key, native_unit_resolver
):
    """Compare explicit identity values without asserting provider authenticity."""
    reported_explicit = explicit_ledger_identity_fields(
        row, semantic_fields=semantic_fields, explicit_fields_key=explicit_fields_key
    )
    state_explicit = explicit_ledger_identity_fields(
        state, semantic_fields=semantic_fields, explicit_fields_key=explicit_fields_key
    )
    for key in (
        "symbol", "exchange_name", "client_order_id", "order_id", "exchange_id", "front_id",
        "session_id", "order_ref", "position_id", "side", "position_side", "offset",
        "position_mode", "quantity_unit", "trading_day",
    ):
        if key in semantic_fields and (key not in state_explicit or key not in reported_explicit):
            continue
        existing, reported = state.get(key), row.get(key)
        if key in semantic_fields:
            exchange_name = state.get("exchange_name") or row.get("exchange_name")
            existing = semantic_identity_value(
                key, existing, exchange_name, native_unit_resolver=native_unit_resolver
            )
            reported = semantic_identity_value(
                key, reported, exchange_name, native_unit_resolver=native_unit_resolver
            )
        if (
            existing not in (None, "")
            and reported not in (None, "")
            and str(existing) != str(reported)
        ):
            return "ledger_mismatch" if key in semantic_fields else "order_identity_mismatch"
    return None


__all__ = (
    "explicit_ledger_identity_fields",
    "explicit_execution_identity_fields",
    "unsupported_order_identity_aliases",
    "normalize_position_mode",
    "normalize_side_candidates",
    "order_identity_conflict_code",
    "semantic_identity_value",
)
