from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from datetime import date
from decimal import Decimal

from pydantic import ValidationError

from app.models.composite_materialization import (
    CompositeMaterializationCommand,
    CompositeMemberCalculationReference,
    CompositeMemberMaterializationOutcome,
    CompositeMemberOutcomeState,
    CompositeMemberSourceEvidence,
    CompositeNormalizedMemberSourceEvidence,
)
from app.models.composites import CompositeMemberReturnFact
from app.models.portfolio_asset_evidence import PortfolioSourceAssetEvidence
from app.models.responses import (
    ComparativeAnalyticsBlock,
    ComparativeBreakdownItem,
    PerformanceResponse,
    TWRDailyCalculationEvidence,
)
from app.models.twr_requests import TWRInputMode, TWRResolvedExecutionRequest
from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_TWR
from app.services.calculation_result_access import authorize_calculation_result_access
from app.services.composite_materialization.currency_normalization import normalize_member_money
from app.services.composite_materialization.currency_snapshot_custody import require_fx_snapshot_custody
from app.services.composite_materialization.currency_source_admission import (
    admit_composite_fx_source,
    fx_resolution_for_command,
)
from app.services.core_tenant_authority import admitted_tenant_authority, require_composite_tenant_authority
from app.services.execution_registry import ExecutionRecord, ExecutionStatus, execution_registry
from app.services.reproducibility_service import generate_value_fingerprint
from common.enums import Frequency
from core.errors import APIError
from core.monetary_input import validate_calculated_money_model


def member_outcome(portfolio_id: str, *, code: str, retryable: bool = False) -> CompositeMemberMaterializationOutcome:
    return CompositeMemberMaterializationOutcome(
        portfolio_id=portfolio_id,
        state=CompositeMemberOutcomeState.WAITING if retryable else CompositeMemberOutcomeState.BLOCKED,
        reason_code=code,
        retryable=retryable,
    )


class RetainedCompositeMemberResultSource:
    def __init__(self, *, currency_normalization_wire=None):
        self.currency_normalization_wire = currency_normalization_wire

    def read_member(
        self,
        command: CompositeMaterializationCommand,
        reference: CompositeMemberCalculationReference,
        *,
        tenant_id: str,
        membership_snapshot_id: str,
        request_headers: Mapping[str, str],
    ) -> CompositeMemberMaterializationOutcome:
        tenant_id = require_composite_tenant_authority(admitted_tenant_authority(tenant_id)).tenant_id
        execution = execution_registry.get_execution_for_tenant(reference.calculation_id, tenant_id=tenant_id)
        if execution is None or execution.response_payload is None:
            return member_outcome(reference.portfolio_id, code="PINNED_MEMBER_RESULT_PENDING", retryable=True)
        if authorize_calculation_result_access(execution=execution, headers=request_headers) is not None:
            return member_outcome(reference.portfolio_id, code="MEMBER_RESULT_AUTHORITY_REFUSED")
        reason = _execution_refusal(execution, command=command, reference=reference)
        if reason:
            return member_outcome(reference.portfolio_id, code=reason)
        try:
            response = PerformanceResponse.model_validate(execution.response_payload)
            fact, source_evidence = _verified_member_fact(
                command,
                reference,
                execution=execution,
                response=response,
                membership_snapshot_id=membership_snapshot_id,
                tenant_id=tenant_id,
                currency_normalization_wire=self.currency_normalization_wire,
            )
        except APIError as error:
            return member_outcome(
                reference.portfolio_id,
                code=error.error_code or "MEMBER_FINANCIAL_EVIDENCE_REFUSED",
                retryable=bool(error.retryable),
            )
        except (ValidationError, ValueError, KeyError, TypeError):
            return member_outcome(reference.portfolio_id, code="MEMBER_FINANCIAL_EVIDENCE_REFUSED")
        return CompositeMemberMaterializationOutcome(
            portfolio_id=reference.portfolio_id,
            state=CompositeMemberOutcomeState.READY,
            reason_code="MEMBER_FACT_VERIFIED",
            retryable=False,
            fact=fact,
            source_evidence=source_evidence,
        )


def _execution_refusal(
    execution: ExecutionRecord,
    *,
    command: CompositeMaterializationCommand,
    reference: CompositeMemberCalculationReference,
) -> str | None:
    if execution.analytics_type != ANALYTICS_WORKFLOW_TWR or execution.portfolio_id != reference.portfolio_id:
        return "MEMBER_RESULT_IDENTITY_MISMATCH"
    if execution.status != ExecutionStatus.COMPLETE:
        return "MEMBER_RESULT_NOT_COMPLETE"
    if (execution.input_fingerprint, execution.calculation_hash) != (
        reference.input_fingerprint,
        reference.calculation_hash,
    ):
        return "MEMBER_RESULT_FINGERPRINT_MISMATCH"
    return _fee_view_refusal(execution.request_payload or {}, command)


def _fee_view_refusal(payload: dict, command: CompositeMaterializationCommand) -> str | None:
    resolved = payload.get("resolved_request", payload)
    request = resolved.get("portfolio", resolved)
    expected_basis = command.source_metric_basis
    if request.get("metric_basis", "NET") != expected_basis:
        return "MEMBER_RETURN_VIEW_NOT_SUPPORTED"
    return None


def _verified_member_fact(
    command: CompositeMaterializationCommand,
    reference: CompositeMemberCalculationReference,
    *,
    execution: ExecutionRecord,
    response: PerformanceResponse,
    membership_snapshot_id: str,
    tenant_id: str,
    currency_normalization_wire=None,
) -> tuple[CompositeMemberReturnFact, CompositeMemberSourceEvidence | CompositeNormalizedMemberSourceEvidence]:
    if membership_snapshot_id != command.membership_content_hash:
        raise ValueError("Pinned Manage membership differs from the admitted command")
    _require_result_provenance(command, reference, execution=execution, response=response)
    block, evidence, dates = _exact_period_evidence(command, response)
    return_value = Decimal(str(block.summary.period_return.base)) / Decimal(100)
    _require_linked_result(return_value, evidence)
    source_evidence = _retained_source_evidence(
        command, execution=execution, response=response, period_return=return_value
    )
    _require_reported_asset_projection(source_evidence.source_assets, evidence, dates)
    source_evidence, output_assets, receipt_version = _member_money_evidence(
        command, reference, execution, source_evidence, tenant_id, currency_normalization_wire
    )
    beginning = output_assets.observations[0].beginning_market_value
    ending = output_assets.observations[-1].ending_market_value
    if not beginning.is_finite() or not ending.is_finite() or beginning < 0 or ending < 0:
        raise ValueError("Member asset evidence is not finite nonnegative money")
    receipt_fingerprint, _ = generate_value_fingerprint(source_evidence, receipt_version)
    fact = CompositeMemberReturnFact(
        composite_id=command.composite_id,
        portfolio_id=reference.portfolio_id,
        period_start=command.period_start,
        period_end=command.period_end,
        return_value=return_value,
        return_view=command.return_view,
        beginning_market_value=beginning,
        ending_market_value=ending,
        reporting_currency=command.reporting_currency,
        calculation_id=str(reference.calculation_id),
        source_snapshot_id=receipt_fingerprint,
        source_fingerprint=reference.calculation_hash,
        restatement_version=str(command.materialization_id),
        restatement_sequence=command.restatement_sequence,
    )
    return fact, source_evidence


def _member_money_evidence(command, reference, execution, native, tenant_id, currency_normalization_wire):
    if command.currency_normalization_binding is None:
        return native, native.source_assets, "composite-member-source.v1"
    admitted = admit_composite_fx_source(
        fx_resolution_for_command(command, tenant_id=tenant_id), retained_wire=currency_normalization_wire
    )
    member = next(row for row in admitted.source.members if row.member_id == reference.portfolio_id)
    snapshots = require_fx_snapshot_custody(
        member,
        reporting_currency=command.reporting_currency,
        calculation_id=reference.calculation_id,
        snapshots=[asdict(row) for row in execution.upstream_snapshots if row.upstream_endpoint == "fx_rates"],
    )
    evidence = normalize_member_money(
        command, native, admitted, member_id=reference.portfolio_id, fx_snapshots=snapshots
    )
    return evidence, evidence.normalized_assets, "composite-member-source.v3"


def _retained_source_evidence(
    command: CompositeMaterializationCommand,
    *,
    execution: ExecutionRecord,
    response: PerformanceResponse,
    period_return: Decimal,
) -> CompositeMemberSourceEvidence:
    payload = execution.request_payload or {}
    assets = PortfolioSourceAssetEvidence.model_validate(payload.get("source_asset_evidence"))
    retained_assets = _source_asset_window(command, assets)
    asset_fingerprint, _ = generate_value_fingerprint(retained_assets, "portfolio-source-assets.v1")
    retained_request = validate_calculated_money_model(TWRResolvedExecutionRequest, payload.get("resolved_request"))
    if generate_value_fingerprint(retained_request, response.meta.engine_version) != (
        response.meta.input_fingerprint,
        response.meta.calculation_hash,
    ):
        raise ValueError("Retained engine request does not match calculation identity")
    return CompositeMemberSourceEvidence.model_validate(
        {
            "engine_version": response.meta.engine_version,
            "precision_mode": response.meta.precision_mode,
            "input_fingerprint": response.meta.input_fingerprint,
            "calculation_hash": response.meta.calculation_hash,
            "calculation_request": retained_request,
            "membership_snapshot_id": command.membership_content_hash,
            "asset_evidence_fingerprint": asset_fingerprint,
            "period_return": period_return,
            "source_assets": retained_assets,
            "core_snapshots": [
                {
                    "snapshot_id": item.snapshot_id,
                    "source_identifier": item.source_identifier,
                    "request_as_of_date": item.as_of_date,
                    "request_fingerprint": item.request_fingerprint,
                    "response_fingerprint": item.response_fingerprint,
                    "retrieved_at_utc": item.created_at_utc,
                }
                for item in execution.upstream_snapshots
                if item.upstream_endpoint == "portfolio_timeseries"
            ],
        }
    )


def _source_asset_window(
    command: CompositeMaterializationCommand, assets: PortfolioSourceAssetEvidence
) -> PortfolioSourceAssetEvidence:
    if assets.portfolio_currency != command.reporting_currency and command.currency_normalization_binding is None:
        raise ValueError("Applied asset conversion is not established")
    selected = [
        item for item in assets.observations if command.period_start <= item.valuation_date <= command.period_end
    ]
    if not selected or (selected[0].valuation_date, selected[-1].valuation_date) != (
        command.period_start,
        command.period_end,
    ):
        raise ValueError("Exact source asset window is unavailable")
    return assets.model_copy(update={"observations": selected})


def _require_reported_asset_projection(
    assets: PortfolioSourceAssetEvidence, evidence: list[TWRDailyCalculationEvidence], dates: list[date]
) -> None:
    if [item.valuation_date for item in assets.observations] != dates:
        raise ValueError("Reported and source asset date grains differ")
    for source, reported in zip(assets.observations, evidence, strict=True):
        if reported.portfolio_currency != assets.portfolio_currency:
            raise ValueError("Reported native currency conflicts with source asset evidence")
        _require_projected_money(source.beginning_market_value, reported.begin_mv)
        _require_projected_money(source.ending_market_value, reported.end_mv)


def _require_projected_money(exact: Decimal, projected: object) -> None:
    # Comparison tolerance for the existing public numeric projection only.
    # Fact assets always retain exact source decimals, never the rounded projection.
    reported = Decimal(str(projected))
    tolerance = max(abs(exact) * Decimal("0.000000000000001"), Decimal("0.000000000001"))
    if not reported.is_finite() or abs(exact - reported) > tolerance:
        raise ValueError("Reported assets conflict with retained exact source values")


def _require_result_provenance(
    command: CompositeMaterializationCommand,
    reference: CompositeMemberCalculationReference,
    *,
    execution: ExecutionRecord,
    response: PerformanceResponse,
) -> None:
    if response.calculation_id != reference.calculation_id or response.portfolio_id != reference.portfolio_id:
        raise ValueError("Retained result identity differs")
    if (response.meta.input_fingerprint, response.meta.calculation_hash) != (
        reference.input_fingerprint,
        reference.calculation_hash,
    ):
        raise ValueError("Retained result provenance differs")
    _require_clean_core_quality(response)
    _require_complete_history(response, command=command)
    _require_core_snapshots(execution, portfolio_id=reference.portfolio_id)
    if response.currency_evidence.applied_report_ccy != command.reporting_currency:
        raise ValueError("Applied return currency differs")


def _require_clean_core_quality(response: PerformanceResponse) -> None:
    support = response.calculation_supportability
    quality = support.source_quality_evidence
    if response.input_mode != TWRInputMode.STATEFUL or support.state != "ready" or quality is None:
        raise ValueError("Authoritative Core assets are not established")
    if quality.source_owner != "lotus-core" or quality.quality_state != "clean":
        raise ValueError("Authoritative Core source is not clean")


def _require_complete_history(response: PerformanceResponse, *, command: CompositeMaterializationCommand) -> None:
    coverage = response.calculation_supportability.history_coverage
    if coverage is None or coverage.status != "complete":
        raise ValueError("Complete retained history is required")
    if (coverage.requested_start_date, coverage.requested_end_date) != (command.period_start, command.period_end):
        raise ValueError("Retained history does not bind the fact window")


def _require_core_snapshots(execution: ExecutionRecord, *, portfolio_id: str) -> None:
    snapshots = [item for item in execution.upstream_snapshots if item.upstream_endpoint == "portfolio_timeseries"]
    if not snapshots or any(
        (item.source_identifier, item.retrieval_status) != (portfolio_id, "200") or not item.response_fingerprint
        for item in snapshots
    ):
        raise ValueError("Core valuation source provenance is missing")


def _exact_period_evidence(
    command: CompositeMaterializationCommand,
    response: PerformanceResponse,
) -> tuple[ComparativeAnalyticsBlock, list[TWRDailyCalculationEvidence], list[date]]:
    candidates = []
    for result in response.results_by_period.values():
        rows = result.portfolio.breakdowns.get(Frequency.DAILY, [])
        if _period_matches(rows, command):
            candidates.append((result.portfolio, rows))
    if len(candidates) != 1:
        raise ValueError("A single exact retained period with daily evidence is required")
    block, rows = candidates[0]
    _require_daily_grain(rows)
    return (
        block,
        [_admit_daily_evidence(row.calculation_evidence, command) for row in rows],
        [row.period_start for row in rows],
    )


def _require_daily_grain(rows: list[ComparativeBreakdownItem]) -> None:
    dates = [row.period_start for row in rows]
    if dates != sorted(set(dates)) or any(row.period_start != row.period_end for row in rows):
        raise ValueError("Daily evidence grain is ambiguous")


def _period_matches(rows: list[ComparativeBreakdownItem], command: CompositeMaterializationCommand) -> bool:
    return bool(rows) and (rows[0].period_start, rows[-1].period_end) == (command.period_start, command.period_end)


def _admit_daily_evidence(
    item: TWRDailyCalculationEvidence | None,
    command: CompositeMaterializationCommand,
) -> TWRDailyCalculationEvidence:
    if item is None or item.status != "calculated" or item.linkability_status != "linkable":
        raise ValueError("Unsupported daily linkability")
    # Monetary values are native even when returns are restated; no inferred rates.
    if item.reporting_currency != command.reporting_currency or (
        item.portfolio_currency != command.reporting_currency and command.currency_normalization_binding is None
    ):
        raise ValueError("Applied member asset conversion evidence is unavailable")
    return item


def _require_linked_result(return_value: Decimal, evidence: list[TWRDailyCalculationEvidence]) -> None:
    linked = Decimal(1)
    for item in evidence:
        value = Decimal(str(item.daily_return)) / Decimal(100)
        if not value.is_finite():
            raise ValueError("Nonfinite daily return")
        linked *= Decimal(1) + value
    if not return_value.is_finite() or abs(linked - Decimal(1) - return_value) > Decimal("0.0000000001"):
        raise ValueError("Published return does not reconcile to retained daily evidence")
