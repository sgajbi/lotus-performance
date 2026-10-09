from __future__ import annotations

from datetime import date as dt_date
from uuid import UUID

from app.adapters.composite_materialization_repository import get_composite_materialization_store
from app.models.composite_authority import ManageCompositeDefinitionV2
from app.models.composite_materialization import CompositeMaterializationCommand, CompositeMaterializationState
from app.models.composites import (
    CompositeMemberReturnFact,
    CompositeReturnView,
    CompositeTWRRequest,
    CompositeTWRWindowEvidence,
)
from app.observability import tenant_id_var
from app.services.composite_materialization.model_fee_calculation import (
    calculate_with_model_fee_context,
    requires_scoped_model_arithmetic,
    selected_facts_require_scoped_model_arithmetic,
)
from app.services.composite_materialization.records import MaterializationRecord
from app.services.composite_materialization.source_contract import ManageCompositeDefinition
from app.services.composite_materialization.window_currency_authority import (
    CurrencyWindowAuthority,
    require_compatible_currency_authority,
    retained_currency_authority,
)
from app.services.composite_metadata_store import CompositeMetadataStore, composite_metadata_store
from app.services.core_tenant_authority import admitted_tenant_authority, require_composite_tenant_authority
from app.services.durable_store_runtime import RuntimeStoreProxy
from app.services.reproducibility_service import generate_value_fingerprint
from core.errors import APIConflictError, APIUnprocessableEntityError
from engine.composites import CompositeCalculationResult


class CompositeDefinitionNotFoundError(ValueError):
    pass


def calculate_composite_twr_from_materializations(
    *, tenant_id: str, request: CompositeTWRRequest
) -> tuple[CompositeCalculationResult, list[CompositeTWRWindowEvidence]]:
    """Explicit historical selection; never infer latest or official authority."""
    facts, windows = select_composite_materialization_facts(tenant_id=tenant_id, request=request)
    scheduled = request.return_view == CompositeReturnView.NET_MODEL_FEE and requires_scoped_model_arithmetic(
        windows[0].method_binding
    )
    return calculate_with_model_fee_context(
        composite_id=request.composite_id, facts=facts, scheduled=scheduled
    ), windows


def select_composite_materialization_facts(
    *, tenant_id: str, request: CompositeTWRRequest
) -> tuple[list[CompositeMemberReturnFact], list[CompositeTWRWindowEvidence]]:
    """Admit the same retained vector once and expose original Decimal financial facts."""
    materialization_ids = _selected_materializations(request)
    records = get_composite_materialization_store().get_many(materialization_ids, tenant_id=tenant_id)
    _require_vector_order(records)
    cursor = request.period_start.toordinal()
    currency = request.reporting_currency or records[0].command.reporting_currency
    basis = None
    facts, windows = [], []
    for record in records:
        definition = _complete_window_definition(record)
        _require_window_scope(record.command, request, currency, cursor)
        currency_authority = retained_currency_authority(record)
        method = retained_return_method(definition, currency_authority.normalization_method)
        selected_basis = (
            definition.calculation_method,
            record.command.policy_version,
            method,
            currency_authority.normalization_method,
            currency_authority.native_currency,
            currency_authority.member_money_currencies,
        )
        _require_compatible_window_authority(basis, selected_basis)
        basis = selected_basis
        facts.extend(_window_facts(record))
        windows.append(retained_window_evidence(record, method))
        cursor = record.command.period_end.toordinal() + 1
    if records[-1].command.period_end != request.period_end:
        raise APIConflictError("A required retained window is missing.", error_code="REQUIRED_PERIOD_UNAVAILABLE")
    return facts, windows


def _require_compatible_window_authority(previous, selected):
    if previous is None:
        return
    require_compatible_currency_authority(
        CurrencyWindowAuthority(*previous[-3:]), CurrencyWindowAuthority(*selected[-3:])
    )
    if previous[:-3] != selected[:-3]:
        raise APIUnprocessableEntityError(
            "Selected window method or policy authority differs.", error_code="COMPOSITE_VECTOR_METHOD_MISMATCH"
        )


def _selected_materializations(request: CompositeTWRRequest) -> list[UUID]:
    if request.materialization_ids is None:
        raise APIUnprocessableEntityError(
            "Pinned TWR replay requires an explicit materialization selection.",
            error_code="COMPOSITE_VECTOR_SELECTION_REQUIRED",
        )
    return request.materialization_ids


def _require_vector_order(records: list[MaterializationRecord]) -> None:
    starts = [record.command.period_start for record in records]
    if starts != sorted(starts):
        raise APIUnprocessableEntityError(
            "Selected windows are not in canonical order.", error_code="COMPOSITE_VECTOR_WINDOW_MISMATCH"
        )


def _complete_window_definition(
    record: MaterializationRecord,
) -> ManageCompositeDefinition | ManageCompositeDefinitionV2:
    if record.state != CompositeMaterializationState.COMPLETE or record.source is None:
        raise APIConflictError("A required retained window is unavailable.", error_code="REQUIRED_PERIOD_UNAVAILABLE")
    definition = record.source.definition
    if not isinstance(definition, ManageCompositeDefinitionV2) and record.source.currency_normalization_wire is None:
        raise APIUnprocessableEntityError(
            "Pinned TWR windows require retained method authority.", error_code="COMPOSITE_VECTOR_METHOD_UNAVAILABLE"
        )
    return definition


def retained_return_method(definition, currency_method):
    if isinstance(definition, ManageCompositeDefinitionV2):
        return definition.source_authority.payload.return_method_binding.model_dump(mode="json")
    if currency_method is None:
        raise APIUnprocessableEntityError(
            "Pinned TWR windows require retained method authority.", error_code="COMPOSITE_VECTOR_METHOD_UNAVAILABLE"
        )
    return currency_method


def _require_window_scope(
    command: CompositeMaterializationCommand, request: CompositeTWRRequest, currency: str, cursor: int
) -> None:
    if (command.composite_id, command.return_view, command.reporting_currency) != (
        request.composite_id,
        request.return_view,
        currency,
    ):
        raise APIUnprocessableEntityError(
            "Selected window scope differs from the request.", error_code="COMPOSITE_VECTOR_SCOPE_MISMATCH"
        )
    if command.period_start.toordinal() > cursor:
        raise APIConflictError("A required retained window is missing.", error_code="REQUIRED_PERIOD_UNAVAILABLE")
    if command.period_start.toordinal() < cursor or command.period_end > request.period_end:
        raise APIUnprocessableEntityError(
            "Selected windows overlap or are not in canonical order.", error_code="COMPOSITE_VECTOR_WINDOW_MISMATCH"
        )


def _window_facts(record: MaterializationRecord) -> list[CompositeMemberReturnFact]:
    facts = [outcome.fact for outcome in record.outcomes if outcome.fact is not None]
    if not facts:
        raise APIConflictError(
            "A required retained window has no eligible facts.", error_code="REQUIRED_PERIOD_UNAVAILABLE"
        )
    if any(fact.ending_market_value is None for fact in facts):
        raise APIUnprocessableEntityError(
            "Pinned asset reporting requires authoritative ending assets.",
            error_code="COMPOSITE_ENDING_ASSETS_UNAVAILABLE",
        )
    return facts


def retained_window_evidence(record: MaterializationRecord, method: dict[str, str]) -> CompositeTWRWindowEvidence:
    command, source = record.command, record.source
    if source is None:
        raise APIConflictError("A required retained window is unavailable.", error_code="REQUIRED_PERIOD_UNAVAILABLE")
    receipt_fingerprint = generate_value_fingerprint(
        {
            # Preserve the pre-model-fee v1 receipt shape, including all its
            # existing nulls and executor/FX pins. Bound fee custody remains
            # part of the hash; absent new optional fields must not change it.
            "command": command.model_dump(
                mode="json", exclude={"model_fee_binding"} if command.model_fee_binding is None else set()
            ),
            "source": source.model_dump(
                mode="json", exclude={"model_fee_wire"} if source.model_fee_wire is None else set()
            ),
            "outcomes": [outcome.model_dump(mode="json") for outcome in record.outcomes],
        },
        "composite-retained-window.v1",
    )[0]
    return CompositeTWRWindowEvidence(
        materialization_id=command.materialization_id,
        period_start=command.period_start,
        period_end=command.period_end,
        restatement_sequence=command.restatement_sequence,
        definition_content_hash=command.definition_content_hash,
        membership_content_hash=command.membership_content_hash,
        attestation_content_hash=command.attestation_content_hash,
        source_cut_id=command.source_cut_id,
        method_binding=method,
        retained_receipt_fingerprint=receipt_fingerprint,
    )


def calculate_composite_twr_from_persisted_facts(
    *,
    tenant_id: str | None = None,
    composite_id: str,
    period_start: dt_date,
    period_end: dt_date,
    return_view: CompositeReturnView = CompositeReturnView.NET_ACTUAL,
    reporting_currency: str | None = None,
    restatement_sequence: int | None = None,
    store: CompositeMetadataStore | RuntimeStoreProxy[CompositeMetadataStore] = composite_metadata_store,
) -> CompositeCalculationResult:
    tenant_id = require_composite_tenant_authority(
        admitted_tenant_authority(tenant_id_var.get() if tenant_id is None else tenant_id),
    ).tenant_id
    definition = store.get_definition(composite_id, tenant_id=tenant_id)
    if definition is None:
        raise CompositeDefinitionNotFoundError(f"Composite definition not found: {composite_id}")

    facts = store.list_member_return_facts(
        tenant_id=tenant_id,
        composite_id=composite_id,
        period_start=period_start,
        period_end=period_end,
        return_view=return_view,
        reporting_currency=reporting_currency,
        restatement_sequence=restatement_sequence,
    )
    if any(fact.ending_market_value is None for fact in facts):
        raise APIUnprocessableEntityError(
            detail="This composite calculation includes asset reporting and requires authoritative ending assets.",
            error_code="COMPOSITE_ENDING_ASSETS_UNAVAILABLE",
        )
    scheduled = False
    if return_view == CompositeReturnView.NET_MODEL_FEE and facts:
        records = store.get_member_return_fact_materializations(facts, tenant_id=tenant_id)
        scheduled = selected_facts_require_scoped_model_arithmetic(facts, records)
    return calculate_with_model_fee_context(composite_id=composite_id, facts=facts, scheduled=scheduled)
