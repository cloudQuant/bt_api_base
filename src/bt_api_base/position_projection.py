"""Position-field projection using provider-declared source aliases."""


def project_position_fields(row, policy, *, pick, number, decimal_number):
    """Project supplied position fields without asserting account authority."""
    fields = policy.position_fields
    raw_amount = pick(row, *fields["quantity"])
    if raw_amount in (None, ""):
        raise ValueError("position_quantity_missing")
    exact_amount = decimal_number(raw_amount)
    amount = number(raw_amount)
    if amount == 0 and exact_amount != 0:
        amount = exact_amount
    side = str(pick(row, *fields["side"], default="net")).lower()
    side = {"buy": "long", "sell": "short", "both": "net"}.get(side, side)
    if side not in {"long", "short", "net"}:
        raise ValueError("unknown_position_side")
    quantity = abs(amount) if side in {"long", "short"} else amount
    return {
        "quantity": quantity,
        "quantity_known": True,
        "quantity_exact_zero": exact_amount == 0,
        "size": quantity,
        "volume": abs(amount),
        "position_side": side,
        "direction": ("short" if amount < 0 else "long") if side == "net" else side,
        "position_id": pick(row, *fields["position_id"]),
        "quantity_unit": pick(row, "quantity_unit", default=policy.quantity_unit),
        "price": number(pick(row, *fields["price"])),
        "today": number(pick(row, *fields["today"])),
        "yesterday": number(pick(row, *fields["yesterday"])),
        "multiplier": number(pick(row, *fields["multiplier"])),
        "offset": pick(row, "offset"),
        "exchange_id": pick(row, *fields["exchange_id"]),
    }


__all__ = ("project_position_fields",)
