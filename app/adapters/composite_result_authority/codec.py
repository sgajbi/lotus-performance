"""Rehydrate and verify nonfinancial receipts without repairing retained history."""

import json

from app.adapters.composite_result_authority.vector import custody_refused
from app.models.composite_authority import authority_digest
from app.models.composite_result_authority import (
    AuthorityApprovalResponse,
    AuthorityDecisionResponse,
    AuthorityProposalResponse,
    AuthoritySelection,
)


def wire(value):
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def digest(value):
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return authority_digest(value)


def proposal_response(row):
    try:
        result = AuthorityProposalResponse.model_validate_json(row.response_json)
        expected = digest(result.model_dump(mode="json", exclude={"proposal_digest"}))
        if (
            expected != result.proposal_digest
            or expected != row.content_digest
            or str(result.proposal_id) != row.proposal_id
        ):
            custody_refused()
        return result
    except (ValueError, TypeError, KeyError):
        custody_refused()


def approval_response(row):
    try:
        result = AuthorityApprovalResponse.model_validate_json(row.response_json)
        if (
            str(result.approval_id) != row.approval_id
            or str(result.proposal_id) != row.proposal_id
            or result.evidence_digest != digest({"financial_evidence": row.financial_evidence})
        ):
            custody_refused()
        return result
    except (ValueError, TypeError, KeyError):
        custody_refused()


def decision_response(row):
    try:
        result = AuthorityDecisionResponse.model_validate_json(row.response_json)
        if digest(result) != row.receipt_digest or (
            str(result.decision_id),
            str(result.proposal_id),
            str(result.approval_id),
        ) != (row.decision_id, row.proposal_id, row.approval_id):
            custody_refused()
        if snapshot_token(result) != result.snapshot_token:
            custody_refused()
        for selection in result.selections:
            _retained_selection(selection)
        return result
    except (ValueError, TypeError, KeyError):
        custody_refused()


def snapshot_token(receipt):
    content = receipt.model_dump(mode="json", exclude={"snapshot_token"})
    return f"authority:v1:{receipt.decision_id}:{digest(content).removeprefix('sha256:')}"


def selection_response(row):
    try:
        result = _retained_selection(AuthoritySelection.model_validate_json(row.selection_json))
        if (result.scope.scope_id, result.revision, str(result.candidate_id)) != (
            row.scope_id,
            row.revision,
            row.candidate_id,
        ):
            custody_refused()
        return result
    except (ValueError, TypeError, KeyError):
        custody_refused()


def _retained_selection(selection):
    if selection.frozen and selection.current_use == "STALE":
        custody_refused()
    return selection
