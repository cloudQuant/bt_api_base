"""Validation of explicit direct write error classifications."""

from dataclasses import FrozenInstanceError

import pytest

from bt_api_base.direct_write_protocol import DirectWriteErrorPolicy


def test_empty_and_finite_policies_are_immutable():
    policy = DirectWriteErrorPolicy(frozenset({"timeout"}), frozenset())
    assert policy.place_unknown_codes == frozenset({"timeout"})
    with pytest.raises(FrozenInstanceError):
        policy.cancel_unknown_codes = frozenset({"cancel"})


@pytest.mark.parametrize(
    "value",
    [
        "timeout",
        {"timeout"},
        ["timeout"],
        frozenset({""}),
        frozenset({" timeout"}),
        frozenset({"x" * 129}),
        frozenset({1}),
        frozenset(str(i) for i in range(129)),
    ],
)
@pytest.mark.parametrize("field", ["place", "cancel"])
def test_invalid_policy_fields_are_rejected(field, value):
    kwargs = {"place_unknown_codes": frozenset(), "cancel_unknown_codes": frozenset()}
    kwargs[field + "_unknown_codes"] = value
    with pytest.raises(ValueError):
        DirectWriteErrorPolicy(**kwargs)
