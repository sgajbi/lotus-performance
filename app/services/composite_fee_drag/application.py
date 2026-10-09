"""Compare model facts with their own original gross receipts using the shared engine."""

from decimal import DecimalException, localcontext
from typing import NoReturn

from app.adapters.composite_materialization_repository import get_composite_materialization_store
from app.models.composite_fee_drag import (
    CompositeFeeDragMemberSource,
    CompositeFeeDragPeriod,
    CompositeFeeDragRequest,
    CompositeFeeDragResponse,
)
from app.models.composite_materialization import (
    CompositeComponentModelFeeMemberEvidence,
    CompositeModelFeeMemberEvidence,
    CompositeScheduledModelFeeMemberEvidence,
)
from app.models.composites import CompositeReturnView, CompositeTWRSelectionManifest
from app.services.calculation_engine_version import calculation_engine_version
from app.services.composite_calculation_service import select_composite_materialization_facts
from app.services.composite_materialization.model_fee_calculation import (
    calculate_with_model_fee_context,
    selected_facts_require_scoped_model_arithmetic,
)
from app.services.composite_materialization.model_fee_schedule_rates import scheduled_model_fee_context
from app.services.reproducibility_service import generate_value_fingerprint
from core.errors import APIUnprocessableEntityError


def _refuse(code: str) -> NoReturn:
    raise APIUnprocessableEntityError("Retained same-population model fee drag is unavailable.", error_code=code)


def _original_gross_facts(records):
    facts, sources = [], []
    for record in records:
        for outcome in record.outcomes:
            fact = outcome.fact
            if fact is None:
                continue
            evidence = outcome.source_evidence
            if not isinstance(
                evidence,
                (
                    CompositeModelFeeMemberEvidence,
                    CompositeScheduledModelFeeMemberEvidence,
                    CompositeComponentModelFeeMemberEvidence,
                ),
            ):
                _refuse("COMPOSITE_FEE_DRAG_GROSS_RECEIPT_REQUIRED")
            facts.append(
                fact.model_copy(
                    update={
                        "return_value": evidence.gross_return,
                        "return_view": CompositeReturnView.GROSS,
                        "source_snapshot_id": evidence.gross_receipt_digest,
                    }
                )
            )
            sources.append(
                CompositeFeeDragMemberSource(
                    portfolio_id=fact.portfolio_id,
                    period_start=fact.period_start,
                    period_end=fact.period_end,
                    gross_receipt_digest=evidence.gross_receipt_digest,
                    model_receipt_digest=fact.source_snapshot_id,
                )
            )
    return facts, sources


def _paired_periods(gross, model):
    rows = []
    if len(gross.period_results) != len(model.period_results):
        _refuse("COMPOSITE_FEE_DRAG_POPULATION_MISMATCH")
    for before, after in zip(gross.period_results, model.period_results, strict=True):
        if (
            (before.period_start, before.period_end, before.member_count, before.excluded_member_count)
            != (after.period_start, after.period_end, after.member_count, after.excluded_member_count)
            or before.return_value is None
            or after.return_value is None
        ):
            _refuse("COMPOSITE_FEE_DRAG_POPULATION_MISMATCH")
        rows.append(
            CompositeFeeDragPeriod(
                period_start=after.period_start,
                period_end=after.period_end,
                gross_return=before.return_value,
                model_net_return=after.return_value,
                fee_drag=before.return_value - after.return_value,
                member_count=after.member_count,
                excluded_member_count=after.excluded_member_count,
            )
        )
    return rows


def _exact_method_binding(records):
    binding = records[0].command.model_fee_binding
    if binding is None or any(record.command.model_fee_binding != binding for record in records):
        _refuse("COMPOSITE_FEE_DRAG_METHOD_MISMATCH")
    return binding


def _require_complete_calculations(gross, model):
    if (
        model.status != "READY"
        or gross.status != "READY"
        or model.cumulative_return is None
        or gross.cumulative_return is None
    ):
        _refuse("COMPOSITE_FEE_DRAG_POPULATION_UNAVAILABLE")


def calculate_model_fee_drag(request: CompositeFeeDragRequest, *, tenant_id: str) -> CompositeFeeDragResponse:
    try:
        with localcontext(scheduled_model_fee_context()):
            facts, windows = select_composite_materialization_facts(tenant_id=tenant_id, request=request)
            records = get_composite_materialization_store().get_many(request.materialization_ids, tenant_id=tenant_id)
            scheduled = selected_facts_require_scoped_model_arithmetic(facts, records)
            binding = _exact_method_binding(records)
            gross_facts, sources = _original_gross_facts(records)
            model = calculate_with_model_fee_context(
                composite_id=request.composite_id, facts=facts, scheduled=scheduled
            )
            gross = calculate_with_model_fee_context(
                composite_id=request.composite_id, facts=gross_facts, scheduled=scheduled
            )
            _require_complete_calculations(gross, model)
            periods = _paired_periods(gross, model)
            difference = gross.cumulative_return - model.cumulative_return
    except DecimalException:
        _refuse("COMPOSITE_FEE_DRAG_PRECISION_REFUSED")
    version = calculation_engine_version()
    response = CompositeFeeDragResponse(
        calculation_id=request.calculation_id,
        composite_id=request.composite_id,
        period_start=request.period_start,
        period_end=request.period_end,
        reporting_currency=records[0].command.reporting_currency,
        model_fee_binding=binding,
        cumulative_gross_return=gross.cumulative_return,
        cumulative_model_net_return=model.cumulative_return,
        cumulative_fee_drag=difference,
        periods=periods,
        member_sources=sources,
        selection_manifest=CompositeTWRSelectionManifest(
            windows=windows, engine_version=version, calculation_fingerprint="pending"
        ),
    )
    response.selection_manifest.calculation_fingerprint = generate_value_fingerprint(
        {
            "tenant_id": tenant_id,
            "request": request.model_dump(mode="json"),
            "result": response.model_dump(mode="json", exclude={"selection_manifest"}),
            "windows": [window.model_dump(mode="json") for window in windows],
        },
        version,
    )[0]
    return response
