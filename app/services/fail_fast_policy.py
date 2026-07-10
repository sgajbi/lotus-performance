from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal, cast

from app.models.attribution_responses import AttributionResponse
from app.models.contribution_responses import ContributionResponse
from app.models.mwr_responses import MoneyWeightedReturnResponse
from app.models.responses import PerformanceResponse
from app.services.error_details import coded_error_detail
from core.errors import APIUnprocessableEntityError

CoreAnalyticsOperation = Literal["twr", "mwr", "contribution", "attribution"]

FAIL_FAST_SOFT_WARNING = "FAIL_FAST_SOFT_WARNING"
_FAIL_FAST_MESSAGE = (
    "flags.fail_fast=true rejected a completed analytics response because warning or degraded "
    "supportability evidence was present."
)
_FAIL_FAST_REMEDIATION = (
    "Review the returned condition codes with fail_fast=false, correct the degraded input or request posture, "
    "then resubmit with fail_fast=true."
)


@dataclass(frozen=True)
class FailFastCondition:
    source: str
    code: str
    message: str

    def as_payload(self) -> dict[str, str]:
        return {
            "source": self.source,
            "code": self.code,
            "message": self.message,
        }


def enforce_core_analytics_fail_fast(
    *,
    operation: CoreAnalyticsOperation,
    request: Any,
    response: PerformanceResponse | MoneyWeightedReturnResponse | ContributionResponse | AttributionResponse,
) -> None:
    """Reject completed core analytics responses when strict fail-fast was requested."""
    if not _request_fail_fast(request):
        return

    conditions = _fail_fast_conditions(operation=operation, response=response)
    if not conditions:
        return

    detail: dict[str, Any] = coded_error_detail(
        code=FAIL_FAST_SOFT_WARNING,
        message=_FAIL_FAST_MESSAGE,
        retryable=False,
        remediation_hint=_FAIL_FAST_REMEDIATION,
    )
    detail["operation"] = operation
    detail["conditions"] = [condition.as_payload() for condition in conditions]
    raise APIUnprocessableEntityError(detail=detail, error_code=FAIL_FAST_SOFT_WARNING)


def _request_fail_fast(request: Any) -> bool:
    flags = getattr(request, "flags", None)
    return bool(getattr(flags, "fail_fast", False))


def _fail_fast_conditions(
    *,
    operation: CoreAnalyticsOperation,
    response: PerformanceResponse | MoneyWeightedReturnResponse | ContributionResponse | AttributionResponse,
) -> list[FailFastCondition]:
    common = _supportability_conditions(response)
    if operation == "twr":
        return [*common, *_twr_conditions(cast(PerformanceResponse, response))]
    if operation == "mwr":
        return [*common, *_mwr_conditions(cast(MoneyWeightedReturnResponse, response))]
    if operation == "contribution":
        return [*common, *_contribution_conditions(cast(ContributionResponse, response))]
    return [*common, *_attribution_conditions(cast(AttributionResponse, response))]


def _supportability_conditions(response: Any) -> list[FailFastCondition]:
    supportability = getattr(response, "calculation_supportability", None)
    if supportability is None or getattr(supportability, "state", "ready") == "ready":
        return []
    return [
        FailFastCondition(
            source="calculation_supportability.state",
            code=str(supportability.state),
            message=f"Calculation supportability state is {supportability.state}.",
        )
    ]


def _twr_conditions(response: PerformanceResponse) -> list[FailFastCondition]:
    return [
        *_twr_benchmark_conditions(response),
        *_twr_source_quality_conditions(response),
        *_twr_daily_calculation_conditions(response),
    ]


def _twr_benchmark_conditions(response: PerformanceResponse) -> list[FailFastCondition]:
    benchmark_evidence = (
        response.benchmark_context.supportability_evidence if response.benchmark_context is not None else None
    )
    if benchmark_evidence is None:
        return []
    return _code_conditions(
        source="benchmark_context.supportability_evidence.warning_codes",
        codes=benchmark_evidence.warning_codes,
        message_prefix="TWR benchmark supportability warning",
    )


def _twr_source_quality_conditions(response: PerformanceResponse) -> list[FailFastCondition]:
    source_quality = getattr(response.calculation_supportability, "source_quality_evidence", None)
    if source_quality is None:
        return []
    return _code_conditions(
        source="calculation_supportability.source_quality_evidence.warnings",
        codes=getattr(source_quality, "warnings", []),
        message_prefix="TWR source-quality warning",
    )


def _twr_daily_calculation_conditions(response: PerformanceResponse) -> list[FailFastCondition]:
    conditions: list[FailFastCondition] = []
    for period_name, period_result in response.results_by_period.items():
        for frequency, rows in period_result.portfolio.breakdowns.items():
            for row in rows:
                evidence = row.calculation_evidence
                if evidence is None:
                    continue
                conditions.extend(
                    _code_conditions(
                        source=f"results_by_period.{period_name}.portfolio.breakdowns.{frequency}.calculation_evidence.warnings",
                        codes=evidence.warnings,
                        message_prefix="TWR daily calculation warning",
                    )
                )
    return conditions


def _mwr_conditions(response: MoneyWeightedReturnResponse) -> list[FailFastCondition]:
    conditions = _code_conditions(
        source="warnings",
        codes=response.warnings,
        message_prefix="MWR warning",
    )
    if response.status in {"FALLBACK_USED", "NOT_CALCULABLE"}:
        conditions.append(
            FailFastCondition(
                source="status",
                code=response.status,
                message=f"MWR completed with status {response.status}.",
            )
        )
    if response.fallback_from is not None:
        conditions.append(
            FailFastCondition(
                source="fallback_from",
                code="FALLBACK_METHOD_USED",
                message=f"MWR fell back from {response.fallback_from}.",
            )
        )
    return conditions


def _contribution_conditions(response: ContributionResponse) -> list[FailFastCondition]:
    conditions: list[FailFastCondition] = []
    conditions.extend(
        _note_conditions(
            source="diagnostics.notes",
            notes=response.diagnostics.notes,
            message_prefix="Contribution diagnostic warning",
        )
    )
    source_economics = response.source_economics_evidence
    if source_economics.status == "SOURCE_LIMITED":
        conditions.append(
            FailFastCondition(
                source="source_economics_evidence.status",
                code="SOURCE_LIMITED",
                message="Contribution source-economics evidence is source-limited.",
            )
        )
    conditions.extend(
        _code_conditions(
            source="source_economics_evidence.degraded_economics",
            codes=source_economics.degraded_economics,
            message_prefix="Contribution degraded source-economics family",
        )
    )
    for period_name, period_result in response.results_by_period.items():
        smoothing = period_result.smoothing_evidence
        if smoothing is not None and smoothing.status == "INVALID_DOMAIN_FALLBACK":
            conditions.append(
                FailFastCondition(
                    source=f"results_by_period.{period_name}.smoothing_evidence.status",
                    code=smoothing.status,
                    message="Contribution smoothing used an invalid-domain fallback.",
                )
            )
    return conditions


def _attribution_conditions(response: AttributionResponse) -> list[FailFastCondition]:
    conditions: list[FailFastCondition] = []
    for period_name, period_result in response.results_by_period.items():
        if period_result.status != "valid":
            conditions.append(
                FailFastCondition(
                    source=f"results_by_period.{period_name}.status",
                    code=period_result.status,
                    message=f"Attribution period {period_name} completed with status {period_result.status}.",
                )
            )
        conditions.extend(
            FailFastCondition(
                source=f"results_by_period.{period_name}.reasons",
                code=reason.code,
                message=f"Attribution {reason.severity} reason {reason.code} was emitted.",
            )
            for reason in period_result.reasons
            if reason.severity in {"warning", "error"}
        )
        residual_classification = period_result.reconciliation.residual_materiality.classification
        if residual_classification in {"watch", "material"}:
            conditions.append(
                FailFastCondition(
                    source=f"results_by_period.{period_name}.reconciliation.residual_materiality.classification",
                    code=residual_classification,
                    message=f"Attribution residual materiality is {residual_classification}.",
                )
            )
    return conditions


def _code_conditions(*, source: str, codes: Iterable[Any], message_prefix: str) -> list[FailFastCondition]:
    return [
        FailFastCondition(
            source=source,
            code=str(code),
            message=f"{message_prefix}: {code}.",
        )
        for code in codes
        if str(code).strip()
    ]


def _note_conditions(*, source: str, notes: Iterable[str], message_prefix: str) -> list[FailFastCondition]:
    return [
        FailFastCondition(
            source=source,
            code="DIAGNOSTIC_NOTE",
            message=f"{message_prefix}: {note}",
        )
        for note in notes
        if note.strip()
    ]
