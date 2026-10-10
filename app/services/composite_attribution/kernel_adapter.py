"""Reuse the existing raw BF kernel without portfolio linking or unit conversion."""

from math import fsum

import pandas as pd

from app.models.attribution_requests import AttributionModel
from app.models.composite_attribution import AttributionEffect, AttributionOutcome
from app.services.composite_attribution.source_binding import refuse
from core.attribution_precision_policy import require_attribution_precision
from engine.attribution import _calculate_single_period_effects


def calculate_attribution(request, observation):
    precision = require_attribution_precision(request.precision_mode)
    bundle = observation.source_bundle
    frame = pd.DataFrame(
        [
            {
                "w_p": row.portfolio_weight,
                "w_b": row.benchmark_weight,
                "r_base_p": row.portfolio_return,
                "r_base_b": row.benchmark_return,
                "r_b_total": observation.benchmark_return,
            }
            for row in bundle.groups
        ]
    )
    effects = _calculate_single_period_effects(frame.copy(deep=True), AttributionModel.BRINSON_FACHLER)
    groups = tuple(
        AttributionEffect(
            group_id=source.group_id,
            allocation=float(row.allocation),
            selection=float(row.selection),
            interaction=float(row.interaction),
            total=fsum((row.allocation, row.selection, row.interaction)),
        )
        for source, row in zip(bundle.groups, effects.itertuples(), strict=True)
    )
    allocation, selection, interaction = (
        fsum(getattr(row, name) for row in groups) for name in ("allocation", "selection", "interaction")
    )
    active = observation.portfolio_return - observation.benchmark_return
    residual = fsum((allocation, selection, interaction)) - active
    if abs(residual) > bundle.policy.tolerance:
        refuse(
            "ATTRIBUTION_RECONCILIATION_FAILED", "BF effects do not reconcile to the observed arithmetic active return."
        )
    return AttributionOutcome(
        precision_mode=precision,
        portfolio_return=observation.portfolio_return,
        benchmark_return=observation.benchmark_return,
        active_return=active,
        allocation=allocation,
        selection=selection,
        interaction=interaction,
        reconciliation_delta=residual,
        groups=groups,
    )
