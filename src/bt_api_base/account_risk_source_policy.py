"""Provider declaration of additional account-risk source binding requirements.

This declaration is not account identity, data provenance, or trading authority.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AccountRiskSourcePolicy:
    requires_native_account_binding: bool

    def __post_init__(self):
        if type(self.requires_native_account_binding) is not bool:
            raise ValueError("invalid account risk source policy")


def legacy_account_risk_source_policy():
    """Preserve the prior non-CTP branch without proving its source capability."""
    return AccountRiskSourcePolicy(requires_native_account_binding=False)


__all__ = ("AccountRiskSourcePolicy", "legacy_account_risk_source_policy")
