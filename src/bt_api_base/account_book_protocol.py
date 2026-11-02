"""Neutral snapshots for one explicitly selected strategy account book.

The projection records service-owned journal coverage and, when present, a
separate persisted financial cut. It does not grant write authority and does
not turn a persisted cut into provider-live account state.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any


_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z", re.ASCII)
_DECIMAL = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z", re.ASCII)
_REMOTE_CODES = frozenset(
    {"INVALID_REQUEST", "SCOPE_DENIED", "UNAVAILABLE", "REPLY_TOO_LARGE", "UNKNOWN_OPERATION"}
)
_WATERMARK_KINDS = frozenset({"execution_outbox", "account_facts", "account_activity"})
_MAX_ROWS = 4096
_MAX_TEXT = 256
_MAX_DECIMAL_TEXT = 128


class AccountBookProjectionError(RuntimeError):
    """Finite diagnostic for an invalid or unavailable account-book reply."""

    def __init__(self, code: str) -> None:
        if type(code) is not str or not _CODE.fullmatch(code):
            code = "ACCOUNT_BOOK_PROJECTION_INVALID"
        self.code = code
        super().__init__(code)


def _text(value: object, code: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > _MAX_TEXT
        or value != value.strip()
        or not value.isprintable()
    ):
        raise AccountBookProjectionError(code)
    return value


def _optional_text(value: object, code: str) -> str | None:
    return None if value is None else _text(value, code)


def _mapping(value: object, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise AccountBookProjectionError(code)
    return value


def _rows(value: object, code: str) -> tuple[Mapping[str, Any], ...]:
    if type(value) not in (tuple, list) or len(value) > _MAX_ROWS:
        raise AccountBookProjectionError(code)
    result = tuple(_mapping(row, code) for row in value)
    return result


def _decimal(value: object, code: str) -> Decimal:
    if type(value) is not str or len(value) > _MAX_DECIMAL_TEXT or not _DECIMAL.fullmatch(value):
        raise AccountBookProjectionError(code)
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError):
        raise AccountBookProjectionError(code) from None
    if not parsed.is_finite():
        raise AccountBookProjectionError(code)
    return parsed


def _counter(value: object, code: str, *, allow_zero: bool) -> int:
    if type(value) is not int or value < (0 if allow_zero else 1):
        raise AccountBookProjectionError(code)
    return value


def _decimal_map(value: object, code: str) -> Mapping[str, Decimal]:
    raw = _mapping(value, code)
    if len(raw) > _MAX_ROWS:
        raise AccountBookProjectionError(code)
    parsed: dict[str, Decimal] = {}
    for key, item in raw.items():
        if type(item) is not Decimal or not item.is_finite():
            raise AccountBookProjectionError(code)
        parsed[_text(key, code)] = item
    return MappingProxyType(parsed)


@dataclass(frozen=True)
class StrategyPositionCost:
    """One persisted owner position and its explicitly sourced cost basis."""

    quantity: Decimal
    cost_basis: Decimal | None
    cost_currency: str | None
    product_model: str
    metadata_version: str
    average_cost: Decimal | None

    def __post_init__(self) -> None:
        if type(self.quantity) is not Decimal or not self.quantity.is_finite() or self.quantity < 0:
            raise ValueError("quantity must be a finite nonnegative Decimal")
        if self.cost_basis is not None and (
            type(self.cost_basis) is not Decimal
            or not self.cost_basis.is_finite()
            or self.cost_basis < 0
        ):
            raise ValueError("cost_basis must be a finite nonnegative Decimal or None")
        if self.average_cost is not None and (
            type(self.average_cost) is not Decimal
            or not self.average_cost.is_finite()
            or self.average_cost < 0
        ):
            raise ValueError("average_cost must be a finite nonnegative Decimal or None")
        if self.cost_basis is None:
            if self.cost_currency is not None or self.average_cost is not None:
                raise ValueError("unknown cost basis cannot carry derived cost facts")
        else:
            _text(self.cost_currency, "INVALID_COST_BASIS_PROJECTION")
            if (self.quantity == 0 and self.cost_basis != 0) or (
                self.quantity > 0 and self.cost_basis == 0
            ):
                raise ValueError("cost basis does not match quantity")
        _text(self.product_model, "INVALID_COST_BASIS_PROJECTION")
        _text(self.metadata_version, "INVALID_COST_BASIS_PROJECTION")


@dataclass(frozen=True)
class StrategyFinancialWatermark:
    """One immutable source cursor from the independent financial cut."""

    source_kind: str
    source_ref: str
    generation: str
    cursor: int
    as_of_ns: int

    def __post_init__(self) -> None:
        for name in ("source_kind", "source_ref", "generation"):
            _text(getattr(self, name), "INVALID_FINANCIAL_CUT")
        _counter(self.cursor, "INVALID_FINANCIAL_CUT", allow_zero=True)
        _counter(self.as_of_ns, "INVALID_FINANCIAL_CUT", allow_zero=False)


@dataclass(frozen=True)
class StrategyFinancialLedgerCut:
    """The persisted financial ledger cut, separate from account-book coverage."""

    account_key: str
    owner_directory_revision: str
    captured_at_ns: int
    watermarks: tuple[StrategyFinancialWatermark, ...]

    def __post_init__(self) -> None:
        _text(self.account_key, "INVALID_FINANCIAL_CUT")
        _text(self.owner_directory_revision, "INVALID_FINANCIAL_CUT")
        captured = _counter(self.captured_at_ns, "INVALID_FINANCIAL_CUT", allow_zero=False)
        if type(self.watermarks) is not tuple or len(self.watermarks) != 3:
            raise ValueError("financial cut requires the three declared source watermarks")
        if any(type(item) is not StrategyFinancialWatermark for item in self.watermarks):
            raise TypeError("invalid financial watermark")
        kinds = tuple(item.source_kind for item in self.watermarks)
        if frozenset(kinds) != _WATERMARK_KINDS or len(set(kinds)) != 3:
            raise ValueError("financial cut source set is incomplete or duplicated")
        if any(item.as_of_ns > captured for item in self.watermarks):
            raise ValueError("financial cut predates a source watermark")


@dataclass(frozen=True)
class StrategyAccountBookSnapshot:
    """One strategy's durable position book and optional separate financial cut."""

    strategy_ref: str
    account_ref: str
    scope_directory_revision: str
    journal_generation: str
    baseline_execution_cursor: int
    current_execution_cursor: int
    positions: Mapping[str, Decimal]
    fees_since_baseline: Mapping[str, Decimal]
    cash_by_currency: Mapping[str, Decimal] = field(default_factory=dict)
    position_costs: Mapping[str, StrategyPositionCost] = field(default_factory=dict)
    cumulative_fees_by_currency: Mapping[str, Decimal] = field(default_factory=dict)
    financial_available: bool = False
    cost_basis_complete: bool = False
    financial_error_code: str = "STRATEGY_FINANCIAL_UNAVAILABLE"
    financial_source: str | None = None
    financial_freshness: str | None = None
    financial_cut_relationship: str | None = None
    financial_ledger_cut: StrategyFinancialLedgerCut | None = None
    account_key: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "strategy_ref",
            "account_ref",
            "scope_directory_revision",
            "journal_generation",
        ):
            _text(getattr(self, name), "INVALID_COVERAGE")
        baseline = _counter(self.baseline_execution_cursor, "INVALID_COVERAGE", allow_zero=True)
        current = _counter(self.current_execution_cursor, "INVALID_COVERAGE", allow_zero=True)
        if baseline > current:
            raise ValueError("execution cursor coverage is reversed")
        for name in (
            "positions",
            "fees_since_baseline",
            "cash_by_currency",
            "cumulative_fees_by_currency",
        ):
            object.__setattr__(self, name, _decimal_map(getattr(self, name), "INVALID_PROJECTION"))
        costs = _mapping(self.position_costs, "INVALID_COST_BASIS_PROJECTION")
        if len(costs) > _MAX_ROWS:
            raise AccountBookProjectionError("INVALID_COST_BASIS_PROJECTION")
        parsed_costs: dict[str, StrategyPositionCost] = {}
        for instrument, item in costs.items():
            if type(item) is not StrategyPositionCost:
                raise TypeError("position cost values must be StrategyPositionCost")
            parsed_costs[_text(instrument, "INVALID_COST_BASIS_PROJECTION")] = item
        object.__setattr__(self, "position_costs", MappingProxyType(parsed_costs))
        if type(self.financial_available) is not bool or type(self.cost_basis_complete) is not bool:
            raise TypeError("financial availability flags must be exact bool values")
        if type(self.financial_error_code) is not str or (
            self.financial_error_code and not _CODE.fullmatch(self.financial_error_code)
        ):
            raise ValueError("financial_error_code must be a finite code")
        _optional_text(self.financial_source, "INVALID_FINANCIAL_PROJECTION")
        _optional_text(self.financial_freshness, "INVALID_FINANCIAL_PROJECTION")
        _optional_text(self.financial_cut_relationship, "INVALID_FINANCIAL_PROJECTION")
        _optional_text(self.account_key, "INVALID_COVERAGE")
        if self.financial_available:
            if (
                self.financial_error_code
                or self.financial_source is None
                or self.financial_freshness is None
                or self.financial_cut_relationship is None
                or type(self.financial_ledger_cut) is not StrategyFinancialLedgerCut
            ):
                raise ValueError("available financial projection requires its complete cut")
        elif (
            self.cost_basis_complete
            or self.financial_error_code == ""
            or self.financial_source is not None
            or self.financial_freshness is not None
            or self.financial_cut_relationship is not None
            or self.financial_ledger_cut is not None
            or self.cash_by_currency
            or self.position_costs
            or self.cumulative_fees_by_currency
        ):
            raise ValueError("unavailable financial projection cannot carry financial rows")


def parse_strategy_account_book_reply(
    reply: object, *, strategy_ref: str, account_ref: str
) -> StrategyAccountBookSnapshot:
    """Validate one successful strategy-view RPC reply and project its result.

    ``strategy_ref`` and ``account_ref`` are expected values from the caller's
    already selected SDK route. The response must independently identify the
    same strategy; the account reference is retained as route context and is
    not inferred from the financial ledger's distinct ``account_key``.
    """

    _text(strategy_ref, "INVALID_SCOPE")
    _text(account_ref, "INVALID_SCOPE")
    envelope = _mapping(reply, "INVALID_REPLY")
    if set(envelope) != {"ok", "code", "result"}:
        raise AccountBookProjectionError("INVALID_REPLY")
    if envelope.get("ok") is not True:
        if envelope.get("ok") is not False or envelope.get("code") == "OK":
            raise AccountBookProjectionError("INVALID_REPLY")
        code = envelope.get("code")
        raise AccountBookProjectionError(
            code if type(code) is str and code in _REMOTE_CODES else "REMOTE_QUERY_REJECTED"
        )
    if envelope.get("code") != "OK":
        raise AccountBookProjectionError("INVALID_REPLY")
    result = _mapping(envelope.get("result"), "INVALID_REPLY")
    if (
        result.get("view") != "OWNER_BOOK"
        or result.get("owner_kind") != "STRATEGY"
        or result.get("owner_ref") != strategy_ref
    ):
        raise AccountBookProjectionError("OWNER_BINDING_MISMATCH")

    coverage = _mapping(result.get("coverage"), "INVALID_COVERAGE")
    if coverage.get("complete") is not True:
        raise AccountBookProjectionError("STRATEGY_BOOK_COVERAGE_INCOMPLETE")
    revision = _text(coverage.get("scope_directory_revision"), "INVALID_COVERAGE")
    generation = _text(coverage.get("journal_generation"), "INVALID_COVERAGE")
    baseline = _counter(
        coverage.get("baseline_execution_cursor"), "INVALID_COVERAGE", allow_zero=True
    )
    current = _counter(
        coverage.get("current_execution_cursor"), "INVALID_COVERAGE", allow_zero=True
    )
    if baseline > current:
        raise AccountBookProjectionError("INVALID_COVERAGE")
    account_key = _optional_text(coverage.get("account_key"), "INVALID_COVERAGE")

    books = _rows(result.get("books"), "OWNER_BOOK_AMBIGUOUS")
    if len(books) != 1:
        raise AccountBookProjectionError("OWNER_BOOK_AMBIGUOUS")
    book = books[0]
    if book.get("owner_kind") != "STRATEGY" or book.get("owner_ref") != strategy_ref:
        raise AccountBookProjectionError("OWNER_BINDING_MISMATCH")

    positions: dict[str, Decimal] = {}
    for row in _rows(book.get("current_positions"), "INVALID_POSITION_PROJECTION"):
        instrument = _text(row.get("instrument"), "INVALID_POSITION_PROJECTION")
        if instrument in positions:
            raise AccountBookProjectionError("DUPLICATE_POSITION")
        positions[instrument] = _decimal(row.get("net_quantity"), "INVALID_POSITION_PROJECTION")

    fees: dict[str, Decimal] = {}
    for row in _rows(book.get("fees_since_baseline"), "INVALID_FEE_PROJECTION"):
        currency = _text(row.get("currency"), "INVALID_FEE_PROJECTION")
        if currency in fees:
            raise AccountBookProjectionError("DUPLICATE_FEE")
        fees[currency] = _decimal(row.get("amount"), "INVALID_FEE_PROJECTION")

    financial = _financial_projection(
        result,
        strategy_ref=strategy_ref,
        expected_account_key=account_key,
        positions=positions,
        journal_generation=generation,
        current_execution_cursor=current,
    )
    return StrategyAccountBookSnapshot(
        strategy_ref=strategy_ref,
        account_ref=account_ref,
        scope_directory_revision=revision,
        journal_generation=generation,
        baseline_execution_cursor=baseline,
        current_execution_cursor=current,
        positions=positions,
        fees_since_baseline=fees,
        account_key=account_key,
        **financial,
    )


def _financial_projection(
    result: Mapping[str, Any],
    *,
    strategy_ref: str,
    expected_account_key: str | None,
    positions: Mapping[str, Decimal],
    journal_generation: str,
    current_execution_cursor: int,
) -> dict[str, Any]:
    raw = result.get("financial")
    if raw is None:
        return _unavailable_financial("STRATEGY_FINANCIAL_UNAVAILABLE")
    financial = _mapping(raw, "INVALID_FINANCIAL_PROJECTION")
    available = financial.get("available")
    if available is False:
        code = financial.get("code")
        if type(code) is not str or not _CODE.fullmatch(code):
            code = "STRATEGY_FINANCIAL_UNAVAILABLE"
        return _unavailable_financial(code)
    if available is not True:
        raise AccountBookProjectionError("INVALID_FINANCIAL_PROJECTION")
    if (
        financial.get("source") != "PERSISTED_EXECUTION_FINANCIAL_PROJECTION"
        or financial.get("freshness") != "PERSISTED_CUT_NOT_LIVE_SOURCE_VERIFIED"
        or financial.get("cut_relationship") != "INDEPENDENT_OF_LEGACY_ACCOUNT_BOOK_CUT"
        or financial.get("view") != "OWNER_BOOK"
        or financial.get("owner_kind") != "STRATEGY"
        or financial.get("owner_ref") != strategy_ref
        or "state" in financial
        or "unallocated" in financial
    ):
        raise AccountBookProjectionError("OWNER_BINDING_MISMATCH")
    if financial.get("complete") is not True:
        return _unavailable_financial("STRATEGY_FINANCIAL_INCOMPLETE")
    if expected_account_key is None:
        return _unavailable_financial("STRATEGY_FINANCIAL_ACCOUNT_KEY_UNAVAILABLE")

    raw_cut = financial.get("ledger_cut")
    if not isinstance(raw_cut, Mapping):
        return _unavailable_financial("STRATEGY_FINANCIAL_CUT_UNAVAILABLE")
    try:
        cut = _parse_financial_cut(raw_cut)
    except (AccountBookProjectionError, TypeError, ValueError):
        return _unavailable_financial("STRATEGY_FINANCIAL_CUT_UNAVAILABLE")
    if cut.account_key != expected_account_key:
        return _unavailable_financial("STRATEGY_FINANCIAL_ACCOUNT_MISMATCH")
    execution = next(item for item in cut.watermarks if item.source_kind == "execution_outbox")
    if execution.generation != journal_generation or execution.cursor != current_execution_cursor:
        return _unavailable_financial("STRATEGY_FINANCIAL_CUT_MISMATCH")

    books = _rows(financial.get("books"), "INVALID_FINANCIAL_PROJECTION")
    if len(books) != 1:
        raise AccountBookProjectionError("OWNER_BOOK_AMBIGUOUS")
    owner_book = books[0]
    if owner_book.get("ledger_cut") != dict(raw_cut):
        return _unavailable_financial("STRATEGY_FINANCIAL_CUT_MISMATCH")
    owner = _mapping(owner_book.get("owner"), "OWNER_BINDING_MISMATCH")
    if owner.get("kind") != "STRATEGY" or owner.get("owner_ref") != strategy_ref:
        raise AccountBookProjectionError("OWNER_BINDING_MISMATCH")

    cash = _currency_amounts(
        owner_book.get("cash"),
        "INVALID_CASH_PROJECTION",
        "DUPLICATE_CASH_CURRENCY",
    )
    cumulative_fees = _currency_amounts(
        owner_book.get("cumulative_fees"),
        "INVALID_FEE_PROJECTION",
        "DUPLICATE_CUMULATIVE_FEE",
    )
    cost_basis_complete = owner_book.get("cost_basis_complete")
    if type(cost_basis_complete) is not bool:
        raise AccountBookProjectionError("INVALID_COST_BASIS_PROJECTION")
    position_costs: dict[str, StrategyPositionCost] = {}
    for row in _rows(owner_book.get("positions"), "INVALID_COST_BASIS_PROJECTION"):
        instrument = _text(row.get("instrument"), "INVALID_COST_BASIS_PROJECTION")
        if instrument in position_costs:
            raise AccountBookProjectionError("DUPLICATE_POSITION_COST")
        quantity = _decimal(row.get("quantity"), "INVALID_COST_BASIS_PROJECTION")
        if quantity < 0:
            raise AccountBookProjectionError("INVALID_COST_BASIS_PROJECTION")
        raw_basis = row.get("cost_basis")
        basis = None if raw_basis is None else _decimal(raw_basis, "INVALID_COST_BASIS_PROJECTION")
        currency = _optional_text(row.get("cost_currency"), "INVALID_COST_BASIS_PROJECTION")
        if (basis is None) != (currency is None):
            raise AccountBookProjectionError("INVALID_COST_BASIS_PROJECTION")
        if basis is not None and (
            basis < 0 or (quantity == 0 and basis != 0) or (quantity > 0 and basis == 0)
        ):
            raise AccountBookProjectionError("INVALID_COST_BASIS_PROJECTION")
        if row.get("cost_method") != "AVERAGE_COST":
            raise AccountBookProjectionError("UNSUPPORTED_COST_METHOD")
        product_model = _text(row.get("product_model"), "INVALID_COST_BASIS_PROJECTION")
        if product_model != "SPOT":
            raise AccountBookProjectionError("UNSUPPORTED_PRODUCT_MODEL")
        metadata_version = _text(row.get("metadata_version"), "INVALID_COST_BASIS_PROJECTION")
        average_cost = None
        if cost_basis_complete and basis is not None:
            average_cost = basis / quantity if quantity else Decimal("0")
        position_costs[instrument] = StrategyPositionCost(
            quantity=quantity,
            cost_basis=basis,
            cost_currency=currency,
            product_model=product_model,
            metadata_version=metadata_version,
            average_cost=average_cost,
        )

    if cost_basis_complete and any(
        quantity != 0
        and (
            (cost := position_costs.get(instrument)) is None
            or cost.quantity != quantity
            or cost.cost_basis is None
        )
        for instrument, quantity in positions.items()
    ):
        cost_basis_complete = False
    return {
        "cash_by_currency": cash,
        "position_costs": position_costs,
        "cumulative_fees_by_currency": cumulative_fees,
        "financial_available": True,
        "cost_basis_complete": cost_basis_complete,
        "financial_error_code": "",
        "financial_source": "PERSISTED_EXECUTION_FINANCIAL_PROJECTION",
        "financial_freshness": "PERSISTED_CUT_NOT_LIVE_SOURCE_VERIFIED",
        "financial_cut_relationship": "INDEPENDENT_OF_LEGACY_ACCOUNT_BOOK_CUT",
        "financial_ledger_cut": cut,
    }


def _parse_financial_cut(raw: Mapping[str, Any]) -> StrategyFinancialLedgerCut:
    if set(raw) != {"account_key", "owner_directory_revision", "captured_at_ns", "watermarks"}:
        raise AccountBookProjectionError("INVALID_FINANCIAL_CUT")
    watermarks: list[StrategyFinancialWatermark] = []
    for row in _rows(raw.get("watermarks"), "INVALID_FINANCIAL_CUT"):
        if set(row) != {"source_kind", "source_ref", "generation", "cursor", "as_of_ns"}:
            raise AccountBookProjectionError("INVALID_FINANCIAL_CUT")
        watermarks.append(
            StrategyFinancialWatermark(
                source_kind=_text(row.get("source_kind"), "INVALID_FINANCIAL_CUT"),
                source_ref=_text(row.get("source_ref"), "INVALID_FINANCIAL_CUT"),
                generation=_text(row.get("generation"), "INVALID_FINANCIAL_CUT"),
                cursor=_counter(row.get("cursor"), "INVALID_FINANCIAL_CUT", allow_zero=True),
                as_of_ns=_counter(row.get("as_of_ns"), "INVALID_FINANCIAL_CUT", allow_zero=False),
            )
        )
    return StrategyFinancialLedgerCut(
        account_key=_text(raw.get("account_key"), "INVALID_FINANCIAL_CUT"),
        owner_directory_revision=_text(
            raw.get("owner_directory_revision"), "INVALID_FINANCIAL_CUT"
        ),
        captured_at_ns=_counter(
            raw.get("captured_at_ns"), "INVALID_FINANCIAL_CUT", allow_zero=False
        ),
        watermarks=tuple(watermarks),
    )


def _currency_amounts(
    value: object, row_error: str, duplicate_error: str
) -> dict[str, Decimal]:
    result: dict[str, Decimal] = {}
    for row in _rows(value, row_error):
        currency = _text(row.get("currency"), row_error)
        if currency in result:
            raise AccountBookProjectionError(duplicate_error)
        result[currency] = _decimal(row.get("amount"), row_error)
    return result


def _unavailable_financial(code: str) -> dict[str, Any]:
    return {
        "cash_by_currency": {},
        "position_costs": {},
        "cumulative_fees_by_currency": {},
        "financial_available": False,
        "cost_basis_complete": False,
        "financial_error_code": code,
        "financial_source": None,
        "financial_freshness": None,
        "financial_cut_relationship": None,
        "financial_ledger_cut": None,
    }


__all__ = [
    "AccountBookProjectionError",
    "StrategyAccountBookSnapshot",
    "StrategyFinancialLedgerCut",
    "StrategyFinancialWatermark",
    "StrategyPositionCost",
    "parse_strategy_account_book_reply",
]
