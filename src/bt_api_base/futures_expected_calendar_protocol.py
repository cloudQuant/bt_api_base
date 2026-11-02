"""Neutral contracts for provider-owned expected futures calendars.

This protocol carries the rule-derived calendar and its declared limits. It does
not claim an observed exchange calendar or authenticate the request's market
snapshot inputs; SDK composition must bind those inputs to its own snapshot
facade before treating them as current provider facts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
import hashlib
import json
import re
from typing import Any, ClassVar, Protocol, runtime_checkable

from bt_api_base.futures_market_protocol import FuturesProductKey
from bt_api_base.market_protocol import MarketInstrumentKey


_MAX_PRODUCTS = 2_000
_MAX_VENUES = 16
_MAX_DAYS = 10_000
_MAX_PRODUCT_DAYS = 100_000
_MAX_WINDOWS = 300_000
_MAX_SOURCES = 16
_MAX_URLS = 32
_MAX_LIMITATIONS = 32
_MAX_BLOCKERS = 256
_TEXT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,255}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UTC_ZERO = timedelta(0)


class FuturesExpectedCalendarStatus(str, Enum):
    """Coverage state of one exact expected-calendar request scope."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class FuturesExpectedCalendarError(ValueError):
    """Finite, value-free validation error for expected-calendar contracts."""

    _CODES: ClassVar[frozenset[str]] = frozenset(
        {
            "FUTURES_EXPECTED_CALENDAR_REQUEST_INVALID",
            "FUTURES_EXPECTED_CALENDAR_RESULT_INVALID",
            "FUTURES_EXPECTED_CALENDAR_PROVIDER_ROUTE_INVALID",
            "FUTURES_EXPECTED_CALENDAR_PROVIDER_UNAVAILABLE",
        }
    )

    def __init__(self, code: str) -> None:
        self.code = code if type(code) is str and code in self._CODES else (
            "FUTURES_EXPECTED_CALENDAR_REQUEST_INVALID"
        )
        super().__init__(self.code)


def _text(value: Any, name: str) -> str:
    if type(value) is not str or _TEXT.fullmatch(value) is None:
        raise ValueError("{} must be bounded canonical text".format(name))
    return value


def _plain_text(value: Any, name: str) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or not value.isprintable()
        or len(value.encode("utf-8", errors="strict")) > 1024
    ):
        raise ValueError("{} must be bounded printable text".format(name))
    return value


def _sequence(value: Any, name: str, limit: int) -> tuple[Any, ...]:
    if type(value) not in (tuple, list) or len(value) > limit:
        raise ValueError("{} must be a bounded tuple or list".format(name))
    return tuple(value)


def _day(value: Any, name: str) -> date:
    if type(value) is not date:
        raise ValueError("{} must be a date".format(name))
    return value


def _utc(value: Any, name: str) -> datetime:
    if (
        type(value) is not datetime
        or value.tzinfo is None
        or value.utcoffset() != _UTC_ZERO
    ):
        raise ValueError("{} must be an aware UTC datetime".format(name))
    return value


def _digest(value: Any, name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ValueError("{} must be lowercase SHA-256 hex".format(name))
    return value


def _date_text(value: date) -> str:
    return value.isoformat()


@dataclass(frozen=True)
class FuturesExpectedTradingDay:
    """A caller-selected current trading day, not provider calendar evidence."""

    venue: str
    trading_day: date

    def __post_init__(self) -> None:
        _text(self.venue, "venue")
        _day(self.trading_day, "trading_day")

    def to_dict(self) -> dict[str, str]:
        return {"venue": self.venue, "trading_day": _date_text(self.trading_day)}


@dataclass(frozen=True)
class FuturesProductLastTradingDay:
    """Selected-contract expiry overlay supplied from a separately validated catalog."""

    instrument: MarketInstrumentKey
    product: FuturesProductKey
    last_trading_day: date | None

    def __post_init__(self) -> None:
        if type(self.instrument) is not MarketInstrumentKey:
            raise TypeError("instrument must be a MarketInstrumentKey")
        if type(self.product) is not FuturesProductKey:
            raise TypeError("product must be a FuturesProductKey")
        if self.instrument.venue != self.product.venue:
            raise ValueError("instrument and product venues must match")
        if self.last_trading_day is not None:
            _day(self.last_trading_day, "last_trading_day")

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument": self.instrument.to_dict(),
            "product": self.product.to_dict(),
            "last_trading_day": (
                _date_text(self.last_trading_day) if self.last_trading_day is not None else None
            ),
        }


@dataclass(frozen=True)
class FuturesExpectedCalendarRequest:
    """Exact product/day scope for provider-owned expected-rule projection.

    Holiday ranges, exchange closures, product session rules and source
    evidence are intentionally absent: callers choose scope, while the provider
    owns those facts and reports limitations explicitly.
    """

    products: tuple[FuturesProductKey, ...]
    current_trading_days: tuple[FuturesExpectedTradingDay, ...]
    as_of_utc: datetime
    selected_contract_last_trading_days: tuple[FuturesProductLastTradingDay, ...] = ()

    def __post_init__(self) -> None:
        products = _sequence(self.products, "products", _MAX_PRODUCTS)
        days = _sequence(self.current_trading_days, "current_trading_days", _MAX_VENUES)
        overlays = _sequence(
            self.selected_contract_last_trading_days,
            "selected_contract_last_trading_days",
            _MAX_PRODUCTS,
        )
        if not products or any(type(item) is not FuturesProductKey for item in products):
            raise ValueError("products must contain FuturesProductKey values")
        if len(set(products)) != len(products):
            raise ValueError("products must be unique")
        products = tuple(sorted(products, key=lambda item: (item.venue, item.product_id)))
        venues = tuple(sorted({item.venue for item in products}))
        if not days or any(type(item) is not FuturesExpectedTradingDay for item in days):
            raise ValueError("current_trading_days must contain explicit venue/day records")
        if tuple(item.venue for item in days) != tuple(sorted({item.venue for item in days})):
            raise ValueError("current_trading_days must have one sorted row per venue")
        if tuple(item.venue for item in days) != venues:
            raise ValueError("current_trading_days must exactly cover requested product venues")
        if any(type(item) is not FuturesProductLastTradingDay for item in overlays):
            raise ValueError("last-trading-day overlays have an invalid type")
        if any(item.product not in products for item in overlays):
            raise ValueError("last-trading-day overlay lies outside requested products")
        if len({item.instrument for item in overlays}) != len(overlays):
            raise ValueError("last-trading-day overlays must have unique instruments")
        _utc(self.as_of_utc, "as_of_utc")
        object.__setattr__(self, "products", products)
        object.__setattr__(self, "current_trading_days", tuple(days))
        object.__setattr__(self, "selected_contract_last_trading_days", tuple(overlays))

    @property
    def venues(self) -> tuple[str, ...]:
        return tuple(sorted({item.venue for item in self.products}))

    def to_dict(self) -> dict[str, Any]:
        return {
            "products": [item.to_dict() for item in self.products],
            "current_trading_days": [item.to_dict() for item in self.current_trading_days],
            "as_of_utc": self.as_of_utc.isoformat().replace("+00:00", "Z"),
            "selected_contract_last_trading_days": [
                item.to_dict() for item in self.selected_contract_last_trading_days
            ],
        }

    @property
    def scope_digest(self) -> str:
        payload = json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class FuturesExpectedSessionWindow:
    """One normalized continuous interval, represented in UTC."""

    trading_day: date
    session_date: date
    start_at_utc: datetime
    end_at_utc: datetime
    session_id: str

    def __post_init__(self) -> None:
        _day(self.trading_day, "trading_day")
        _day(self.session_date, "session_date")
        start = _utc(self.start_at_utc, "start_at_utc")
        end = _utc(self.end_at_utc, "end_at_utc")
        if start >= end:
            raise ValueError("session window must be non-empty")
        _text(self.session_id, "session_id")


@dataclass(frozen=True)
class FuturesExpectedProductDay:
    """Normalized expected session set for one product and trading day."""

    product: FuturesProductKey
    trading_day: date
    source_id: str
    windows: tuple[FuturesExpectedSessionWindow, ...]
    closed_reason: str | None = None

    def __post_init__(self) -> None:
        if type(self.product) is not FuturesProductKey:
            raise TypeError("product must be a FuturesProductKey")
        _day(self.trading_day, "trading_day")
        _text(self.source_id, "source_id")
        windows = _sequence(self.windows, "windows", 32)
        if any(type(item) is not FuturesExpectedSessionWindow for item in windows):
            raise ValueError("windows must contain expected session window records")
        ordered = tuple(sorted(windows, key=lambda item: item.start_at_utc))
        if windows != ordered or any(
            current.start_at_utc < previous.end_at_utc
            for previous, current in zip(windows, windows[1:])
        ):
            raise ValueError("windows must be ordered and non-overlapping")
        if any(item.trading_day != self.trading_day for item in windows):
            raise ValueError("window trading_day differs from product-day trading_day")
        if windows:
            if self.closed_reason is not None:
                raise ValueError("open product-day cannot carry closed_reason")
        elif self.closed_reason is None:
            raise ValueError("empty windows require an explicit closed_reason")
        else:
            _text(self.closed_reason, "closed_reason")
        object.__setattr__(self, "windows", windows)


@dataclass(frozen=True)
class FuturesExpectedVenueCalendar:
    """Explicit expected trading-day set over one bounded venue interval."""

    venue: str
    coverage_start: date
    coverage_through: date
    trading_days: tuple[date, ...]
    source_id: str
    complete: bool

    def __post_init__(self) -> None:
        _text(self.venue, "venue")
        start = _day(self.coverage_start, "coverage_start")
        through = _day(self.coverage_through, "coverage_through")
        if through < start:
            raise ValueError("coverage_through precedes coverage_start")
        days = _sequence(self.trading_days, "trading_days", _MAX_DAYS)
        if any(type(item) is not date for item in days):
            raise ValueError("trading_days must contain dates")
        if tuple(sorted(set(days))) != days or any(item < start or item > through for item in days):
            raise ValueError("trading_days are outside or unordered within coverage")
        _text(self.source_id, "source_id")
        if type(self.complete) is not bool:
            raise TypeError("complete must be bool")
        object.__setattr__(self, "trading_days", tuple(days))


@dataclass(frozen=True)
class FuturesExpectedCalendarNotice:
    """Neutral public-notice provenance, including its byte-capture limit."""

    issuer_name: str
    notice_ref: str
    issued_on: date
    source_urls: tuple[str, ...]
    provenance: str
    byte_identity_limit: str

    def __post_init__(self) -> None:
        _plain_text(self.issuer_name, "issuer_name")
        _plain_text(self.notice_ref, "notice_ref")
        _day(self.issued_on, "issued_on")
        urls = _sequence(self.source_urls, "notice source_urls", _MAX_URLS)
        if not urls or any(
            type(item) is not str or not item.startswith("https://") for item in urls
        ):
            raise ValueError("notice source_urls must contain HTTPS references")
        if len(set(urls)) != len(urls):
            raise ValueError("notice source_urls must be unique")
        _plain_text(self.provenance, "provenance")
        _plain_text(self.byte_identity_limit, "byte_identity_limit")
        object.__setattr__(self, "source_urls", tuple(sorted(urls)))


@dataclass(frozen=True)
class FuturesExpectedCalendarEvidence:
    """Provider-owned public rule references and their declared limitations."""

    venue: str
    source_id: str
    source_urls: tuple[str, ...]
    version: str
    available_at_utc: datetime
    retrieved_at_utc: datetime
    rules_manifest_sha256: str
    limitations: tuple[str, ...]
    notices: tuple[FuturesExpectedCalendarNotice, ...] = ()
    evidence_kind: str = "expected_rule_derived"

    def __post_init__(self) -> None:
        _text(self.venue, "venue")
        _text(self.source_id, "source_id")
        urls = _sequence(self.source_urls, "source_urls", _MAX_URLS)
        if not urls or any(
            type(item) is not str or not item.startswith("https://") for item in urls
        ):
            raise ValueError("source_urls must contain HTTPS references")
        if len(set(urls)) != len(urls):
            raise ValueError("source_urls must be unique")
        _text(self.version, "version")
        available = _utc(self.available_at_utc, "available_at_utc")
        retrieved = _utc(self.retrieved_at_utc, "retrieved_at_utc")
        if retrieved < available:
            raise ValueError("retrieved_at_utc precedes available_at_utc")
        _digest(self.rules_manifest_sha256, "rules_manifest_sha256")
        limitations = _sequence(self.limitations, "limitations", _MAX_LIMITATIONS)
        if any(type(item) is not str or not item or item != item.strip() for item in limitations):
            raise ValueError("limitations must contain non-empty text")
        if len(set(limitations)) != len(limitations):
            raise ValueError("limitations must be unique")
        notices = _sequence(self.notices, "notices", _MAX_SOURCES)
        if any(type(item) is not FuturesExpectedCalendarNotice for item in notices):
            raise ValueError("notices must contain neutral notice records")
        if any(not set(item.source_urls).issubset(set(urls)) for item in notices):
            raise ValueError("notice URLs must be present in source_urls")
        if self.evidence_kind != "expected_rule_derived":
            raise ValueError("evidence_kind must remain expected_rule_derived")
        object.__setattr__(self, "source_urls", tuple(sorted(urls)))
        object.__setattr__(self, "limitations", tuple(limitations))
        object.__setattr__(self, "notices", tuple(notices))


@dataclass(frozen=True)
class FuturesExpectedProductDayKey:
    """One absent product/day scope member in a partial result."""

    product: FuturesProductKey
    trading_day: date

    def __post_init__(self) -> None:
        if type(self.product) is not FuturesProductKey:
            raise TypeError("product must be a FuturesProductKey")
        _day(self.trading_day, "trading_day")


@dataclass(frozen=True)
class FuturesExpectedCalendarSnapshot:
    """Provider result bound to one exact neutral request and rule manifest."""

    request: FuturesExpectedCalendarRequest
    status: FuturesExpectedCalendarStatus
    venue_calendars: tuple[FuturesExpectedVenueCalendar, ...]
    product_days: tuple[FuturesExpectedProductDay, ...]
    sources: tuple[FuturesExpectedCalendarEvidence, ...]
    fifth_future_trading_days: tuple[FuturesExpectedTradingDay, ...]
    rules_manifest_sha256: str
    blockers: tuple[str, ...] = ()
    missing_product_days: tuple[FuturesExpectedProductDayKey, ...] = ()

    def __post_init__(self) -> None:
        if type(self.request) is not FuturesExpectedCalendarRequest:
            raise TypeError("request must be a FuturesExpectedCalendarRequest")
        if type(self.status) is not FuturesExpectedCalendarStatus:
            raise TypeError("status must be FuturesExpectedCalendarStatus")
        calendars = _sequence(self.venue_calendars, "venue_calendars", _MAX_VENUES)
        rows = _sequence(self.product_days, "product_days", _MAX_PRODUCT_DAYS)
        sources = _sequence(self.sources, "sources", _MAX_SOURCES)
        fifth = _sequence(self.fifth_future_trading_days, "fifth_future_trading_days", _MAX_VENUES)
        blockers = _sequence(self.blockers, "blockers", _MAX_BLOCKERS)
        missing = _sequence(self.missing_product_days, "missing_product_days", _MAX_PRODUCT_DAYS)
        if any(type(item) is not FuturesExpectedVenueCalendar for item in calendars):
            raise ValueError("venue_calendars contains an invalid row")
        if any(type(item) is not FuturesExpectedProductDay for item in rows):
            raise ValueError("product_days contains an invalid row")
        if any(type(item) is not FuturesExpectedCalendarEvidence for item in sources):
            raise ValueError("sources contains an invalid row")
        if any(type(item) is not FuturesExpectedTradingDay for item in fifth):
            raise ValueError("fifth_future_trading_days contains an invalid row")
        if any(type(item) is not FuturesExpectedProductDayKey for item in missing):
            raise ValueError("missing_product_days contains an invalid row")
        if any(type(item) is not str or _TEXT.fullmatch(item) is None for item in blockers):
            raise ValueError("blockers must be finite code strings")
        if len(set(blockers)) != len(blockers):
            raise ValueError("blockers must be unique")
        if len({item.venue for item in calendars}) != len(calendars):
            raise ValueError("venue_calendars must be unique by venue")
        if len({item.venue for item in sources}) != len(sources):
            raise ValueError("sources must be unique by venue")
        if len({(item.venue, item.trading_day) for item in fifth}) != len(fifth):
            raise ValueError("fifth future trading days must be unique by venue")
        if len({(item.product, item.trading_day) for item in rows}) != len(rows):
            raise ValueError("product_days must be unique by product/day")
        if len({(item.product, item.trading_day) for item in missing}) != len(missing):
            raise ValueError("missing_product_days must be unique")
        _digest(self.rules_manifest_sha256, "rules_manifest_sha256")
        if any(item.rules_manifest_sha256 != self.rules_manifest_sha256 for item in sources):
            raise ValueError("source evidence manifest digest mismatch")
        calendar_venues = {item.venue for item in calendars}
        requested_venues = set(self.request.venues)
        if not calendar_venues.issubset(requested_venues):
            raise ValueError("calendar lies outside request venues")
        source_venues = {item.venue for item in sources}
        if source_venues != calendar_venues:
            raise ValueError("calendar and source venue coverage mismatch")
        if any(item.product.venue not in calendar_venues for item in rows):
            raise ValueError("product-day row lies outside returned calendar venues")
        if any(item.product not in self.request.products for item in rows):
            raise ValueError("product-day row lies outside requested products")
        if any(item.trading_day not in next(
            calendar.trading_days for calendar in calendars if calendar.venue == item.product.venue
        ) for item in rows):
            raise ValueError("product-day row lies outside venue trading days")
        if any(item.product not in self.request.products for item in missing):
            raise ValueError("missing product-day key lies outside requested products")
        if self.status is FuturesExpectedCalendarStatus.COMPLETE:
            if blockers or missing or not self._scope_is_complete(calendars, rows, sources, fifth):
                raise ValueError("complete result does not cover the exact request scope")
        elif not blockers:
            raise ValueError("partial or unavailable result requires blockers")
        if self.status is FuturesExpectedCalendarStatus.UNAVAILABLE and (calendars or rows or sources):
            raise ValueError("unavailable result must not expose partial schedule rows")
        object.__setattr__(self, "venue_calendars", tuple(calendars))
        object.__setattr__(self, "product_days", tuple(rows))
        object.__setattr__(self, "sources", tuple(sources))
        object.__setattr__(self, "fifth_future_trading_days", tuple(fifth))
        object.__setattr__(self, "blockers", tuple(blockers))
        object.__setattr__(self, "missing_product_days", tuple(missing))

    def _scope_is_complete(
        self,
        calendars: tuple[FuturesExpectedVenueCalendar, ...],
        rows: tuple[FuturesExpectedProductDay, ...],
        sources: tuple[FuturesExpectedCalendarEvidence, ...],
        fifth: tuple[FuturesExpectedTradingDay, ...],
    ) -> bool:
        if {item.venue for item in calendars} != set(self.request.venues):
            return False
        if {item.venue for item in sources} != set(self.request.venues):
            return False
        if {item.venue for item in fifth} != set(self.request.venues):
            return False
        calendar_by_venue = {item.venue: item for item in calendars}
        current_by_venue = {item.venue: item.trading_day for item in self.request.current_trading_days}
        fifth_by_venue = {item.venue: item.trading_day for item in fifth}
        if any(not item.complete for item in calendars):
            return False
        for venue, calendar in calendar_by_venue.items():
            if current_by_venue[venue] not in calendar.trading_days:
                return False
            index = calendar.trading_days.index(current_by_venue[venue])
            if index + 5 >= len(calendar.trading_days):
                return False
            if calendar.trading_days[index + 5] != fifth_by_venue[venue]:
                return False
        expected = {
            (product, day)
            for product in self.request.products
            for day in calendar_by_venue[product.venue].trading_days
        }
        actual = {(item.product, item.trading_day) for item in rows}
        return expected == actual

    @property
    def scope_complete(self) -> bool:
        return self._scope_is_complete(
            self.venue_calendars,
            self.product_days,
            self.sources,
            self.fifth_future_trading_days,
        ) and not self.missing_product_days

    @property
    def complete(self) -> bool:
        return self.status is FuturesExpectedCalendarStatus.COMPLETE and self.scope_complete

    @property
    def evidence_mode(self) -> str:
        return "expected_rule_derived"


@dataclass(frozen=True)
class SelectedFuturesExpectedCalendarRoute:
    """Exact SDK route passed opaquely to one provider factory."""

    exchange_name: str
    client: object = field(repr=False, compare=False)
    environment: str | None = None

    def __post_init__(self) -> None:
        _text(self.exchange_name, "exchange_name")
        if self.client is None:
            raise FuturesExpectedCalendarError("FUTURES_EXPECTED_CALENDAR_PROVIDER_ROUTE_INVALID")
        if self.environment is not None:
            _text(self.environment, "environment")


@runtime_checkable
class FuturesExpectedCalendarPort(Protocol):
    """Neutral SDK facade for rule-derived expected calendars."""

    def build(self, request: FuturesExpectedCalendarRequest) -> FuturesExpectedCalendarSnapshot:
        """Build only the provider-owned rules for the exact request scope."""

    def expected_trading_days(self, venue: str, year: int) -> tuple[date, ...]:
        """Return a full-year date set only when that year is explicitly supported."""

    def validate(self, snapshot: FuturesExpectedCalendarSnapshot) -> bool:
        """Return exact True only for this facade's exact issued snapshot object."""


class FuturesExpectedCalendarProviderFactory(Protocol):
    def __call__(
        self, route: SelectedFuturesExpectedCalendarRoute
    ) -> FuturesExpectedCalendarPort:
        """Create a provider-owned calendar port for one selected route."""


@runtime_checkable
class FuturesExpectedCalendarProviderRegistryPort(Protocol):
    def register(
        self, exchange_name: str, factory: FuturesExpectedCalendarProviderFactory
    ) -> None:
        """Register one provider-owned factory for an exact SDK route key."""


__all__ = [
    "FuturesExpectedCalendarError",
    "FuturesExpectedCalendarEvidence",
    "FuturesExpectedCalendarNotice",
    "FuturesExpectedCalendarPort",
    "FuturesExpectedCalendarProviderFactory",
    "FuturesExpectedCalendarProviderRegistryPort",
    "FuturesExpectedCalendarRequest",
    "FuturesExpectedCalendarSnapshot",
    "FuturesExpectedCalendarStatus",
    "FuturesExpectedProductDayKey",
    "FuturesExpectedProductDay",
    "FuturesExpectedSessionWindow",
    "FuturesExpectedTradingDay",
    "FuturesExpectedVenueCalendar",
    "FuturesProductLastTradingDay",
    "SelectedFuturesExpectedCalendarRoute",
]
