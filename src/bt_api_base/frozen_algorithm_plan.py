"""Canonical frozen algorithm plan identity; no execution authority."""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal

_MAX_INT = 2**63 - 1
_MAX_SLOTS = 4096
_MAX_SNAPSHOT_BYTES = 1024 * 1024
_MAX_CONFIG_NODES = 100_000

class FrozenAlgorithmPlanError(ValueError):
    """Invalid bounded frozen plan."""


def _invalid():
    raise FrozenAlgorithmPlanError('invalid algorithm plan')


def _text(value, field):
    if (type(value) is not str or not value or value != value.strip() or not value.isprintable()
            or len(value.encode('utf-8', 'strict')) > 256):
        raise FrozenAlgorithmPlanError('invalid ' + field)
    return value


def _integer(value: object, *, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= _MAX_INT:
        _invalid()
    return value


def _json_value(value: object) -> None:
    # Count every occurrence, including shared subtrees, before serializing.
    # This both bounds expansion cost and rejects cycles without expanding them.
    nodes = 0
    encoded_bytes = 0
    active: set[int] = set()

    def charge(byte_count: int, node_count: int = 1) -> None:
        nonlocal nodes, encoded_bytes
        nodes += node_count
        encoded_bytes += byte_count
        if nodes > _MAX_CONFIG_NODES or encoded_bytes > _MAX_SNAPSHOT_BYTES:
            _invalid()

    def visit(item: object, depth: int) -> None:
        if depth > 8:
            _invalid()
        if item is None:
            charge(4)
        elif type(item) is bool:
            charge(4 if item else 5)
        elif type(item) is int:
            _integer(item)
            charge(len(str(item)))
        elif type(item) is str:
            if len(item) > 256:
                _invalid()
            charge(len(json.dumps(item, ensure_ascii=True)))
        elif type(item) in (list, dict):
            if (type(item) is list and len(item) > _MAX_SLOTS) or (type(item) is dict and len(item) > 64):
                _invalid()
            identity = id(item)
            if identity in active:
                _invalid()
            charge(2 + max(0, len(item) - 1))  # Brackets/braces and commas.
            active.add(identity)
            try:
                if type(item) is list:
                    for entry in item:
                        visit(entry, depth + 1)
                else:
                    for key, entry in item.items():
                        if type(key) is not str or len(key) > 64:
                            _invalid()
                        charge(len(json.dumps(key, ensure_ascii=True)) + 1)  # Key and colon.
                        visit(entry, depth + 1)
            finally:
                active.remove(identity)
        else:
            _invalid()

    visit(value, 0)


def _encode(value: dict[str, object]) -> str:
    _json_value(value)
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    if len(text) > _MAX_SNAPSHOT_BYTES:
        _invalid()
    return text


def algorithm_plan_digest(plan):
    """Hash a bounded v1 envelope as sorted, ASCII, compact JSON bytes."""
    if (type(plan) is not dict or set(plan) != {'schema_version', 'plan_version', 'build_id', 'schedule'}
            or type(plan['schema_version']) is not int or plan['schema_version'] != 1):
        raise FrozenAlgorithmPlanError('invalid algorithm plan')
    _text(plan['plan_version'], 'plan_version')
    _text(plan['build_id'], 'build_id')
    if type(plan['schedule']) is not dict:
        raise FrozenAlgorithmPlanError('invalid algorithm plan')
    try:
        encoded = _encode(plan).encode('ascii')
    except (FrozenAlgorithmPlanError, TypeError, ValueError, UnicodeError) as error:
        raise FrozenAlgorithmPlanError('invalid algorithm plan') from error
    return hashlib.sha256(encoded).hexdigest()


def check_frozen_algorithm_plan(plan, spec):
    """Check persisted self-consistency without loading a current algorithm."""
    try:
        digest = algorithm_plan_digest(plan)
        schedule = plan['schedule']
        if (set(schedule) != {'class', 'version', 'binding', 'params'}
                or type(schedule['class']) is not str or not schedule['class']
                or type(schedule['version']) is not int or schedule['version'] < 1
                or type(schedule['params']) is not dict or type(schedule['binding']) is not dict
                or set(schedule['binding']) != {'deadline_ns', 'quantity_step', 'parent_limit',
                                                'price_step', 'retry_limit'}
                or type(schedule['binding']['deadline_ns']) is not int
                or schedule['binding']['deadline_ns'] != spec['expires_at_ns']
                or type(schedule['binding']['parent_limit']) is not str
                or Decimal(schedule['binding']['parent_limit']) != Decimal(spec['limit_price'])
                or plan['plan_version'] != spec['plan_version'] or digest != spec['plan_digest']):
            raise ValueError
    except (KeyError, TypeError, ValueError, ArithmeticError, FrozenAlgorithmPlanError) as error:
        raise FrozenAlgorithmPlanError('invalid frozen algorithm plan') from error
    return json.loads(_encode(plan))

