"""Compare admitted public v1 annual outputs without another estimator."""

from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

from app.models.composite_annual_comparison import CompositeAnnualComparisonRequest, CompositeAnnualComparisonResponse
from app.models.composite_annual_dispersion import CompositeAnnualDispersionResponse
from app.ports.composite_annual_dispersion import AnnualDispersionReceiptReader
from app.services.composite_annual_dispersion.application import calculate_annual_member_dispersion
from app.services.core_tenant_authority import admitted_tenant_authority, require_composite_tenant_authority
from app.services.reproducibility_service import generate_value_fingerprint
from core.errors import APIUnprocessableEntityError


def _available_output_delta(
    baseline: CompositeAnnualDispersionResponse, candidate: CompositeAnnualDispersionResponse
) -> Decimal | None:
    if baseline.value is None or candidate.value is None:
        return None
    # Admitted v1 outputs are nonnegative, quantized and bounded by its 60-digit context.
    with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN, Emin=-128, Emax=128)):
        return candidate.value - baseline.value


def compare_annual_member_dispersion(
    request: CompositeAnnualComparisonRequest, *, tenant_id: str, reader: AnnualDispersionReceiptReader
) -> CompositeAnnualComparisonResponse:
    tenant = require_composite_tenant_authority(admitted_tenant_authority(tenant_id)).tenant_id
    baseline = calculate_annual_member_dispersion(request.baseline, tenant_id=tenant, reader=reader)
    candidate = calculate_annual_member_dispersion(request.candidate, tenant_id=tenant, reader=reader)
    baseline_basis = (baseline.months[0].definition_content_hash, baseline.months[0].policy_version)
    candidate_basis = (candidate.months[0].definition_content_hash, candidate.months[0].policy_version)
    if baseline_basis != candidate_basis:
        raise APIUnprocessableEntityError(
            "Annual comparison requires the same admitted definition and policy basis.",
            error_code="ANNUAL_COMPARISON_POLICY_BASIS_MISMATCH",
        )
    reasons = [
        f"{side}_{reason}"
        for side, result in (("BASELINE", baseline), ("CANDIDATE", candidate))
        for reason in result.reason_codes
    ]
    value = _available_output_delta(baseline, candidate)
    old_members = {member.portfolio_id for member in baseline.members}
    new_members = {member.portfolio_id for member in candidate.members}
    result = CompositeAnnualComparisonResponse(
        baseline=baseline,
        candidate=candidate,
        value=value,
        status="AVAILABLE" if value is not None else "UNAVAILABLE",
        reason_codes=reasons,
        full_year_members_added=sorted(new_members - old_members),
        full_year_members_removed=sorted(old_members - new_members),
        result_fingerprint="pending",
    )
    digest, _ = generate_value_fingerprint(
        {"tenant_id": tenant, "result": result.model_dump(mode="json", exclude={"result_fingerprint"})},
        "composite-annual-comparison.v1",
    )
    return result.model_copy(update={"result_fingerprint": digest})
