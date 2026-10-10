"""Derive common internal TWR semantics from immutable member receipts."""

from typing import NoReturn

from app.models.composite_materialization import (
    CompositeMaterializationCommand,
    CompositeMemberMaterializationOutcome,
    CompositeMemberOutcomeState,
    CompositeMemberSourceEvidence,
)
from app.models.composites import CompositeReturnView
from app.services.composite_materialization.member_evidence_policy import require_member_source_evidence
from app.services.composite_materialization.records import MaterializationRecord
from app.services.composite_materialization.source_contract import ManageCompositeDefinition
from app.services.reproducibility_service import generate_value_fingerprint
from core.errors import APIUnprocessableEntityError


def _refuse(code: str) -> NoReturn:
    raise APIUnprocessableEntityError(
        "Selected internal TWR method evidence is unavailable or incompatible.", error_code=code
    )


def retained_internal_return_method(record: MaterializationRecord) -> dict[str, str]:
    """No provider, FX, or approval authority is inferred from this internal method."""
    _require_internal_window(record)
    common = None
    for outcome in record.outcomes:
        if outcome.state != CompositeMemberOutcomeState.READY:
            continue
        method = _member_method(record.command, outcome)
        if common is not None and common != method:
            _refuse("COMPOSITE_VECTOR_METHOD_MISMATCH")
        common = method
    if common is None:
        _refuse("COMPOSITE_VECTOR_METHOD_UNAVAILABLE")
    return {**common, "method_digest": generate_value_fingerprint(common, "internal-retained-twr-method.v1")[0]}


def _require_internal_window(record: MaterializationRecord) -> None:
    source, command = record.source, record.command
    if (
        source is None
        or not isinstance(source.definition, ManageCompositeDefinition)
        or source.definition.source_authority.member_return_owner != "lotus-performance"
        or source.definition.source_authority.asset_owner != "lotus-core"
        or source.definition.reporting_currency != command.reporting_currency
        or command.return_view != CompositeReturnView.NET_ACTUAL
        or command.currency_normalization_binding is not None
    ):
        _refuse("COMPOSITE_VECTOR_METHOD_UNAVAILABLE")


def _member_method(
    command: CompositeMaterializationCommand, outcome: CompositeMemberMaterializationOutcome
) -> dict[str, str]:
    evidence = outcome.source_evidence
    if not isinstance(evidence, CompositeMemberSourceEvidence):
        _refuse("COMPOSITE_VECTOR_METHOD_UNAVAILABLE")
    require_member_source_evidence(command, outcome)
    request = evidence.calculation_request.portfolio
    if (
        request.metric_basis != "NET"
        or request.currency != command.reporting_currency
        or (request.report_start_date, request.report_end_date) != (command.period_start, command.period_end)
    ):
        _refuse("COMPOSITE_VECTOR_METHOD_MISMATCH")
    policies = request.model_dump(
        mode="json",
        include={"rounding_precision", "annualization", "flags", "fee_effect", "reset_policy", "data_policy"},
    )
    return {
        "methodology": evidence.methodology,
        "engine_version": evidence.engine_version,
        "precision_mode": evidence.precision_mode,
        "metric_basis": request.metric_basis,
        "reporting_currency": request.currency,
        "calendar_digest": generate_value_fingerprint(request.calendar, "internal-twr-calendar.v1")[0],
        "policy_digest": generate_value_fingerprint(policies, "internal-twr-policies.v1")[0],
    }
