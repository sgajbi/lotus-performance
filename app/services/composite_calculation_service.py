from __future__ import annotations

from datetime import date as dt_date

from app.models.composites import CompositeReturnView
from app.observability import tenant_id_var
from app.services.composite_metadata_store import CompositeMetadataStore, composite_metadata_store
from app.services.core_tenant_authority import admitted_tenant_authority, require_composite_tenant_authority
from app.services.durable_store_runtime import RuntimeStoreProxy
from engine.composites import CompositeCalculationResult, calculate_asset_weighted_composite_twr


class CompositeDefinitionNotFoundError(ValueError):
    pass


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

    selected_reporting_currency = reporting_currency or definition.reporting_currency
    facts = store.list_member_return_facts(
        tenant_id=tenant_id,
        composite_id=composite_id,
        period_start=period_start,
        period_end=period_end,
        return_view=return_view,
        reporting_currency=selected_reporting_currency,
        restatement_sequence=restatement_sequence,
    )
    return calculate_asset_weighted_composite_twr(composite_id=composite_id, member_return_facts=facts)
