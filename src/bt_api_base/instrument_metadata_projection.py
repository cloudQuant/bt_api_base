"""Shared instrument metadata projection using provider-declared field names."""


def project_instrument_metadata(row, policy, *, pick, number):
    """Project supplied fields without asserting instrument-rule authority."""
    fields = policy.instrument_fields
    defaults = policy.instrument_metadata_defaults(row, pick=pick)
    multiplier = number(pick(row, *fields["multiplier"]))
    value_field = policy.instrument_contract_value_field
    if (
        multiplier is not None
        and value_field is not None
        and row.get(value_field) not in (None, "")
    ):
        multiplier *= number(row.get(policy.instrument_contract_multiplier_field), 1)
    if multiplier is None:
        multiplier = policy.default_multiplier
    step = number(pick(row, *fields["step"], default=defaults.get("quantity_step")))
    linear_type = policy.instrument_linear_type_field
    perpetual_type = policy.instrument_perpetual_type_field
    return {
        "quantity_unit": pick(row, "quantity_unit", default=policy.quantity_unit),
        "multiplier": multiplier,
        "lot_size": step,
        "order_size_step": step,
        "min_size": number(pick(row, *fields["min_size"], default=defaults.get("min_size"))),
        "max_size": number(pick(row, *fields["max_size"], default=defaults.get("max_size"))),
        "min_notional": number(
            pick(row, "min_notional", default=defaults.get("min_notional")), 0
        ),
        "tick_size": number(
            pick(row, *fields["tick_size"], default=defaults.get("tick_size"))
        ),
        "settlement_currency": pick(row, *fields["settlement_currency"]),
        "base_currency": pick(row, *fields["base_currency"]),
        "linear": pick(
            row,
            "linear",
            default=(
                row.get(linear_type) == "linear"
                if linear_type is not None and linear_type in row
                else True
                if perpetual_type is not None and row.get(perpetual_type) == "PERPETUAL"
                else None
            ),
        ),
        "margin_rate": number(pick(row, *fields["margin_rate"])),
        "commission_rate": number(pick(row, *fields["commission_rate"])),
        "exchange_id": pick(row, *fields["exchange_id"]),
    }


__all__ = ("project_instrument_metadata",)
