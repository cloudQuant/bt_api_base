"""Provider-neutral contracts for explicitly requested futures EOD rankings.

Daily ranking sources are historical observations and do not share the live
clock/freshness contract of ``futures_market_protocol``.  Provider adapters
own exchange-specific download, parsing, and instrument mapping.  This module
contains only the normalized request, catalog binding, ranked rows, coverage,
and provider port consumed by SDK facades and strategy projections.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Optional, Protocol, Tuple, runtime_checkable

from bt_api_base.futures_market_protocol import (
    FuturesCatalogDisposition,
    FuturesCatalogRecord,
    FuturesContractKind,
    FuturesProductKey,
    FuturesQuantityUnit,
    FuturesVolumeSemantics,
)
from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.query_protocol import QueryCompleteness
from bt_api_base.service_protocol import MAX_REFERENCE_BYTES

MAX_FUTURES_EOD_PRODUCTS = 2_048
MAX_FUTURES_EOD_RECORDS = 100_000
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_DECIMAL_RE = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z", re.ASCII)
_TOKEN_RE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z", re.ASCII)


class FuturesEodRankingCompleteness(str, Enum):
    """Completeness of one explicit EOD ranking request."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


def _text(value: Any, field: str) -> str:
    if type(value) is not str:
        raise TypeError("{} must be text".format(field))
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError("{} must be valid UTF-8".format(field)) from exc
    if (
        not encoded
        or len(encoded) > MAX_REFERENCE_BYTES
        or value != value.strip()
        or not value.isprintable()
    ):
        raise ValueError("{} must be bounded printable UTF-8".format(field))
    return value


def _optional_text(value: Any, field: str) -> Optional[str]:
    return None if value is None else _text(value, field)


def _digest(value: Any, field: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise ValueError("{} must be lowercase SHA-256 hex".format(field))
    return value


def _day(value: Any, field: str) -> date:
    if type(value) is not date:
        raise TypeError("{} must be a date".format(field))
    return value


def _utc(value: Any, field: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("{} must be timezone-aware".format(field))
    if value.utcoffset() != timedelta(0):
        raise ValueError("{} must use UTC".format(field))
    return value


def _optional_utc(value: Any, field: str) -> Optional[datetime]:
    return None if value is None else _utc(value, field)


def _tokens(values: Any, field: str) -> Tuple[str, ...]:
    if type(values) not in (tuple, list):
        raise TypeError("{} must be a tuple or list".format(field))
    result = tuple(values)
    if any(type(item) is not str or _TOKEN_RE.fullmatch(item) is None for item in result):
        raise ValueError("{} must contain neutral lower-case tokens".format(field))
    if len(set(result)) != len(result):
        raise ValueError("{} must not contain duplicates".format(field))
    return tuple(sorted(result))


def _products(values: Any, field: str) -> Tuple[FuturesProductKey, ...]:
    if type(values) not in (tuple, list):
        raise TypeError("{} must be a tuple or list".format(field))
    result = tuple(values)
    if not result or len(result) > MAX_FUTURES_EOD_PRODUCTS:
        raise ValueError("{} must contain a bounded non-empty product set".format(field))
    if any(type(item) is not FuturesProductKey for item in result):
        raise TypeError("{} must contain FuturesProductKey records".format(field))
    keys = tuple((item.venue, item.product_id) for item in result)
    if len(set(keys)) != len(keys):
        raise ValueError("{} contains duplicate product keys".format(field))
    return tuple(sorted(result, key=lambda item: (item.venue, item.product_id)))


def _instruments(values: Any, field: str) -> Tuple[MarketInstrumentKey, ...]:
    if type(values) not in (tuple, list):
        raise TypeError("{} must be a tuple or list".format(field))
    result = tuple(values)
    if any(type(item) is not MarketInstrumentKey for item in result):
        raise TypeError("{} must contain MarketInstrumentKey records".format(field))
    def key(item: MarketInstrumentKey) -> tuple[str, ...]:
        return (
            item.provider,
            item.venue,
            item.environment,
            item.product_type,
            item.instrument_id,
            item.native_symbol,
        )
    keys = tuple(key(item) for item in result)
    if len(set(keys)) != len(keys):
        raise ValueError("{} contains duplicate instrument identities".format(field))
    return tuple(sorted(result, key=key))


def _blockers(values: Any, field: str) -> Tuple[str, ...]:
    if type(values) not in (tuple, list):
        raise TypeError("{} must be a tuple or list".format(field))
    result = tuple(values)
    if any(type(item) is not str or _TOKEN_RE.fullmatch(item) is None for item in result):
        raise ValueError("{} must contain safe neutral codes".format(field))
    return tuple(sorted(set(result)))


@dataclass(frozen=True)
class FuturesEodRankingRequest:
    """An explicit product set and trading day for public EOD ranking reads."""

    request_ref: str
    trading_day: date
    products: Tuple[FuturesProductKey, ...]

    def __post_init__(self) -> None:
        _text(self.request_ref, "request_ref")
        _day(self.trading_day, "trading_day")
        object.__setattr__(self, "products", _products(self.products, "products"))


@dataclass(frozen=True)
class FuturesEodCatalogScope:
    """Neutral catalog rows bound to one exact SDK market snapshot.

    The public SDK facade constructs this projection only after checking the
    exact market-snapshot lease.  ``catalog_scope_complete`` describes the
    returned catalog family; it does not claim that the provider knows the
    complete product universe. Empty product catalogs require a separate,
    complete ``product_universe`` fact before they can be considered complete.
    """

    market_snapshot_ref: str
    market_source_ref: Optional[str]
    market_generation: Optional[str]
    market_records_digest: str
    environment: str
    venues: Optional[Tuple[str, ...]]
    catalog_products: Optional[Tuple[FuturesProductKey, ...]]
    catalog_request_ref: str
    catalog_snapshot_ref: Optional[str]
    catalog_records_digest: Optional[str]
    catalog_completeness: QueryCompleteness
    catalog_scope_complete: Optional[bool]
    catalog_records: Tuple[FuturesCatalogRecord, ...]
    product_universe_request_ref: Optional[str] = None
    product_universe_snapshot_ref: Optional[str] = None
    product_universe_records_digest: Optional[str] = None
    product_universe_complete: Optional[bool] = None
    product_universe: Optional[Tuple[FuturesProductKey, ...]] = None

    def __post_init__(self) -> None:
        for name in (
            "market_snapshot_ref",
            "catalog_request_ref",
            "environment",
        ):
            _text(getattr(self, name), name)
        for name in (
            "market_source_ref",
            "market_generation",
            "catalog_snapshot_ref",
        ):
            _optional_text(getattr(self, name), name)
        _digest(self.market_records_digest, "market_records_digest")
        if self.catalog_records_digest is not None:
            _digest(self.catalog_records_digest, "catalog_records_digest")
        if self.venues is not None:
            venues = tuple(self.venues)
            if not venues or any(
                type(item) is not str or not item or item != item.strip() for item in venues
            ):
                raise ValueError("venues must contain non-empty exchange IDs")
            normalized_venues = tuple(sorted(item.upper() for item in venues))
            if len(set(normalized_venues)) != len(normalized_venues):
                raise ValueError("venues contains duplicates")
            object.__setattr__(self, "venues", normalized_venues)
        if self.catalog_products is not None:
            object.__setattr__(self, "catalog_products", _products(self.catalog_products, "catalog_products"))
        for name in (
            "product_universe_request_ref",
            "product_universe_snapshot_ref",
        ):
            _optional_text(getattr(self, name), name)
        if self.product_universe_records_digest is not None:
            _digest(self.product_universe_records_digest, "product_universe_records_digest")
        if type(self.catalog_completeness) is not QueryCompleteness:
            raise TypeError("catalog_completeness must be QueryCompleteness")
        if self.catalog_scope_complete is not None and type(self.catalog_scope_complete) is not bool:
            raise TypeError("catalog_scope_complete must be bool or None")
        records = tuple(self.catalog_records)
        if len(records) > MAX_FUTURES_EOD_RECORDS or any(
            type(item) is not FuturesCatalogRecord for item in records
        ):
            raise TypeError("catalog_records must contain bounded FuturesCatalogRecord rows")
        identities = tuple(item.instrument for item in records)
        if len(set(identities)) != len(identities):
            raise ValueError("catalog_records contain duplicate instrument identities")
        if any(item.instrument.environment != self.environment for item in records):
            raise ValueError("catalog_records are outside the bound environment")
        if self.venues is not None and any(item.instrument.venue not in self.venues for item in records):
            raise ValueError("catalog_records are outside the bound venue scope")
        if self.catalog_products is not None and any(
            item.product not in self.catalog_products for item in records
        ):
            raise ValueError("catalog_records are outside the bound product scope")
        object.__setattr__(self, "catalog_records", records)
        if self.product_universe_complete is not None and type(self.product_universe_complete) is not bool:
            raise TypeError("product_universe_complete must be bool or None")
        if self.product_universe is None:
            if self.product_universe_complete is True:
                raise ValueError("complete product universe requires product keys")
        else:
            products = tuple(self.product_universe)
            if any(type(item) is not FuturesProductKey for item in products):
                raise TypeError("product_universe must contain FuturesProductKey records")
            keys = tuple((item.venue, item.product_id) for item in products)
            if len(set(keys)) != len(keys):
                raise ValueError("product_universe contains duplicate keys")
            if len(products) > MAX_FUTURES_EOD_PRODUCTS:
                raise ValueError("product_universe exceeds its bounded size")
            object.__setattr__(
                self,
                "product_universe",
                tuple(sorted(products, key=lambda item: (item.venue, item.product_id))),
            )
            if self.product_universe_complete is not True:
                raise ValueError("product_universe rows require complete scope evidence")
            for name in (
                "product_universe_request_ref",
                "product_universe_snapshot_ref",
            ):
                if getattr(self, name) is None:
                    raise ValueError("complete product universe requires {}".format(name))
            if self.product_universe_records_digest is None:
                raise ValueError("complete product universe requires its digest")
            if any(
                self.venues is not None and item.venue not in self.venues
                for item in self.product_universe
            ):
                raise ValueError("product_universe rows are outside the bound venue scope")
            if any(
                item.product not in self.product_universe for item in self.catalog_records
            ):
                raise ValueError("catalog records are outside the complete product universe")


@dataclass(frozen=True)
class FuturesEodRankingRecord:
    """One EOD metric row mapped to a full neutral instrument identity."""

    instrument: MarketInstrumentKey
    product: FuturesProductKey
    trading_day: date
    open_interest: str
    volume: str
    open_interest_unit: FuturesQuantityUnit
    volume_unit: FuturesQuantityUnit
    volume_semantics: FuturesVolumeSemantics

    def __post_init__(self) -> None:
        if type(self.instrument) is not MarketInstrumentKey:
            raise TypeError("instrument must be MarketInstrumentKey")
        if type(self.product) is not FuturesProductKey:
            raise TypeError("product must be FuturesProductKey")
        if self.instrument.venue != self.product.venue:
            raise ValueError("instrument and product venue must match")
        _day(self.trading_day, "trading_day")
        for name in ("open_interest", "volume"):
            value = getattr(self, name)
            if type(value) is not str or _DECIMAL_RE.fullmatch(value) is None:
                raise ValueError("{} must be a finite non-negative decimal string".format(name))
        if type(self.open_interest_unit) is not FuturesQuantityUnit:
            raise TypeError("open_interest_unit must be FuturesQuantityUnit")
        if type(self.volume_unit) is not FuturesQuantityUnit:
            raise TypeError("volume_unit must be FuturesQuantityUnit")
        if type(self.volume_semantics) is not FuturesVolumeSemantics:
            raise TypeError("volume_semantics must be FuturesVolumeSemantics")


@dataclass(frozen=True)
class FuturesEodSourceCoverage:
    """Bounded provenance and reconciliation facts for one public EOD source."""

    source_ref: str
    venues: Tuple[str, ...]
    snapshot_ref: Optional[str]
    source_digest: Optional[str]
    trading_day: date
    reported_update_at: Optional[datetime]
    retrieved_at: Optional[datetime]
    observed_at: datetime
    source_row_count: int
    ranking_row_count: int
    excluded_row_count: int
    unmatched_row_count: int
    ambiguous_row_count: int
    duplicate_row_count: int
    completeness: FuturesEodRankingCompleteness
    blockers: Tuple[str, ...] = ()
    report_finalized: Optional[bool] = None
    latest_snapshot: Optional[bool] = None

    def __post_init__(self) -> None:
        _text(self.source_ref, "source_ref")
        _optional_text(self.snapshot_ref, "snapshot_ref")
        if self.source_digest is not None:
            _digest(self.source_digest, "source_digest")
        _day(self.trading_day, "trading_day")
        _optional_utc(self.reported_update_at, "reported_update_at")
        _optional_utc(self.retrieved_at, "retrieved_at")
        _utc(self.observed_at, "observed_at")
        if self.completeness is FuturesEodRankingCompleteness.COMPLETE and (
            self.snapshot_ref is None or self.source_digest is None or self.retrieved_at is None
        ):
            raise ValueError("complete source coverage requires an observed response")
        if (self.snapshot_ref is None) != (self.source_digest is None):
            raise ValueError("source snapshot reference and digest must be present together")
        if (
            self.reported_update_at is not None
            and self.retrieved_at is not None
            and self.reported_update_at > self.retrieved_at
        ):
            raise ValueError("reported update time cannot follow retrieval time")
        venues = tuple(self.venues)
        if not venues or any(type(item) is not str or not item or item != item.strip() for item in venues):
            raise ValueError("venues must contain non-empty exchange IDs")
        normalized_venues = tuple(sorted(item.upper() for item in venues))
        if len(set(normalized_venues)) != len(normalized_venues):
            raise ValueError("venues contains duplicates")
        object.__setattr__(self, "venues", normalized_venues)
        for name in (
            "source_row_count",
            "ranking_row_count",
            "excluded_row_count",
            "unmatched_row_count",
            "ambiguous_row_count",
            "duplicate_row_count",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError("{} must be a non-negative int".format(name))
        for name in ("report_finalized", "latest_snapshot"):
            value = getattr(self, name)
            if value is not None and type(value) is not bool:
                raise TypeError("{} must be bool or None".format(name))
        if self.ranking_row_count > self.source_row_count:
            raise ValueError("ranking rows exceed source rows")
        if type(self.completeness) is not FuturesEodRankingCompleteness:
            raise TypeError("completeness must be FuturesEodRankingCompleteness")
        blockers = _blockers(self.blockers, "blockers")
        if self.completeness is FuturesEodRankingCompleteness.COMPLETE and blockers:
            raise ValueError("complete source coverage cannot have blockers")
        if self.completeness is FuturesEodRankingCompleteness.COMPLETE and (
            self.unmatched_row_count
            or self.ambiguous_row_count
            or self.duplicate_row_count
        ):
            raise ValueError("complete source coverage cannot contain unresolved rows")
        if self.completeness in (
            FuturesEodRankingCompleteness.PARTIAL,
            FuturesEodRankingCompleteness.UNAVAILABLE,
            FuturesEodRankingCompleteness.UNKNOWN,
        ) and not blockers:
            raise ValueError("incomplete source coverage requires a blocker")
        object.__setattr__(self, "blockers", blockers)

    @property
    def complete(self) -> bool:
        return self.completeness is FuturesEodRankingCompleteness.COMPLETE and not self.blockers


@dataclass(frozen=True)
class FuturesEodProductCoverage:
    """Coverage for one explicitly requested product's catalog/ranking join."""

    product: FuturesProductKey
    expected_instruments: Tuple[MarketInstrumentKey, ...]
    ranking_instruments: Tuple[MarketInstrumentKey, ...]
    missing_instruments: Tuple[MarketInstrumentKey, ...]
    candidate_set_complete: bool
    ranking_values_complete: bool
    unmatched_source_row_count: int
    duplicate_source_row_count: int
    source_refs: Tuple[str, ...]
    blockers: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.product) is not FuturesProductKey:
            raise TypeError("product must be FuturesProductKey")
        for name in ("expected_instruments", "ranking_instruments", "missing_instruments"):
            object.__setattr__(self, name, _instruments(getattr(self, name), name))
        if any(item.venue != self.product.venue for item in self.expected_instruments):
            raise ValueError("expected instruments are outside product venue")
        if any(item.venue != self.product.venue for item in self.ranking_instruments):
            raise ValueError("ranking instruments are outside product venue")
        if any(type(getattr(self, name)) is not bool for name in (
            "candidate_set_complete",
            "ranking_values_complete",
        )):
            raise TypeError("coverage completeness flags must be bool")
        for name in ("unmatched_source_row_count", "duplicate_source_row_count"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError("{} must be a non-negative int".format(name))
        refs = tuple(self.source_refs)
        if any(type(item) is not str for item in refs):
            raise TypeError("source_refs must contain text")
        object.__setattr__(
            self,
            "source_refs",
            tuple(sorted(set(_text(item, "source_ref") for item in refs))),
        )
        if self.ranking_values_complete and not self.source_refs:
            raise ValueError("complete ranking values require at least one source reference")
        object.__setattr__(self, "blockers", _blockers(self.blockers, "blockers"))
        expected = set(self.expected_instruments)
        ranked = set(self.ranking_instruments)
        missing = set(self.missing_instruments)
        if ranked - expected or missing != expected - ranked:
            raise ValueError("product coverage instrument sets do not reconcile")
        if self.ranking_values_complete and (
            missing or self.unmatched_source_row_count or self.duplicate_source_row_count
        ):
            raise ValueError("complete ranking values cannot have missing or ambiguous rows")

    @property
    def complete(self) -> bool:
        return (
            self.candidate_set_complete
            and self.ranking_values_complete
            and not self.blockers
            and not self.missing_instruments
        )


@dataclass(frozen=True)
class FuturesEodRankingSnapshot:
    """Immutable EOD source batch bound to one market catalog snapshot."""

    request: FuturesEodRankingRequest
    catalog: FuturesEodCatalogScope
    requested_at: datetime
    completed_at: datetime
    observed_at: datetime
    sources: Tuple[FuturesEodSourceCoverage, ...]
    product_coverage: Tuple[FuturesEodProductCoverage, ...]
    records: Tuple[FuturesEodRankingRecord, ...]
    records_digest: str
    completeness: FuturesEodRankingCompleteness
    blockers: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.request) is not FuturesEodRankingRequest:
            raise TypeError("request must be FuturesEodRankingRequest")
        if type(self.catalog) is not FuturesEodCatalogScope:
            raise TypeError("catalog must be FuturesEodCatalogScope")
        requested = _utc(self.requested_at, "requested_at")
        completed = _utc(self.completed_at, "completed_at")
        observed = _utc(self.observed_at, "observed_at")
        if completed < requested or observed < completed:
            raise ValueError("EOD snapshot times are not monotonic")
        sources = tuple(self.sources)
        if any(type(item) is not FuturesEodSourceCoverage for item in sources):
            raise TypeError("sources must contain FuturesEodSourceCoverage records")
        if len({(item.source_ref, item.snapshot_ref) for item in sources}) != len(sources):
            raise ValueError("sources contain duplicate references")
        if len({item.source_ref for item in sources}) != len(sources):
            raise ValueError("one snapshot cannot contain multiple versions of a source")
        if any(item.trading_day != self.request.trading_day for item in sources):
            raise ValueError("source coverage does not match request trading day")
        if any(
            self.catalog.venues is not None
            and any(venue not in self.catalog.venues for venue in item.venues)
            for item in sources
        ):
            raise ValueError("source coverage is outside the bound venue scope")
        requested_product_keys = {
            (item.venue, item.product_id) for item in self.request.products
        }
        if any(
            self.catalog.venues is not None
            and item.venue not in self.catalog.venues
            for item in self.request.products
        ):
            raise ValueError("request products are outside the bound venue scope")
        if self.catalog.catalog_products is not None and not requested_product_keys.issubset(
            {(item.venue, item.product_id) for item in self.catalog.catalog_products}
        ):
            raise ValueError("request products are outside the bound product scope")
        if self.catalog.product_universe_complete is True and not requested_product_keys.issubset(
            {(item.venue, item.product_id) for item in self.catalog.product_universe or ()}
        ):
            raise ValueError("request products are outside the complete product universe")
        product_coverage = tuple(self.product_coverage)
        if any(type(item) is not FuturesEodProductCoverage for item in product_coverage):
            raise TypeError("product_coverage must contain FuturesEodProductCoverage records")
        actual_products = tuple(item.product for item in product_coverage)
        if actual_products != self.request.products:
            raise ValueError("product coverage must exactly match request products")
        source_refs = {item.source_ref for item in sources}
        if any(not set(item.source_refs).issubset(source_refs) for item in product_coverage):
            raise ValueError("product coverage references an unknown EOD source")
        records = tuple(self.records)
        if len(records) > MAX_FUTURES_EOD_RECORDS or any(
            type(item) is not FuturesEodRankingRecord for item in records
        ):
            raise TypeError("records must contain bounded FuturesEodRankingRecord rows")
        if any(item.trading_day != self.request.trading_day for item in records):
            raise ValueError("records do not match request trading day")
        identities = tuple(item.instrument for item in records)
        if len(set(identities)) != len(identities):
            raise ValueError("records contain duplicate instrument identities")
        _digest(self.records_digest, "records_digest")
        if type(self.completeness) is not FuturesEodRankingCompleteness:
            raise TypeError("completeness must be FuturesEodRankingCompleteness")
        blockers = _blockers(self.blockers, "blockers")
        product_record_identities = {
            instrument
            for item in product_coverage
            for instrument in item.ranking_instruments
        }
        if set(identities) != product_record_identities:
            raise ValueError("records do not match product ranking coverage")
        catalog_by_instrument = {
            item.instrument: item for item in self.catalog.catalog_records
        }
        product_coverage_by_key = {
            (item.product.venue, item.product.product_id): item
            for item in product_coverage
        }
        for record in records:
            key = (record.product.venue, record.product.product_id)
            catalog_record = catalog_by_instrument.get(record.instrument)
            coverage = product_coverage_by_key.get(key)
            if (
                catalog_record is None
                or catalog_record.product != record.product
                or coverage is None
                or record.instrument not in coverage.ranking_instruments
                or record.instrument not in coverage.expected_instruments
            ):
                raise ValueError("ranking record is not bound to its exact catalog product")
        for coverage in product_coverage:
            catalog_candidates = tuple(
                item.instrument
                for item in self.catalog.catalog_records
                if item.product == coverage.product
                and item.disposition is not FuturesCatalogDisposition.EXCLUDED
                and item.contract_kind in (FuturesContractKind.FUTURE, FuturesContractKind.UNKNOWN)
            )
            if set(catalog_candidates) != set(coverage.expected_instruments):
                raise ValueError("product expected instruments do not match catalog candidates")
        for source in sources:
            source_products = tuple(
                item
                for item in product_coverage
                if source.source_ref in item.source_refs
            )
            if sum(
                sum(1 for record in records if record.product == item.product)
                for item in source_products
            ) != source.ranking_row_count:
                raise ValueError("source ranking-row count does not match product coverage")
            if sum(item.unmatched_source_row_count for item in source_products) != (
                source.unmatched_row_count
            ):
                raise ValueError("source unmatched-row count does not match product coverage")
            if sum(item.duplicate_source_row_count for item in source_products) != (
                source.duplicate_row_count + source.ambiguous_row_count
            ):
                raise ValueError("source duplicate-row count does not match product coverage")
        if self.records_digest != futures_eod_records_digest(records):
            raise ValueError("records_digest does not bind the neutral ranking records")
        if self.completeness is FuturesEodRankingCompleteness.COMPLETE and (
            blockers
            or self.catalog.catalog_completeness is not QueryCompleteness.COMPLETE
            or self.catalog.catalog_scope_complete is not True
            or any(not item.complete for item in sources)
            or any(not item.complete for item in product_coverage)
        ):
            raise ValueError("complete snapshot has incomplete source or product coverage")
        if self.completeness in (
            FuturesEodRankingCompleteness.PARTIAL,
            FuturesEodRankingCompleteness.UNAVAILABLE,
            FuturesEodRankingCompleteness.UNKNOWN,
        ) and not blockers:
            raise ValueError("incomplete snapshot requires a blocker")
        object.__setattr__(self, "sources", sources)
        object.__setattr__(self, "product_coverage", product_coverage)
        object.__setattr__(self, "records", records)
        object.__setattr__(self, "blockers", blockers)

    @property
    def complete(self) -> bool:
        return (
            self.completeness is FuturesEodRankingCompleteness.COMPLETE
            and not self.blockers
            and all(item.complete for item in self.sources)
            and all(item.complete for item in self.product_coverage)
        )


@runtime_checkable
class FuturesEodRankingPort(Protocol):
    """Provider port for explicit, read-only EOD ranking collection."""

    def collect(
        self,
        request: FuturesEodRankingRequest,
        catalog: FuturesEodCatalogScope,
        *,
        deadline: datetime,
    ) -> FuturesEodRankingSnapshot:
        """Return only neutral rows and coverage; never infer missing products."""


@dataclass(frozen=True)
class SelectedFuturesEodRankingRoute:
    """Trusted, provider-neutral route selection for EOD source composition."""

    exchange_name: str

    def __post_init__(self) -> None:
        _text(self.exchange_name, "exchange_name")
        if len(self.exchange_name.encode("utf-8")) > 256:
            raise ValueError("exchange_name exceeds its bounded route size")


class FuturesEodRankingProviderFactory(Protocol):
    """Construct one EOD provider port for a preselected SDK route."""

    def __call__(
        self,
        route: SelectedFuturesEodRankingRoute,
        /,
    ) -> FuturesEodRankingPort:
        ...


@runtime_checkable
class FuturesEodRankingProviderRegistryPort(Protocol):
    """Provider-owned registration contract for the parent SDK router."""

    def register(
        self,
        exchange_name: str,
        factory: FuturesEodRankingProviderFactory,
        /,
    ) -> None:
        ...


def futures_eod_records_digest(records: Tuple[FuturesEodRankingRecord, ...]) -> str:
    """Compute a deterministic digest over neutral EOD records."""

    rows = []
    for item in records:
        if type(item) is not FuturesEodRankingRecord:
            raise TypeError("records must contain FuturesEodRankingRecord rows")
        rows.append(
            {
                "provider": item.instrument.provider,
                "venue": item.instrument.venue,
                "environment": item.instrument.environment,
                "product_type": item.instrument.product_type,
                "instrument_id": item.instrument.instrument_id,
                "native_symbol": item.instrument.native_symbol,
                "product_id": item.product.product_id,
                "trading_day": item.trading_day.isoformat(),
                "open_interest": item.open_interest,
                "volume": item.volume,
                "open_interest_unit": item.open_interest_unit.value,
                "volume_unit": item.volume_unit.value,
                "volume_semantics": item.volume_semantics.value,
            }
        )
    rows.sort(
        key=lambda row: (
            row["venue"],
            row["product_id"],
            row["provider"],
            row["environment"],
            row["product_type"],
            row["instrument_id"],
            row["native_symbol"],
        )
    )
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "FuturesEodCatalogScope",
    "FuturesEodProductCoverage",
    "FuturesEodRankingCompleteness",
    "FuturesEodRankingPort",
    "FuturesEodRankingProviderFactory",
    "FuturesEodRankingProviderRegistryPort",
    "FuturesEodRankingRecord",
    "FuturesEodRankingRequest",
    "FuturesEodRankingSnapshot",
    "FuturesEodSourceCoverage",
    "MAX_FUTURES_EOD_PRODUCTS",
    "MAX_FUTURES_EOD_RECORDS",
    "SelectedFuturesEodRankingRoute",
    "futures_eod_records_digest",
]
