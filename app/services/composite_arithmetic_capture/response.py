"""One native projection for ordinary and precision-captured composite results."""

from app.models.composites import (
    CompositeMemberContributionResponse,
    CompositePeriodResultResponse,
    CompositeTWRResponse,
    CompositeTWRSelectionManifest,
)
from app.services.calculation_engine_version import calculation_engine_version
from app.services.reproducibility_service import generate_value_fingerprint


def _member_contribution_response(item) -> CompositeMemberContributionResponse:
    return CompositeMemberContributionResponse(
        portfolio_id=item.portfolio_id,
        period_start=item.period_start,
        period_end=item.period_end,
        return_value=item.return_value,
        beginning_market_value=item.beginning_market_value,
        beginning_asset_weight=item.weight,
        contribution=item.contribution,
        source_snapshot_id=item.source_snapshot_id,
        source_fingerprint=item.source_fingerprint,
        restatement_version=item.restatement_version,
        restatement_sequence=item.restatement_sequence,
        calculation_id=item.calculation_id,
        source_authority_identity=item.source_authority_identity,
    )


def _period_response(item) -> CompositePeriodResultResponse:
    return CompositePeriodResultResponse(
        period_start=item.period_start,
        period_end=item.period_end,
        status=item.status,
        return_value=item.return_value,
        cumulative_return=item.cumulative_return,
        beginning_market_value=item.beginning_market_value,
        ending_market_value=item.ending_market_value,
        member_count=item.member_count,
        excluded_member_count=item.excluded_member_count,
        dispersion_equal_weight=item.dispersion_equal_weight,
        return_view=item.return_view,
        reporting_currency=item.reporting_currency,
        source_fingerprints=item.source_fingerprints,
        restatement_versions=item.restatement_versions,
        restatement_sequence=item.restatement_sequence,
        reason_codes=item.reason_codes,
        member_contributions=[
            _member_contribution_response(contribution) for contribution in item.member_contributions
        ],
    )


def composite_response(request, result, windows, tenant_id):
    response = CompositeTWRResponse(
        calculation_id=request.calculation_id,
        composite_id=result.composite_id,
        status=result.status,
        period_start=request.period_start,
        period_end=request.period_end,
        cumulative_return=result.cumulative_return,
        reason_codes=result.reason_codes,
        periods=[_period_response(period) for period in result.period_results],
    )
    if windows is not None:
        version = calculation_engine_version()
        fingerprint = generate_value_fingerprint(
            {
                "tenant_id": tenant_id,
                "request": request.model_dump(mode="json"),
                "windows": [window.model_dump(mode="json") for window in windows],
                "result": response.model_dump(mode="json"),
            },
            version,
        )[0]
        response.selection_manifest = CompositeTWRSelectionManifest(
            windows=windows, engine_version=version, calculation_fingerprint=fingerprint
        )
    return response
