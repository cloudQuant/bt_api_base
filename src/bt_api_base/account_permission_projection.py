"""Project explicitly supplied account permissions into neutral fields.

Field names and source provenance are selected by the caller. These helpers
do not establish that a snapshot is current or grant any account authority.
"""


def project_account_permissions(row, *, pick, permission_fields, can_trade_fields):
    """Project explicit permission facts while retaining unknown as unknown."""
    raw = pick(row, *permission_fields)
    permissions = None
    permission_allows = None
    if isinstance(raw, str):
        raw = [part.strip().lower() for part in raw.split(",") if part.strip()]
    if isinstance(raw, (list, tuple)) and raw:
        values = {str(value).strip().lower() for value in raw}
        known = {"read_only", "trade", "withdraw"}
        if values <= known:
            permissions = sorted(values)
            permission_allows = "trade" in values
    explicit = pick(row, *can_trade_fields)
    explicit = (
        True
        if explicit is True or explicit == "true"
        else False
        if explicit is False or explicit == "false"
        else None
    )
    can_trade = (
        False
        if explicit is False or permission_allows is False
        else True
        if explicit is True or permission_allows is True
        else None
    )
    return {"can_trade": can_trade, "trading_permissions": permissions}


def combine_account_permission_projections(source, *, project):
    """Combine projected rows without turning absent permissions into access."""
    snapshots = [project(row) for row in source]
    values = [row["can_trade"] for row in snapshots]
    can_trade = False if False in values else True if True in values else None
    permissions = sorted(
        {permission for row in snapshots for permission in (row["trading_permissions"] or ())}
    )
    return {"can_trade": can_trade, "trading_permissions": permissions or None}


__all__ = ("project_account_permissions", "combine_account_permission_projections")
