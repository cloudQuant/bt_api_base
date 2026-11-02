"""Neutral declarations for provider-owned execution configuration fields.

These declarations describe configuration shape only; they do not establish
account identity, credential validity, provider connectivity, or authority.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExecutionConfigurationPolicy:
    credential_aliases: tuple[tuple[str, tuple[str, ...]], ...]
    require_environment: bool
    api_regions: tuple[str, ...] = ()
    production_only_api_regions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.require_environment) is not bool or type(self.credential_aliases) is not tuple:
            raise ValueError("execution configuration policy is invalid")
        seen = set()
        for entry in self.credential_aliases:
            if type(entry) is not tuple or len(entry) != 2:
                raise ValueError("execution configuration policy is invalid")
            name, aliases = entry
            if (
                type(name) is not str
                or not name
                or name in seen
                or type(aliases) is not tuple
                or not aliases
                or any(type(alias) is not str or not alias for alias in aliases)
            ):
                raise ValueError("execution configuration policy is invalid")
            seen.add(name)
        if seen and not {"public", "secret"}.issubset(seen):
            raise ValueError("execution configuration policy is invalid")
        for regions in (self.api_regions, self.production_only_api_regions):
            if (
                type(regions) is not tuple
                or any(type(region) is not str or not region for region in regions)
                or len(set(regions)) != len(regions)
            ):
                raise ValueError("execution configuration policy is invalid")
        if not set(self.production_only_api_regions).issubset(self.api_regions):
            raise ValueError("execution configuration policy is invalid")


def legacy_execution_configuration_policy(exchange_name: str) -> ExecutionConfigurationPolicy:
    """Preserve the former no-special-policy behavior for an explicit route."""
    return ExecutionConfigurationPolicy(credential_aliases=(), require_environment=False)


__all__ = ("ExecutionConfigurationPolicy", "legacy_execution_configuration_policy")
