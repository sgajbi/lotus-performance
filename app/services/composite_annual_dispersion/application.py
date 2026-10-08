"""Qualify historical populations before invoking the annual financial method."""

from calendar import monthrange
from datetime import date

from app.models.composite_annual_dispersion import (
    AnnualDispersionMember,
    AnnualDispersionMonthEvidence,
    CompositeAnnualDispersionRequest,
    CompositeAnnualDispersionResponse,
)
from app.models.composite_materialization import (
    CompositeMaterializationState,
    CompositeMemberMaterializationOutcome,
    CompositeMemberOutcomeState,
)
from app.models.composites import CompositeMemberReturnFact
from app.ports.composite_annual_dispersion import AnnualDispersionReceiptReader
from app.services.composite_materialization.progress_policy import require_retained_progress
from app.services.composite_materialization.records import MaterializationRecord
from app.services.composite_materialization.window_currency_authority import require_compatible_currency_windows
from app.services.core_tenant_authority import admitted_tenant_authority, require_composite_tenant_authority
from app.services.reproducibility_service import generate_value_fingerprint
from core.errors import APIConflictError, APIUnprocessableEntityError
from engine.composite_annual_dispersion import (
    AnnualDispersionDomainError,
    AnnualMemberReturn,
    calculate_annual_dispersion,
    link_full_year_member_return,
)


def _refuse(code: str) -> None:
    raise APIUnprocessableEntityError(
        "Annual dispersion requires compatible complete historical evidence.", error_code=code
    )


def _records(
    request: CompositeAnnualDispersionRequest, *, reader: AnnualDispersionReceiptReader, tenant_id: str
) -> list[MaterializationRecord]:
    records = [reader.get(identity, tenant_id=tenant_id) for identity in request.materialization_ids]
    ordered = sorted(records, key=lambda item: item.command.period_start)
    for month, record in enumerate(ordered, 1):
        _require_month_scope(record, request, month)
        require_retained_progress(
            command=record.command,
            tenant_id=tenant_id,
            source=record.source,
            outcomes=record.outcomes,
            state=record.state,
        )
    if len({item.command.materialization_id for item in ordered}) != 12:
        _refuse("ANNUAL_DISPERSION_RECEIPT_IDENTITY_MISMATCH")
    require_compatible_currency_windows(ordered)
    bases = {(item.command.definition_content_hash, item.command.policy_version) for item in ordered}
    if len(bases) != 1:
        _refuse("ANNUAL_DISPERSION_POLICY_BASIS_MISMATCH")
    return ordered


def _require_month_scope(record: MaterializationRecord, request: CompositeAnnualDispersionRequest, month: int) -> None:
    command = record.command
    if record.state != CompositeMaterializationState.COMPLETE or record.source is None:
        raise APIConflictError(
            "A selected monthly materialization is not complete.", error_code="ANNUAL_DISPERSION_MONTH_NOT_COMPLETE"
        )
    expected = (
        request.composite_id,
        request.return_view,
        request.reporting_currency,
        date(request.year, month, 1),
        date(request.year, month, monthrange(request.year, month)[1]),
    )
    actual = (
        command.composite_id,
        command.return_view,
        command.reporting_currency,
        command.period_start,
        command.period_end,
    )
    if actual != expected:
        _refuse("ANNUAL_DISPERSION_MONTH_SCOPE_MISMATCH")
    if command.materialization_id not in request.materialization_ids:
        _refuse("ANNUAL_DISPERSION_RECEIPT_IDENTITY_MISMATCH")


def _month_evidence(record: MaterializationRecord) -> AnnualDispersionMonthEvidence:
    return AnnualDispersionMonthEvidence.model_validate(
        record.command.model_dump(
            include={
                "materialization_id",
                "period_start",
                "period_end",
                "definition_version",
                "definition_content_hash",
                "membership_revision",
                "membership_content_hash",
                "attestation_version",
                "attestation_content_hash",
                "policy_version",
                "source_cut_id",
                "restatement_sequence",
            }
        )
    )


def _annual_members(records: list[MaterializationRecord]) -> tuple[list[AnnualDispersionMember], int]:
    # Retained-progress admission proves READY corresponds to INCLUDED discretionary membership,
    # EXCLUDED to an explicit policy decision, and every attested identity has one outcome.
    populations = [
        {item.portfolio_id: item for item in record.outcomes if item.state == CompositeMemberOutcomeState.READY}
        for record in records
    ]
    full_year = set(populations[0]).intersection(*(set(population) for population in populations[1:]))
    members = [
        _member_evidence(identity, [population[identity] for population in populations])
        for identity in sorted(full_year)
    ]
    return members, len(populations[-1])


def _member_evidence(identity: str, outcomes: list[CompositeMemberMaterializationOutcome]) -> AnnualDispersionMember:
    retained_facts = [_required_fact(outcome) for outcome in outcomes]
    return AnnualDispersionMember(
        portfolio_id=identity,
        annual_return=link_full_year_member_return([fact.return_value for fact in retained_facts]),
        year_begin_assets=retained_facts[0].beginning_market_value,
        source_snapshot_ids=[fact.source_snapshot_id for fact in retained_facts],
        source_fingerprints=[fact.source_fingerprint for fact in retained_facts],
    )


def _required_fact(outcome: CompositeMemberMaterializationOutcome) -> CompositeMemberReturnFact:
    if outcome.fact is None:
        raise APIUnprocessableEntityError(
            "A full-year member has no retained return fact.", error_code="ANNUAL_DISPERSION_MEMBER_RETURN_MISSING"
        )
    return outcome.fact


def calculate_annual_member_dispersion(
    request: CompositeAnnualDispersionRequest, *, tenant_id: str, reader: AnnualDispersionReceiptReader
) -> CompositeAnnualDispersionResponse:
    tenant = require_composite_tenant_authority(admitted_tenant_authority(tenant_id)).tenant_id
    records = _records(request, reader=reader, tenant_id=tenant)
    try:
        members, year_end_count = _annual_members(records)
        value = calculate_annual_dispersion(
            [AnnualMemberReturn(item.portfolio_id, item.annual_return, item.year_begin_assets) for item in members],
            method=request.method,
        )
    except AnnualDispersionDomainError as exc:
        raise APIUnprocessableEntityError(
            "Annual dispersion inputs are outside the selected financial domain.",
            error_code="ANNUAL_DISPERSION_NUMERICAL_DOMAIN_REFUSED",
        ) from exc
    result = CompositeAnnualDispersionResponse(
        method=request.method,
        composite_id=request.composite_id,
        period_start=date(request.year, 1, 1),
        period_end=date(request.year, 12, 31),
        return_view=request.return_view,
        reporting_currency=request.reporting_currency,
        value=value,
        status="AVAILABLE" if value is not None else "UNAVAILABLE",
        reason_codes=[] if value is not None else ["ANNUAL_DISPERSION_INSUFFICIENT_MEMBERS"],
        year_end_member_count=year_end_count,
        full_year_member_count=len(members),
        reporting_applicability="NOT_REQUIRED_SMALL_POPULATION" if len(members) <= 5 else "REQUIRES_PROFILE_REVIEW",
        result_fingerprint="pending",
        months=[_month_evidence(record) for record in records],
        members=members,
    )
    digest, _ = generate_value_fingerprint(
        {"tenant_id": tenant, "result": result.model_dump(mode="json", exclude={"result_fingerprint"})},
        "composite-annual-dispersion.v1",
    )
    return result.model_copy(update={"result_fingerprint": digest})
