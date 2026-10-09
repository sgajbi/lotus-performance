"""Bind v2 selections to the genuine shipped internal member receipt."""

from app.models.composite_materialization import (
    CompositeModelFeeMemberEvidence,
    CompositeNormalizedMemberSourceEvidence,
    CompositeScheduledModelFeeMemberEvidence,
)
from app.services.composite_materialization.authority_policy import authority_refusal, selection_for_window
from app.services.reproducibility_service import generate_value_fingerprint


def require_internal_selection_bindings(definition, command, reference, evidence, *, facts):
    if isinstance(evidence, (CompositeModelFeeMemberEvidence, CompositeScheduledModelFeeMemberEvidence)):
        evidence = evidence.gross_evidence
    if isinstance(evidence, CompositeNormalizedMemberSourceEvidence):
        evidence = evidence.native_evidence
    if reference is None or evidence is None:
        raise authority_refusal("COMPOSITE_INTERNAL_RECEIPT_REQUIRED")
    receipt_digest = generate_value_fingerprint(evidence, "composite-member-source.v1")[0]
    if (evidence.input_fingerprint, evidence.calculation_hash) != (
        reference.input_fingerprint,
        reference.calculation_hash,
    ):
        raise authority_refusal("COMPOSITE_INTERNAL_RECEIPT_BINDING_MISMATCH")
    for fact in facts:
        selection = selection_for_window(
            definition,
            member_id=reference.portfolio_id,
            fact=fact,
            period_start=command.period_start,
            period_end=command.period_end,
        )
        # This product label identifies existing retained evidence, not a new published API.
        if (
            selection.source_product,
            selection.source_contract_version,
            selection.source_revision,
            selection.source_digest,
            selection.source_watermark,
            selection.source_cut_id,
        ) != (
            "CompositeMemberSourceEvidence",
            "composite-member-source.v1",
            str(reference.calculation_id),
            receipt_digest,
            evidence.input_fingerprint,
            command.source_cut_id,
        ):
            raise authority_refusal("COMPOSITE_INTERNAL_RECEIPT_BINDING_MISMATCH")
