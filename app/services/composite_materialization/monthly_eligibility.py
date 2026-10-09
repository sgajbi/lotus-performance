"""Compare actual recurring publication wires; no financial rules or custody ledger."""

from datetime import date, datetime

from app.models.composite_eligibility_evidence import _month_window
from app.models.composite_monthly_eligibility_evidence import CompositeMonthlyEligibilityPublicationReceipt
from core.errors import APIUnprocessableEntityError


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise APIUnprocessableEntityError(detail="Pinned monthly publication failed admission.", error_code=code)


def admit_monthly_publication_graph(source, receipt: CompositeMonthlyEligibilityPublicationReceipt) -> None:
    proposal = receipt.approval.proposal
    _require(
        receipt.definition.model_dump() == source.wire_evidence.definition,
        "COMPOSITE_ELIGIBILITY_FINAL_DEFINITION_MISMATCH",
    )
    expected = [
        item.model_dump()
        for item in proposal.universe.source_products
        if not (item.owner_service == "lotus-manage" and item.product_name == "CompositeMonthlyEvaluationApproval")
    ]
    expected.append(
        {
            "owner_service": "lotus-manage",
            "product_name": receipt.approval.product_name,
            "contract_version": "v1",
            "authority_scope": "POLICY_INPUT",
            "source_cut_id": receipt.source_cut_id,
            "source_watermark": proposal.evaluation_revision,
            "content_hash": receipt.approval.content_hash,
        }
    )
    expected.sort(
        key=lambda item: (item["owner_service"], item["product_name"], item["contract_version"], item["source_cut_id"])
    )
    _require(
        source.wire_evidence.attestation["source_products"] == expected,
        "COMPOSITE_ELIGIBILITY_PUBLISHED_SOURCE_PRODUCTS_MISMATCH",
    )
    _require(
        source.attestation.expected_portfolio_ids == proposal.observations.expected_portfolio_ids
        and source.attestation.observed_portfolio_count == proposal.evaluation.observed_count,
        "COMPOSITE_ELIGIBILITY_PUBLICATION_MEMBER_MISMATCH",
    )
    _admit_monthly_membership(source, receipt)


def _admit_monthly_membership(source, receipt: CompositeMonthlyEligibilityPublicationReceipt) -> None:
    approval = receipt.approval
    proposal = approval.proposal
    first, last = _month_window(proposal.observations.month)
    membership = source.membership
    _require(
        (
            membership.supersedes_membership_revision,
            membership.affected_from.isoformat() if membership.affected_from else None,
            membership.affected_to.isoformat() if membership.affected_to else None,
            membership.decided_by,
            membership.decided_at,
            membership.correlation_id,
        )
        == (
            proposal.parent_membership_revision,
            first,
            last,
            approval.approved_by,
            datetime.fromisoformat(approval.approved_at),
            proposal.correlation_id,
        ),
        "COMPOSITE_MONTHLY_MEMBERSHIP_PUBLICATION_MISMATCH",
    )
    _admit_affected_decisions(source, receipt, first, last)


def _admit_affected_decisions(source, receipt, first: str, last: str) -> None:
    proposal = receipt.approval.proposal
    actual = _affected_decision_map(source, first, last)
    _require(len(actual) == len(proposal.evaluation.portfolios), "COMPOSITE_MONTHLY_DECISION_POPULATION_MISMATCH")
    observations = {item.portfolio_id: item for item in proposal.observations.portfolios}
    for result in proposal.evaluation.portfolios:
        decision = actual.get(result.portfolio_id)
        observation = observations.get(result.portfolio_id)
        if decision is None:
            _require(False, "COMPOSITE_MONTHLY_DECISION_POPULATION_MISMATCH")
        if observation is None or observation.discretionary is None:
            _require(False, "COMPOSITE_MONTHLY_DISCRETIONARY_FACT_UNAVAILABLE")
        _admit_decision(decision, observation, result, receipt, first, last)


def _affected_decision_map(source, first: str, last: str):
    affected = [
        item
        for item in source.membership.decisions
        if item.effective_from <= date.fromisoformat(last)
        and (item.effective_to is None or item.effective_to >= date.fromisoformat(first))
    ]
    actual = {item.portfolio_id: item for item in affected}
    _require(len(actual) == len(affected), "COMPOSITE_MONTHLY_DECISION_POPULATION_MISMATCH")
    return actual


def _decision_reason(result) -> str | None:
    if result.status == "INCLUDED":
        return None
    reasons = [
        reason
        for assessment in result.assessments
        for reason in (assessment.failure_reasons if result.status == "EXCLUDED" else assessment.unknown_reasons)
    ]
    return reasons[0] if reasons else None


def _admit_decision(decision, observation, result, receipt, first: str, last: str) -> None:
    _require(
        (
            decision.status,
            decision.reason_code,
            decision.discretionary,
            decision.source_snapshot_id,
            decision.approval_ref,
            decision.effective_from.isoformat(),
            decision.effective_to.isoformat() if decision.effective_to else None,
        )
        == (
            result.status,
            _decision_reason(result),
            observation.discretionary,
            receipt.approval.proposal.evaluation.content_hash,
            receipt.approval.claims_digest,
            first,
            last,
        ),
        "COMPOSITE_ELIGIBILITY_PUBLISHED_DECISION_MISMATCH",
    )
