"""Neutral managed-paper fill fact contract (``managed_paper_fill.v2``).

Iteration 60, step 60.06. This field set used to be hard-coded separately in
the execution producer's recovery check, two SDK modules and Backtrader. It
now has one owner: every consumer imports it from here, so the copies cannot
drift apart.

* ``MANAGED_PAPER_FILL_V2_FIELDS`` is the exact public wire shape of one
  verified paper fill fact.
* ``MANAGED_PAPER_FILL_V2_RECEIPT_FIELDS`` is the producer's receipt
  projection, which additionally carries ``event_created_at_ns``; the SDK
  strips that field before publishing the wire fact.
"""

from __future__ import annotations

__all__ = [
    "MANAGED_PAPER_FILL_V2_COMMISSION_MODEL_ID",
    "MANAGED_PAPER_FILL_V2_COMMISSION_MODEL_VERSION",
    "MANAGED_PAPER_FILL_V2_FIELDS",
    "MANAGED_PAPER_FILL_V2_RECEIPT_FIELDS",
    "MANAGED_PAPER_FILL_V2_SCHEMA",
    "MANAGED_PAPER_FILL_V2_TIME_SOURCE",
]

MANAGED_PAPER_FILL_V2_SCHEMA = "managed_paper_fill.v2"
MANAGED_PAPER_FILL_V2_TIME_SOURCE = "MANAGED_PAPER_MATCH"
MANAGED_PAPER_FILL_V2_COMMISSION_MODEL_ID = "quote_notional_rate"
MANAGED_PAPER_FILL_V2_COMMISSION_MODEL_VERSION = "1"

MANAGED_PAPER_FILL_V2_FIELDS = frozenset(
    {
        "schema",
        "time_source",
        "fill_id",
        "match_time_ns",
        "quantity",
        "price",
        "commission",
        "commission_currency",
        "commission_model_id",
        "commission_model_version",
        "event_id",
        "event_sequence",
        "journal_generation",
        "scope_key",
        "intent_id",
        "intent_fingerprint",
        "account_ref",
        "strategy_ref",
        "quote_source_ref",
        "quote_generation",
        "quote_cursor",
        "quote_instrument",
        "receipt_sha256",
    }
)
MANAGED_PAPER_FILL_V2_RECEIPT_FIELDS = MANAGED_PAPER_FILL_V2_FIELDS | frozenset(
    {"event_created_at_ns"}
)
