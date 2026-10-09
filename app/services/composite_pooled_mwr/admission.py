"""Pool complete dated source economics before calling the existing MWR solver."""

import json
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal

from app.models.composite_authority import authority_digest
from app.models.composite_pooled_mwr import (
    CompositePooledMWRRequest,
    PooledInvestorCashFlow,
    PooledMonetaryObservation,
    PooledSourceBundle,
)
from app.services.composite_pooled_mwr.source_binding import refuse, require_source_bindings
from engine.numerical_boundary import NumericalDomainError, monetary_arithmetic_context


def admit_pooled_observation(
    request: CompositePooledMWRRequest, bundle: PooledSourceBundle, *, tenant_id: str
) -> PooledMonetaryObservation:
    pins = require_source_bindings(request, bundle, tenant_id=tenant_id)
    membership = _complete_membership(bundle)
    flows = _effective_flows(bundle)
    _require_monetary_rows(bundle, flows, pins)
    _require_flow_coverage(bundle, flows, pins)
    values = [row.amount for row in bundle.valuations] + [row.amount for row in flows]
    try:
        with monetary_arithmetic_context(values):
            return _pool_economics(request, bundle, membership, flows)
    except NumericalDomainError as exc:
        refuse("MONETARY_DOMAIN_UNSUPPORTED", str(exc))


def _complete_segments(segments, start, end, *, code):
    """Require disjoint inclusive complete coverage without enumerating dates."""
    clipped = _clipped_segments(segments, start, end)
    cursor = start
    for left, right, row in clipped:
        if left > right or cursor is None or left != cursor:
            refuse(code, "Dated source intervals overlap or leave a coverage gap.", unavailable=True)
        cursor = None if right == end else right + timedelta(days=1)
    if cursor is not None:
        refuse(code, "Dated source history does not cover the whole interval.", unavailable=True)
    return clipped


def _clipped_segments(segments, start, end):
    return sorted(
        ((max(left, start), min(right, end), row) for left, right, row in segments if left <= end and right >= start),
        key=lambda item: (item[0], item[1]),
    )


def _complete_membership(bundle):
    expected = set(bundle.expected_portfolio_ids)
    grouped = defaultdict(list)
    identities = set()
    for row in bundle.membership:
        if row.portfolio_id not in expected or row.source_row_id in identities or row.effective_from > row.effective_to:
            refuse("MEMBERSHIP_IDENTITY_CONFLICT", "Membership identity, population or date interval is invalid.")
        identities.add(row.source_row_id)
        grouped[row.portfolio_id].append((row.effective_from, row.effective_to, row))
    result = {}
    for member in sorted(expected):
        segments = _complete_segments(
            grouped[member], bundle.period_start, bundle.period_end, code="MISSING_POPULATION_COVERAGE"
        )
        if any(row.status == "PENDING" for _, _, row in segments):
            refuse("APPLICABILITY_UNAVAILABLE", "A population decision remains pending.", unavailable=True)
        result[member] = segments
    return result


def _identity(flow):
    return (flow.identity_namespace, flow.portfolio_id if flow.identity_scope == "PORTFOLIO" else "", flow.event_id)


def _event_label(flow):
    # Explicit field separators are JSON encoded, so source identifiers cannot collide.
    return json.dumps([*_identity(flow), flow.revision], separators=(",", ":"))


def _effective_flows(bundle):
    versions = {}
    namespace_scopes = {}
    for flow in bundle.flows:
        if namespace_scopes.setdefault(flow.identity_namespace, flow.identity_scope) != flow.identity_scope:
            refuse("SOURCE_IDENTITY_CONFLICT", "A source namespace cannot change its event identity scope.")
        key = (*_identity(flow), flow.revision)
        if key in versions and versions[key] != flow:
            refuse("SOURCE_IDENTITY_CONFLICT", "The same source flow revision has conflicting economics.")
        versions[key] = flow
    _require_lifecycle_graph(versions)
    active = {}
    for key, flow in versions.items():
        if flow.lifecycle_status != "ACTIVE":
            continue
        identity = key[:-1]
        if identity in active:
            refuse("SOURCE_IDENTITY_CONFLICT", "An event has more than one active source revision.")
        active[identity] = flow
    return sorted(active.values(), key=lambda flow: (flow.economic_date, _event_label(flow)))


def _require_lifecycle_graph(versions):
    predecessors = {}
    for key, flow in versions.items():
        if flow.predecessor_event_id is None:
            continue
        predecessor = (*_identity(flow)[:-1], flow.predecessor_event_id, flow.predecessor_revision)
        if predecessor not in versions or versions[predecessor].lifecycle_status == "ACTIVE":
            refuse(
                "FLOW_LIFECYCLE_UNAVAILABLE",
                "Flow correction lacks its resolved retained predecessor.",
                unavailable=True,
            )
        predecessors[key] = predecessor
    _require_acyclic_predecessors(predecessors)


def _require_acyclic_predecessors(predecessors):
    completed = set()
    for start in predecessors:
        current, path = start, set()
        while current in predecessors and current not in completed:
            if current in path:
                refuse("FLOW_LIFECYCLE_CONFLICT", "Source flow revision history contains a cycle.")
            path.add(current)
            current = predecessors[current]
        completed.update(path)


def _require_flow_coverage(bundle, flows, pins):
    expected = set(bundle.expected_portfolio_ids)
    by_member = defaultdict(list)
    for coverage in bundle.flow_coverage:
        if coverage.portfolio_id not in expected or coverage.source_pin_id not in pins:
            refuse("MISSING_FLOW_COVERAGE", "Flow coverage has an unknown member or source binding.", unavailable=True)
        if not coverage.complete or coverage.coverage_from > coverage.coverage_to:
            refuse("MISSING_FLOW_COVERAGE", "The flow population is not complete.", unavailable=True)
        by_member[coverage.portfolio_id].append((coverage.coverage_from, coverage.coverage_to, coverage))
    for member in expected:
        segments = _complete_segments(
            by_member[member], bundle.period_start, bundle.period_end, code="MISSING_FLOW_COVERAGE"
        )
        for left, right, coverage in segments:
            _require_covered_events(member, left, right, coverage, flows)


def _require_covered_events(member, left, right, coverage, flows):
    selected = [flow for flow in flows if flow.portfolio_id == member and left <= flow.economic_date <= right]
    if any(flow.source_pin_id != coverage.source_pin_id for flow in selected):
        refuse("SOURCE_CUT_CONFLICT", "Flow population and coverage use different source bindings.")
    _require_event_control(coverage, selected)


def _require_event_control(coverage, selected):
    if Counter(coverage.active_event_ids) != Counter(flow.event_id for flow in selected):
        refuse("MISSING_FLOW_COVERAGE", "Flow identities disagree with the source coverage control.", unavailable=True)
    if coverage.explicitly_empty != (not selected):
        refuse(
            "MISSING_FLOW_COVERAGE",
            "An empty flow list requires explicit source-owned empty coverage.",
            unavailable=True,
        )


def _require_monetary_rows(bundle, flows, pins):
    for row in [*bundle.valuations, *flows]:
        if row.portfolio_id not in bundle.expected_portfolio_ids or row.source_pin_id not in pins:
            refuse("SOURCE_IDENTITY_UNAVAILABLE", "Monetary observation has an unknown member/source binding.")
        if not bundle.period_start <= row.economic_date <= bundle.period_end:
            refuse(
                "ECONOMIC_DATE_OUTSIDE_WINDOW", "Selected monetary observations must lie within the explicit interval."
            )
        if row.currency != bundle.reporting_currency:
            refuse("UNSUPPORTED_CURRENCY", "This pooled source contract requires one reporting currency.")
    for flow in flows:
        _require_flow_classification_and_date(bundle, flow)


def _require_flow_classification_and_date(bundle, flow):
    if flow.classification == "UNKNOWN":
        refuse(
            "FLOW_CLASSIFICATION_UNAVAILABLE",
            "Unclassified source economics cannot become zero flows.",
            unavailable=True,
        )
    elected_date = {
        "EFFECTIVE_DATE": flow.source_date,
        "SETTLEMENT_DATE": flow.settlement_date,
        "PAYMENT_DATE": flow.payment_date,
    }[bundle.policy.date_basis]
    if elected_date is None:
        refuse("FLOW_DATE_POLICY_UNAVAILABLE", "The elected source date is not retained.", unavailable=True)
    if elected_date != flow.economic_date:
        refuse("FLOW_DATE_POLICY_MISMATCH", "Source date evidence conflicts with the elected economic date.")


def _member_status(segments, economic_date):
    starts = [left for left, _, _ in segments]
    index = bisect_right(starts, economic_date) - 1
    if index < 0 or economic_date > segments[index][1]:
        refuse("MISSING_POPULATION_COVERAGE", "Economic date has no membership decision.", unavailable=True)
    return segments[index][2].status


def _included_runs(segments):
    runs = []
    for left, right, row in segments:
        if row.status != "INCLUDED":
            continue
        if runs and runs[-1][1] + timedelta(days=1) == left:
            runs[-1] = (runs[-1][0], right)
        else:
            runs.append((left, right))
    return runs


def _boundary_economics(bundle, membership):
    values = _boundary_values(bundle)
    controls, boundary_flows = {}, []
    for member, segments in membership.items():
        control = {
            key: Decimal(0)
            for key in ("opening_value", "terminal_value", "external_flows", "entry_capital", "exit_capital")
        }
        for left, right in _included_runs(segments):
            _append_boundary_run(bundle, values, member, left, right, control, boundary_flows)
        controls[member] = control
    return controls, boundary_flows


def _boundary_values(bundle):
    values = {}
    for row in bundle.valuations:
        key = (row.portfolio_id, row.economic_date, row.role)
        if key in values:
            refuse("BOUNDARY_VALUATION_CONFLICT", "Boundary valuation must be unique.")
        values[key] = row
    return values


def _append_boundary_run(bundle, values, member, left, right, control, boundary_flows):
    opening_role = "OPENING" if left == bundle.period_start else "ENTRY"
    terminal_role = "TERMINAL" if right == bundle.period_end else "EXIT"
    for day, role, timing in (
        (left, opening_role, bundle.policy.opening_timing),
        (right, terminal_role, bundle.policy.terminal_timing),
    ):
        row = _source_boundary_row(values, member, day, role, timing)
        _append_membership_capital(bundle, row, boundary_flows)
        control[
            {
                "OPENING": "opening_value",
                "TERMINAL": "terminal_value",
                "ENTRY": "entry_capital",
                "EXIT": "exit_capital",
            }[role]
        ] += row.amount


def _source_boundary_row(values, member, day, role, timing):
    row = values.get((member, day, role))
    if row is None:
        refuse(
            "MISSING_BOUNDARY_VALUATION",
            "Every applicable opening/terminal/entry/exit requires a source valuation.",
            unavailable=True,
        )
    if row.timing != timing:
        refuse("BOUNDARY_TIMING_MISMATCH", "Boundary valuation timing differs from the approved policy.")
    return row


def _append_membership_capital(bundle, row, boundary_flows):
    if row.role not in {"ENTRY", "EXIT"}:
        return
    if bundle.policy.entry_exit_policy != "EXPLICIT_BOUNDARY_CAPITAL":
        refuse(
            "BOUNDARY_POLICY_UNAVAILABLE",
            "Membership transitions have no approved capital treatment.",
            unavailable=True,
        )
    amount = row.amount if row.role == "ENTRY" else row.amount.copy_negate()
    boundary_flows.append((row.economic_date, amount, "membership:" + row.source_row_id))


def _external_flows(bundle, membership, flows):
    selected, excluded = [], []
    for flow in flows:
        if _member_status(membership[flow.portfolio_id], flow.economic_date) == "EXCLUDED":
            excluded.append(_event_label(flow))
        else:
            selected.append(flow)
    external, transfers = _partition_transfer_flows(bundle, selected)
    eliminated = []
    for legs in transfers.values():
        _require_transfer_pair(legs)
        eliminated.extend(_event_label(flow) for flow in legs)
    return external, sorted(eliminated), sorted(excluded)


def _partition_transfer_flows(bundle, selected):
    transfers = defaultdict(list)
    external = []
    for flow in selected:
        if flow.classification == "POOL_TRANSFER":
            if bundle.policy.transfer_policy != "SOURCE_LINKED_RECONCILED" or flow.transfer_group_id is None:
                refuse(
                    "TRANSFER_POLICY_UNAVAILABLE",
                    "Pool transfers require approved source-linked consolidation.",
                    unavailable=True,
                )
            transfers[(flow.identity_namespace, flow.transfer_group_id)].append(flow)
        else:
            external.append(flow)
    return external, transfers


def _require_transfer_pair(legs):
    if len(legs) != 2:
        refuse(
            "TRANSFER_LEGS_UNRECONCILED",
            "Each consolidated transfer requires exactly two source-linked legs.",
            unavailable=True,
        )
    left, right = legs
    if not _matching_transfer_scope(left, right) or left.amount == 0 or left.amount + right.amount != 0:
        refuse(
            "TRANSFER_LEGS_UNRECONCILED",
            "Linked transfer legs do not reconcile their economic scope and amount.",
            unavailable=True,
        )


def _matching_transfer_scope(left, right):
    return not (
        left.portfolio_id == right.portfolio_id
        or left.counterparty_portfolio_id != right.portfolio_id
        or right.counterparty_portfolio_id != left.portfolio_id
        or left.economic_date != right.economic_date
        or left.timing != right.timing
        or left.currency != right.currency
    )


def _net_projection(rows):
    amounts, identities = defaultdict(lambda: Decimal(0)), defaultdict(list)
    for day, amount, source_id in rows:
        amounts[day] += amount
        identities[day].extend(source_id if isinstance(source_id, tuple) else (source_id,))
    return tuple(
        PooledInvestorCashFlow(economic_date=day, amount=amounts[day], source_event_ids=tuple(sorted(identities[day])))
        for day in sorted(amounts)
    )


def _pool_economics(request, bundle, membership, flows):
    controls, boundary_flows = _boundary_economics(bundle, membership)
    external, eliminated, excluded = _external_flows(bundle, membership, flows)
    for flow in external:
        controls[flow.portfolio_id]["external_flows"] += flow.amount
    opening = sum((control["opening_value"] for control in controls.values()), Decimal(0))
    terminal = sum((control["terminal_value"] for control in controls.values()), Decimal(0))
    portfolio = _net_projection(
        [*boundary_flows, *((flow.economic_date, flow.amount, _event_label(flow)) for flow in external)]
    )
    investor = _net_projection(
        [
            (bundle.period_start, opening.copy_negate(), "pooled:opening"),
            *((flow.economic_date, flow.amount.copy_negate(), flow.source_event_ids) for flow in portfolio),
            (bundle.period_end, terminal, "pooled:terminal"),
        ]
    )
    return PooledMonetaryObservation(
        tenant_id=bundle.tenant_id,
        composite_id=bundle.composite_id,
        source_manifest_id=bundle.source_manifest_id,
        input_manifest_digest=authority_digest(
            {"request": request.model_dump(mode="json"), "source_bundle": bundle.model_dump(mode="json")}
        ),
        period_start=bundle.period_start,
        period_end=bundle.period_end,
        reporting_currency=bundle.reporting_currency,
        opening_value=opening,
        terminal_value=terminal,
        portfolio_cash_flows=portfolio,
        investor_cash_flows=investor,
        per_member_controls={
            member: {key: str(value) for key, value in control.items()} for member, control in controls.items()
        },
        eliminated_transfer_event_ids=tuple(eliminated),
        excluded_flow_event_ids=tuple(excluded),
        source_bundle=bundle,
    )
