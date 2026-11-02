"""Neutral normalized order observations and their finite source projection.

These data shapes do not authenticate a source or grant execution authority.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any


_DATACLASS_SLOT_OPTIONS = {"slots": True} if sys.version_info >= (3, 10) else {}


@dataclass(frozen=True, **_DATACLASS_SLOT_OPTIONS)
class NormalizationProvenance:
    """Finite source facts carried alongside normalized order observations.

    Normalized records intentionally fill useful API defaults from the
    request.  This object keeps a separate projection of fields present in the
    provider response so a safety-sensitive caller can distinguish those
    values from normalization fallbacks.  It does not retain the provider's
    arbitrary response body.
    """

    schema: str
    operation: str
    source_fields: tuple[str, ...]
    source_values: tuple[tuple[str, Any], ...]
    envelope_fields: tuple[str, ...]
    envelope_values: tuple[tuple[str, Any], ...]
    source_sha256: str

    def to_dict(self) -> dict[str, Any]:
        """Return a detached, bounded representation for service evidence."""

        return {
            "schema": self.schema,
            "operation": self.operation,
            "source_fields": list(self.source_fields),
            "source_values": dict(self.source_values),
            "envelope_fields": list(self.envelope_fields),
            "envelope_values": dict(self.envelope_values),
            "source_sha256": self.source_sha256,
        }


class NormalizedRecord(dict):
    """A dict-compatible normalized record with optional source provenance."""

    def __init__(
        self,
        value=(),
        *,
        provenance: NormalizationProvenance | None = None,
        source_row_count: int | None = None,
        source_alignment_valid: bool = False,
        collection_provenance: NormalizationProvenance | None = None,
    ):
        super().__init__(value)
        self.normalization_provenance = provenance
        self.source_row_count = source_row_count
        self.source_alignment_valid = source_alignment_valid
        self.collection_provenance = collection_provenance


class NormalizedRecords(list):
    """A list-compatible normalized result with per-row source provenance."""

    def __init__(
        self,
        values=(),
        *,
        provenance: NormalizationProvenance | None = None,
        row_provenance: tuple[NormalizationProvenance | None, ...] = (),
        source_alignment_valid: bool = False,
    ):
        super().__init__(values)
        self.normalization_provenance = provenance
        self.row_provenance = row_provenance
        self.source_alignment_valid = source_alignment_valid


__all__ = ("NormalizationProvenance", "NormalizedRecord", "NormalizedRecords")
