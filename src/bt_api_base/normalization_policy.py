"""Shared legacy defaults for explicitly declared provider normalization."""


class LegacyNormalizationPolicy:
    """Defaults do not establish provider, account or execution authority."""

    quantity_unit = "base"
    default_multiplier = None
    zero_balance_currency = None
    funding_time_fields = ("nextFundingTime", "fundingTime")
    position_mode_ack_code = "200"
    trade_authority = False

    def order_average(self, row, average, *, pick, number):
        return average

    def apply_cancel_result(self, normalized, result, request):
        return None


def legacy_normalization_policy(exchange_name):
    """Return the legacy defaults explicitly selected by one provider route."""
    return LegacyNormalizationPolicy()


__all__ = ("LegacyNormalizationPolicy", "legacy_normalization_policy")
