"""Signed synthetic source cuts for registered financial admission contracts."""

from copy import deepcopy
from datetime import timedelta

from app.models.composite_attribution import AttributionSourceBundle
from app.models.composite_authority import authority_digest
from tests.composite_attribution_helpers import seal

SOURCE_REFUSAL_CASES = (
    ("missing-member", "MISSING_POPULATION_COVERAGE"),
    ("missing-member-group", "MEMBER_GROUP_UNIVERSE_INCOMPLETE"),
    ("missing-pooled-group", "SOURCE_UNIVERSE_INCOMPLETE"),
    ("missing-benchmark-group", "UNSUPPORTED_OFF_BENCHMARK_GROUP"),
    ("omitted-components", "SOURCE_UNIVERSE_INCOMPLETE"),
    ("page-gap", "SOURCE_PAGE_INCOMPLETE"),
    ("portfolio-zero", "UNSUPPORTED_ZERO_OR_SIGNED_WEIGHT"),
    ("benchmark-zero", "UNSUPPORTED_ZERO_OR_SIGNED_WEIGHT"),
    ("portfolio-short", "UNSUPPORTED_ZERO_OR_SIGNED_WEIGHT"),
    ("benchmark-short", "UNSUPPORTED_ZERO_OR_SIGNED_WEIGHT"),
    ("member-group-short", "UNSUPPORTED_ZERO_OR_SIGNED_WEIGHT"),
    ("derivative", "UNSUPPORTED_DERIVATIVE_CONVENTION"),
    ("currency", "SOURCE_SCOPE_CONFLICT"),
    ("fee-view", "SOURCE_SCOPE_CONFLICT"),
    ("date", "SOURCE_SCOPE_CONFLICT"),
    ("policy-currency", "METHOD_POLICY_CONFLICT"),
    ("policy-window", "METHOD_POLICY_UNAVAILABLE"),
    ("missing-member-return-wire", "SOURCE_WIRE_CONFLICT"),
    ("missing-group-return-wire", "SOURCE_WIRE_CONFLICT"),
    ("missing-benchmark-return-wire", "SOURCE_WIRE_CONFLICT"),
    ("pooled-return-conflict", "SOURCE_ECONOMICS_CONFLICT"),
)


def refused_source_cut(bundle, case):
    """Keep the authority and wire digests valid; isolate the financial defect."""
    if case.endswith("-return-wire"):
        return _missing_observed_wire(bundle, case)
    changes = _scope_changes(bundle) | _economic_changes(bundle)
    if case in {"omitted-components", "page-gap"}:
        pin_change = {"omitted_component_count": 1} if case == "omitted-components" else {"expected_page_count": 2}
        changes[case] = {"source_pins": (bundle.source_pins[0].model_copy(update=pin_change), *bundle.source_pins[1:])}
    # Validate the source port DTO too: these are representable source defects,
    # rather than malformed Python objects created by model_copy.
    changed = AttributionSourceBundle.model_validate(bundle.model_copy(update=changes[case]).model_dump(mode="python"))
    return seal(changed)[0]


def _scope_changes(bundle):
    return {
        "missing-member": {"members": bundle.members[1:]},
        "missing-member-group": {"member_groups": bundle.member_groups[1:]},
        "missing-pooled-group": {"groups": bundle.groups[1:]},
        "missing-benchmark-group": {"expected_benchmark_group_ids": bundle.expected_benchmark_group_ids[1:]},
        "derivative": {"derivatives_present": True},
        "currency": {"reporting_currency": "EUR"},
        "fee-view": {"return_view": "GROSS"},
        "date": {"period_end": bundle.period_end + timedelta(days=1)},
        "policy-currency": {"policy": bundle.policy.model_copy(update={"reporting_currency": "EUR"})},
        "policy-window": {
            "policy": bundle.policy.model_copy(update={"effective_from": bundle.period_end + timedelta(days=1)})
        },
    }


def _economic_changes(bundle):
    changes = {
        name: {"groups": (bundle.groups[0].model_copy(update={field: value}), *bundle.groups[1:])}
        for name, field, value in (
            ("portfolio-zero", "portfolio_weight", 0.0),
            ("benchmark-zero", "benchmark_weight", 0.0),
            ("portfolio-short", "portfolio_weight", -0.1),
            ("benchmark-short", "benchmark_weight", -0.1),
            ("pooled-return-conflict", "portfolio_return", 0.11),
        )
    }
    changes["member-group-short"] = {
        "member_groups": (bundle.member_groups[0].model_copy(update={"member_weight": -0.1}), *bundle.member_groups[1:])
    }
    return changes


def _missing_observed_wire(bundle, case):
    bodies = deepcopy(bundle.raw_source_bodies)
    pin_id, collection, field = {
        "missing-member-return-wire": (bundle.group_source_pin_id, "member_groups", "actual_return"),
        "missing-group-return-wire": (bundle.group_source_pin_id, "groups", "portfolio_return"),
        "missing-benchmark-return-wire": (bundle.benchmark_pin_id, "groups", "return"),
    }[case]
    del bodies[pin_id]["projection"][collection][0][field]
    pins = tuple(
        pin.model_copy(update={"payload_digest": authority_digest(bodies[pin.pin_id])}) for pin in bundle.source_pins
    )
    # Do not reseal: the consumed original really lacks the observation even
    # though the normalized projection still claims to contain it.
    return AttributionSourceBundle.model_validate(
        bundle.model_copy(update={"raw_source_bodies": bodies, "source_pins": pins}).model_dump(mode="python")
    )
