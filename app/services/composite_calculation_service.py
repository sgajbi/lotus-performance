from __future__ import annotations

from datetime import date as dt_date

from app.services.composite_metadata_store import CompositeMetadataStore, composite_metadata_store
from app.services.durable_store_runtime import RuntimeStoreProxy
from engine.composites import CompositeCalculationResult, calculate_asset_weighted_composite_twr


class CompositeDefinitionNotFoundError(ValueError):
    pass


def calculate_composite_twr_from_persisted_facts(
    *,
    composite_id: str,
    period_start: dt_date,
    period_end: dt_date,
    store: CompositeMetadataStore | RuntimeStoreProxy[CompositeMetadataStore] = composite_metadata_store,
) -> CompositeCalculationResult:
    definition = store.get_definition(composite_id)
    if definition is None:
        raise CompositeDefinitionNotFoundError(f"Composite definition not found: {composite_id}")

    facts = store.list_member_return_facts(
        composite_id=composite_id,
        period_start=period_start,
        period_end=period_end,
    )
    return calculate_asset_weighted_composite_twr(composite_id=composite_id, member_return_facts=facts)
