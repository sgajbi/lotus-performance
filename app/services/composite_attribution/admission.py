"""Admit complete observed economics before the portfolio kernel can zero-fill."""

from math import fsum

from app.models.composite_attribution import AttributionObservation
from app.models.composite_authority import authority_digest
from app.services.composite_attribution.source_binding import refuse, require_source_bindings, require_unique
from engine.numerical_boundary import finite_float64_projection


def _close(actual, expected, tolerance, code="SOURCE_ECONOMICS_CONFLICT"):
    if abs(actual - expected) > tolerance:
        refuse(code, "Observed economics do not reconcile within the exact approved policy tolerance.")


def admit_attribution(request, bundle, approval, *, tenant_id, original, vector):
    require_source_bindings(request, bundle, approval, tenant_id=tenant_id)
    period = _original_period(request, bundle, original, vector)
    tolerance = bundle.policy.tolerance
    groups = _group_universe(bundle)
    members = _members(bundle, period, tolerance)
    _member_group_economics(bundle, groups, members, tolerance)
    return _observation(bundle, approval, period, tolerance)


def _group_universe(bundle):
    groups = require_unique(bundle.expected_group_ids)
    if require_unique(bundle.expected_benchmark_group_ids) != groups:
        refuse("UNSUPPORTED_OFF_BENCHMARK_GROUP", "Initial BF policy requires the same complete group universe.")
    if require_unique([row.group_id for row in bundle.groups]) != groups:
        refuse("SOURCE_UNIVERSE_INCOMPLETE", "Observed pooled groups differ from the full expected universe.")
    if bundle.derivatives_present:
        refuse("UNSUPPORTED_DERIVATIVE_CONVENTION", "Derivative attribution is not elected by this method policy.")
    for row in bundle.groups:
        if row.portfolio_weight <= 0 or row.benchmark_weight <= 0:
            refuse(
                "UNSUPPORTED_ZERO_OR_SIGNED_WEIGHT",
                "Zero, short and off-benchmark exposures require another elected convention.",
            )
    return groups


def _observation(bundle, approval, period, tolerance):
    # Original evidence remains Decimal. Only dimensionless ratios enter FLOAT64 BF.
    original_ratio = finite_float64_projection(period.return_value)
    wp = fsum(row.portfolio_weight for row in bundle.groups)
    wb = fsum(row.benchmark_weight for row in bundle.groups)
    _close(wp, 1.0, tolerance, "WEIGHT_UNIVERSE_INCOMPLETE")
    _close(wb, 1.0, tolerance, "WEIGHT_UNIVERSE_INCOMPLETE")
    portfolio = fsum(row.portfolio_weight * row.portfolio_return for row in bundle.groups)
    benchmark = fsum(row.benchmark_weight * row.benchmark_return for row in bundle.groups)
    _close(portfolio, original_ratio, tolerance, "ORIGINAL_RETURN_RECONCILIATION_FAILED")
    content = {"source_bundle": bundle.model_dump(mode="json"), "approval": approval.model_dump(mode="json")}
    return AttributionObservation(
        input_manifest_digest=authority_digest(content),
        source_bundle=bundle,
        approval=approval,
        original_return=original_ratio,
        portfolio_return=portfolio,
        benchmark_return=benchmark,
        portfolio_weight_sum=wp,
        benchmark_weight_sum=wb,
        portfolio_reconciliation_delta=portfolio - original_ratio,
    )


def _original_period(request, bundle, original, vector):
    response = original.response
    actual = (
        original.candidate_id,
        original.tenant_id,
        original.original_response_digest,
        vector.vector_digest,
        len(vector.windows),
        response.composite_id,
        len(response.periods),
    )
    expected = (
        request.candidate_id,
        bundle.tenant_id,
        bundle.original_response_digest,
        bundle.vector_digest,
        1,
        request.composite_id,
        1,
    )
    if actual != expected:
        refuse(
            "ORIGINAL_DEPENDENCY_CONFLICT",
            "BF requires one exact captured original period and retained dependency vector.",
        )
    period = response.periods[0]
    if (
        period.status != "READY"
        or period.return_value is None
        or (period.period_start, period.period_end, period.reporting_currency, period.return_view)
        != (request.period_start, request.period_end, request.reporting_currency, request.return_view)
    ):
        refuse("ORIGINAL_DEPENDENCY_UNAVAILABLE", "Captured original is not READY on the exact requested basis.")
    windows = response.selection_manifest.windows if response.selection_manifest else []
    if len(windows) != 1 or windows[0].membership_content_hash != bundle.membership_digest:
        refuse("MEMBERSHIP_IDENTITY_CONFLICT", "Attribution population does not bind the original membership digest.")
    return period


def _members(bundle, period, tolerance):
    expected = require_unique(bundle.expected_portfolio_ids)
    if require_unique([row.portfolio_id for row in bundle.members]) != expected:
        refuse("MISSING_POPULATION_COVERAGE", "Original historical member vector is incomplete.")
    require_unique([row.source_row_id for row in bundle.members], code="SOURCE_IDENTITY_CONFLICT")
    included = {}
    for row in bundle.members:
        if _included_member(bundle, row):
            included[row.portfolio_id] = row
    _reconcile_original_members(included, period, tolerance)
    return included


def _included_member(bundle, row):
    if row.effective_from > bundle.period_start or row.effective_to < bundle.period_end or row.status == "PENDING":
        refuse(
            "MEMBERSHIP_HISTORY_UNAVAILABLE", "Initial policy requires complete unchanged membership over one period."
        )
    if row.status == "EXCLUDED":
        if row.composite_weight != 0:
            refuse("MEMBERSHIP_IDENTITY_CONFLICT", "Approved excluded members cannot participate economically.")
        return False
    if row.composite_weight <= 0:
        refuse("UNSUPPORTED_ZERO_OR_SIGNED_WEIGHT", "Included members require positive observed capital weights.")
    return True


def _reconcile_original_members(included, period, tolerance):
    originals = {row.portfolio_id: row for row in period.member_contributions}
    if not included or set(included) != set(originals) or len(originals) != len(period.member_contributions):
        refuse("MISSING_POPULATION_COVERAGE", "Source drops or adds an economically included original member.")
    for identity, row in included.items():
        _close(row.composite_weight, finite_float64_projection(originals[identity].beginning_asset_weight), tolerance)
        _close(row.actual_return, finite_float64_projection(originals[identity].return_value), tolerance)
    _close(fsum(row.composite_weight for row in included.values()), 1.0, tolerance, "WEIGHT_UNIVERSE_INCOMPLETE")


def _member_group_economics(bundle, groups, members, tolerance):
    rows = _member_group_rows(bundle, groups, members)
    _reconcile_member_groups(rows, groups, members, tolerance)
    _reconcile_pooled_groups(bundle, rows, members, tolerance)


def _member_group_rows(bundle, groups, members):
    rows = _require_member_group_universe(bundle, groups, members)
    for row in rows.values():
        if row.member_weight <= 0:
            refuse("UNSUPPORTED_ZERO_OR_SIGNED_WEIGHT", "Initial policy requires positive member/group exposure.")
    return rows


def _require_member_group_universe(bundle, groups, members):
    rows = {(row.portfolio_id, row.group_id): row for row in bundle.member_groups}
    expected = {(member, group) for member in members for group in groups}
    if len(rows) != len(bundle.member_groups) or set(rows) != expected:
        refuse("MEMBER_GROUP_UNIVERSE_INCOMPLETE", "Every included member requires every elected group exactly once.")
    require_unique([row.source_row_id for row in bundle.member_groups], code="SOURCE_IDENTITY_CONFLICT")
    require_unique([row.source_row_id for row in bundle.groups], code="SOURCE_IDENTITY_CONFLICT")
    return rows


def _reconcile_member_groups(rows, groups, members, tolerance):
    for identity, member in members.items():
        selected = [rows[identity, group] for group in groups]
        _close(fsum(row.member_weight for row in selected), 1.0, tolerance, "WEIGHT_UNIVERSE_INCOMPLETE")
        _close(fsum(row.member_weight * row.actual_return for row in selected), member.actual_return, tolerance)


def _reconcile_pooled_groups(bundle, rows, members, tolerance):
    for group in bundle.groups:
        capital = fsum(
            member.composite_weight * rows[identity, group.group_id].member_weight
            for identity, member in members.items()
        )
        contribution = fsum(
            member.composite_weight
            * rows[identity, group.group_id].member_weight
            * rows[identity, group.group_id].actual_return
            for identity, member in members.items()
        )
        _close(capital, group.portfolio_weight, tolerance)
        # Compare actual supplied group economics. Never derive a missing group return.
        _close(contribution, group.portfolio_weight * group.portfolio_return, tolerance)
