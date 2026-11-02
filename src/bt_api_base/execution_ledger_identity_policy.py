"""Provider declaration for the existing SDK execution-ledger identity family.

The declaration selects a format and fencing path; it does not authenticate an
account, establish credential validity, or grant a trading capability.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionLedgerIdentityPolicy:
    credential_bound: bool

    def __post_init__(self):
        if type(self.credential_bound) is not bool:
            raise ValueError("invalid execution-ledger identity policy")


def credential_bound_ledger_policy():
    """Select the historical credential-bound identity and fencing family."""
    return ExecutionLedgerIdentityPolicy(credential_bound=True)


def legacy_ledger_policy():
    """Select the historical non-credential-bound identity family."""
    return ExecutionLedgerIdentityPolicy(credential_bound=False)


__all__ = ("ExecutionLedgerIdentityPolicy", "credential_bound_ledger_policy", "legacy_ledger_policy")
