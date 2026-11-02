"""Build source-alias contracts from neutral and provider-declared fields.

These mappings select source values; they do not authenticate a provider,
establish an account fact, or grant execution authority.
"""

from collections.abc import Mapping
from types import MappingProxyType


_RISK_ORDER = {
    "provider_order_id": ("order_id", "external_order_id"),
    "client_order_id": ("client_order_id",),
    "status": ("status", "order_status", "state"),
    "filled_quantity": ("filled", "filled_quantity", "executed_qty"),
    "quantity": ("quantity", "size", "order_size"),
    "account_id": ("account_id",),
    "instrument": (
        "symbol",
        "symbol_name",
        "instrument",
        "instrument_id",
        "data_name",
        "trade_symbol",
    ),
    "side": ("side", "order_side", "trade_side"),
    "price": ("price", "limit_price", "order_price"),
    "position_side": ("position_side",),
    "offset": ("offset", "order_offset", "trade_offset"),
}
_GROUP_ORDER = {
    "order_id": ("order_id", "external_order_id"),
    "client_order_id": ("client_order_id",),
    "status": ("status", "order_status", "state"),
    "filled": ("filled", "filled_quantity", "executed_qty"),
    "quantity": ("quantity", "size", "order_size"),
    "account_id": ("account_id",),
    "instrument": (
        "symbol",
        "symbol_name",
        "instrument",
        "instrument_id",
        "data_name",
        "trade_symbol",
    ),
    "side": ("side", "order_side", "trade_side"),
    "price": ("price", "limit_price", "order_price"),
}
_GROUP_FILL = {
    "trade_id": ("trade_id", "fill_id", "deal_id"),
    "order_id": ("order_id", "external_order_id"),
    "client_order_id": ("client_order_id",),
    "account_id": ("account_id",),
    "instrument": (
        "symbol",
        "symbol_name",
        "instrument",
        "instrument_id",
        "data_name",
        "trade_symbol",
    ),
    "side": ("side", "order_side", "trade_side"),
    "quantity": ("quantity", "size", "trade_volume", "qty", "volume"),
    "price": ("trade_price", "price"),
}

RISK_ORDER_SOURCE_SEMANTICS = frozenset(_RISK_ORDER)
GROUP_ORDER_SOURCE_SEMANTICS = frozenset(_GROUP_ORDER)
GROUP_FILL_SOURCE_SEMANTICS = frozenset(_GROUP_FILL)


def build_provider_order_source_aliases(
    source_fields,
    *,
    risk_order_native_aliases=None,
    group_order_native_aliases=None,
    group_fill_native_aliases=None,
):
    """Return immutable neutral-plus-provider aliases for the three consumers."""
    if type(source_fields) is not frozenset or any(
        type(field) is not str or not field for field in source_fields
    ):
        raise ValueError("provider source fields must be a frozenset of names")

    def project(template, native):
        if native is None:
            native = {}
        if not isinstance(native, Mapping) or set(native) - set(template):
            raise ValueError("provider native source alias semantics are invalid")
        result = {}
        for semantic, neutral in template.items():
            declared = native.get(semantic, ())
            if type(declared) is not tuple or any(
                type(name) is not str or not name or name not in source_fields for name in declared
            ):
                raise ValueError("provider native source aliases are invalid")
            names = [name for name in neutral if name in source_fields]
            names.extend(name for name in declared if name not in names)
            result[semantic] = tuple(names)
        return MappingProxyType(result)

    return (
        project(_RISK_ORDER, risk_order_native_aliases),
        project(_GROUP_ORDER, group_order_native_aliases),
        project(_GROUP_FILL, group_fill_native_aliases),
    )
