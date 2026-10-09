"""Abrupt process death after each actual owning database insert."""

import os
import sys
from pathlib import Path
from uuid import uuid4

from sqlalchemy import event

from app.adapters.composite_principal_credentials import VerifiedCompositePrincipal
from app.adapters.composite_result_candidate_storage import CAPTURE_CAPABILITY
from app.core.config import get_settings
from app.models.composites import CompositeTWRRequest, CompositeTWRResponse
from app.services.async_result_store import AsyncResultStore
from app.services.composite_metadata_store import CompositeMetadataStore


def main():
    boundary = sys.argv[1]
    if boundary not in ("analytics_async_result", "composite_result_candidates"):
        raise ValueError("Unknown crash boundary")
    settings = get_settings()
    settings.APP_GIT_COMMIT_SHA = "c100c885752c86b8d950d7970c99a8d223e6376a"
    response = CompositeTWRResponse.model_validate_json(
        (Path(__file__).resolve().parents[1] / "fixtures" / "composite_candidate_original.json").read_text()
    )
    request = CompositeTWRRequest(
        calculation_id=response.calculation_id,
        composite_id=response.composite_id,
        period_start=response.period_start,
        period_end=response.period_end,
        return_view=response.periods[0].return_view,
        reporting_currency=response.periods[0].reporting_currency,
        materialization_ids=[window.materialization_id for window in response.selection_manifest.windows],
    )
    principal = VerifiedCompositePrincipal(
        "user",
        "verified-crash-test-maker",
        "tenant-a",
        frozenset({CAPTURE_CAPABILITY}),
        frozenset(member.portfolio_id for period in response.periods for member in period.member_contributions),
        "crash-test-credential",
    )
    store, results = (
        CompositeMetadataStore(settings.LINEAGE_METADATA_DATABASE_URL),
        AsyncResultStore(settings.LINEAGE_METADATA_DATABASE_URL),
    )

    def crash(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO " + boundary):
            print("reached_actual_write_boundary=" + boundary, flush=True)
            os._exit(73)

    event.listen(store._engine, "after_cursor_execute", crash)
    store.capture_result_candidate(
        candidate_id=uuid4(), request=request, response=response, principal=principal, result_store=results
    )
    raise AssertionError("Requested actual write boundary was never reached")


if __name__ == "__main__":
    main()
