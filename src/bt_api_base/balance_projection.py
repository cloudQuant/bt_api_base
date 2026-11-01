"""Balance-row projection using provider-declared source fields."""


def project_balance_rows(source, exchange_name, policy, *, to_dict, pick, decimal_number):
    """Project supplied rows; no source, completeness or authority is asserted."""
    fields = policy.balance_fields
    expanded = []
    for row in source:
        details = None
        for field in policy.balance_nested_fields:
            if details:
                break
            details = row.get(field)
        expanded.extend(details if isinstance(details, list) else [row])
    result = []
    for item in expanded:
        row = to_dict(item)
        currency = str(pick(row, *fields["currency"], default=""))
        cash = decimal_number(pick(row, *fields["cash"]))
        value = decimal_number(pick(row, *fields["value"]))
        if value is None:
            wallet = decimal_number(pick(row, *fields["wallet"]))
            if wallet is not None:
                value = wallet + decimal_number(pick(row, *fields["unrealized"]), 0)
        result.append(
            {
                "exchange_name": exchange_name,
                "currency": currency,
                "cash": cash,
                "value": value,
                "available_cash": cash,
                "equity": value,
                "margin_used": decimal_number(pick(row, *fields["margin_used"])),
                "account_id": pick(row, *fields["account_id"]),
            }
        )
    return result


__all__ = ("project_balance_rows",)
