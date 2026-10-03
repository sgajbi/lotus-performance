from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.adapters.composite_member_result_source import member_outcome
from app.models.composite_materialization import (
    CompositeMaterializationCommand,
    CompositeMemberMaterializationOutcome,
    CompositeMemberSourceEvidence,
)
from app.models.composites import CompositeMemberReturnFact, CompositeReturnView
from app.models.requests import PerformanceRequest
from app.models.twr_requests import TWRResolvedExecutionRequest
from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_COMPOSITE_MATERIALIZATION
from app.services.composite_materialization.source_contract import admit_pinned_source, source_digest
from app.services.reproducibility_service import generate_value_fingerprint


def source_products(*, tenant_id="tenant-a", posture="COMPLETE", composite_id="COMPOSITE"):
    definition = {
        "product_name": "CompositeDefinition",
        "product_version": "v1",
        "tenant_id": tenant_id,
        "composite_id": composite_id,
        "definition_version": "d1",
        "display_name": "Balanced composite",
        "strategy_code": "BALANCED",
        "reporting_currency": "USD",
        "inception_date": "2026-01-01",
        "termination_date": None,
        "calculation_method": "ASSET_WEIGHTED",
        "eligibility_policy_version": "policy.v1",
        "source_authority": {
            "definition_owner": "lotus-manage",
            "membership_owner": "lotus-manage",
            "member_return_owner": "lotus-performance",
            "asset_owner": "lotus-core",
            "benchmark_owner": "lotus-core",
            "policy_version": "composite-source-authority.v1",
        },
        "created_at": "2026-01-01T00:00:00Z",
        "created_by": "manage-operator",
        "correlation_id": "definition-receipt",
    }
    definition["content_hash"] = source_digest(definition)
    membership = {
        "product_name": "CompositeMembership",
        "product_version": "v1",
        "tenant_id": tenant_id,
        "composite_id": composite_id,
        "definition_version": "d1",
        "membership_revision": "m1",
        "policy_version": "policy.v1",
        "source_cut_id": "cut1",
        "decisions": [
            {
                "portfolio_id": member,
                "effective_from": "2026-01-01",
                "effective_to": None,
                "status": "INCLUDED",
                "reason_code": None,
                "discretionary": True,
                "approval_ref": None,
                "source_snapshot_id": "membership-" + member,
            }
            for member in ("A", "B", "C")
        ],
        "decided_at": "2026-01-01T01:00:00Z",
        "decided_by": "manage-operator",
        "correlation_id": "membership-receipt",
        "supersedes_membership_revision": None,
        "affected_from": None,
        "affected_to": None,
    }
    membership["content_hash"] = source_digest(membership)
    attestation = {
        "product_name": "CompositeUniverseAttestation",
        "product_version": "v1",
        "tenant_id": tenant_id,
        "composite_id": composite_id,
        "definition_version": "d1",
        "membership_revision": "m1",
        "membership_content_hash": membership["content_hash"],
        "attestation_version": "u1",
        "coverage_from": "2026-01-01",
        "coverage_to": "2026-01-31",
        "policy_version": "policy.v1",
        "source_cut_id": "cut1",
        "source_products": [
            {
                "owner_service": "lotus-manage",
                "product_name": "UniverseFixture",
                "contract_version": "v1",
                "authority_scope": "AUTHORITATIVE_UNIVERSE",
                "source_cut_id": "cut1",
                "source_watermark": "2026-01-01T00:00:00Z",
                "content_hash": "sha256:" + "a" * 64,
            }
        ],
        "posture": posture,
        "expected_portfolio_ids": ["A", "B", "C"],
        "expected_portfolio_count": 3,
        "observed_portfolio_count": 3,
        "missing_portfolio_ids": [],
        "unexpected_portfolio_ids": [],
        "coverage_gap_portfolio_ids": [],
        "reason_code": None,
        "attested_at": "2026-01-01T02:00:00Z",
        "attested_by": "manage-attester",
        "correlation_id": "universe-receipt",
    }
    attestation["content_hash"] = source_digest(attestation)
    return definition, membership, attestation


def controlled_member_request(member, calculation_id, *, corrected=False):
    beginning, ret = controlled_member_figures(member, corrected=corrected)
    return TWRResolvedExecutionRequest(
        portfolio=PerformanceRequest.model_validate(
            {
                "calculation_id": calculation_id,
                "portfolio_id": member,
                "performance_start_date": "2026-01-01",
                "report_start_date": "2026-01-05",
                "report_end_date": "2026-01-05",
                "metric_basis": "NET",
                "analyses": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
                "valuation_points": [
                    {"perf_date": "2026-01-05", "begin_mv": beginning, "end_mv": beginning * (1 + ret)}
                ],
            }
        )
    )


def controlled_member_figures(member, *, corrected=False):
    values = {"A": ("100", "0.20" if corrected else "0.10"), "B": ("200", "0.05"), "C": ("300", "-0.02")}
    beginning, ret = values[member]
    return Decimal(beginning), Decimal(ret)


def controlled_member_reference(member, *, corrected=False):
    calculation_id = uuid4()
    request = controlled_member_request(member, calculation_id, corrected=corrected)
    fingerprint, calculation_hash = generate_value_fingerprint(request, "controlled-test-v1")
    return {
        "portfolio_id": member,
        "calculation_id": str(calculation_id),
        "input_fingerprint": fingerprint,
        "calculation_hash": calculation_hash,
    }


def command_for(products=None, *, corrected=False, **changes):
    definition, membership, attestation = products or source_products()
    return CompositeMaterializationCommand.model_validate(
        {
            "composite_id": definition["composite_id"],
            "definition_version": "d1",
            "definition_content_hash": definition["content_hash"],
            "membership_revision": "m1",
            "membership_content_hash": membership["content_hash"],
            "attestation_version": "u1",
            "attestation_content_hash": attestation["content_hash"],
            "source_cut_id": "cut1",
            "policy_version": "policy.v1",
            "period_start": "2026-01-05",
            "period_end": "2026-01-05",
            "reporting_currency": "USD",
            "restatement_sequence": 1,
            "member_calculations": [
                controlled_member_reference(member, corrected=corrected) for member in ("A", "B", "C")
            ],
            **changes,
        }
    )


def admitted(command, products=None, tenant_id="tenant-a"):
    definition, membership, attestation = products or source_products(tenant_id=tenant_id)
    return admit_pinned_source(
        command=command, tenant_id=tenant_id, definition=definition, membership=membership, attestation=attestation
    )


INVALID_MATERIALIZATION_DATABASE_WRITES = (
    ("tenant_id", ""),
    ("tenant_id", " tenant-a "),
    ("tenant_id", "\u00a0tenant-a\u00a0"),
    ("reporting_currency", "usd"),
    ("reporting_currency", "U\u015aD"),
    ("return_view", "NET_MODEL_FEE"),
    ("restatement_sequence", "0"),
    ("restatement_sequence", "1.5"),
    ("revision", -1),
    ("period_end", "2026-01-04"),
    ("period_start", "2026-02-30"),
    ("state", "PARTIAL_BUT_READY"),
)


class MembershipSource:
    """Controlled source port; not certification of an upstream authority."""

    def __init__(self, source):
        self.source = source
        self.reads = 0

    async def read_pinned(self, command, *, tenant_id, actor_id, role):
        self.reads += 1
        assert self.source.definition.tenant_id == tenant_id
        return self.source


class MemberSource:
    def __init__(self, *, missing=None, corrected=False):
        self.missing = missing
        self.corrected = corrected
        self.reads = []

    def read_member(self, command, reference, *, tenant_id, membership_snapshot_id, request_headers):
        self.reads.append(reference.portfolio_id)
        if reference.portfolio_id == self.missing:
            return member_outcome(reference.portfolio_id, code="PINNED_MEMBER_RESULT_PENDING", retryable=True)
        beginning, ret = controlled_member_figures(reference.portfolio_id, corrected=self.corrected)
        request = controlled_member_request(reference.portfolio_id, reference.calculation_id, corrected=self.corrected)
        assets = {
            "portfolio_currency": "USD",
            "observations": [
                {
                    "valuation_date": "2026-01-05",
                    "beginning_market_value": str(beginning),
                    "ending_market_value": str(beginning * (1 + ret)),
                }
            ],
        }
        from app.models.portfolio_asset_evidence import PortfolioSourceAssetEvidence

        asset_fingerprint, _ = generate_value_fingerprint(
            PortfolioSourceAssetEvidence.model_validate(assets), "portfolio-source-assets.v1"
        )
        evidence = CompositeMemberSourceEvidence.model_validate(
            {
                "engine_version": "controlled-test-v1",
                "precision_mode": "FLOAT64",
                "input_fingerprint": reference.input_fingerprint,
                "calculation_hash": reference.calculation_hash,
                "calculation_request": request,
                "membership_snapshot_id": membership_snapshot_id,
                "asset_evidence_fingerprint": asset_fingerprint,
                "period_return": ret,
                "source_assets": assets,
                "core_snapshots": [
                    {
                        "snapshot_id": "controlled-core-" + reference.portfolio_id,
                        "source_identifier": reference.portfolio_id,
                        "request_as_of_date": "2026-01-05",
                        "request_fingerprint": "a" * 64,
                        "response_fingerprint": "b" * 64,
                        "retrieved_at_utc": "2026-01-06T00:00:00Z",
                    }
                ],
            }
        )
        receipt_fingerprint, _ = generate_value_fingerprint(evidence, "composite-member-source.v1")
        fact = CompositeMemberReturnFact(
            composite_id=command.composite_id,
            portfolio_id=reference.portfolio_id,
            period_start=command.period_start,
            period_end=command.period_end,
            beginning_market_value=beginning,
            ending_market_value=beginning * (1 + ret),
            return_value=ret,
            return_view=command.return_view,
            reporting_currency="USD",
            calculation_id=str(reference.calculation_id),
            source_snapshot_id=receipt_fingerprint,
            source_fingerprint=reference.calculation_hash,
            restatement_version=str(command.materialization_id),
            restatement_sequence=command.restatement_sequence,
        )
        return CompositeMemberMaterializationOutcome(
            portfolio_id=reference.portfolio_id,
            state="READY",
            reason_code="MEMBER_FACT_VERIFIED",
            retryable=False,
            fact=fact,
            source_evidence=evidence,
        )


def running_job(jobs, command, *, tenant_id="tenant-a"):
    jobs.register_job(
        calculation_id=command.calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_COMPOSITE_MATERIALIZATION,
        tenant_id=tenant_id,
        request_payload={
            "command": command.model_dump(mode="json"),
            "actor_id": "operator",
            "role": "DPM_COMPOSITE_CONSUMER",
            "authority": {"x-tenant-id": tenant_id},
        },
    )
    jobs.lease_pending_jobs(worker_id="worker-a", lease_seconds=60, limit=1)
    jobs.mark_running(command.calculation_id, worker_id="worker-a", lease_seconds=60)
    return jobs.get_job_for_tenant(command.calculation_id, tenant_id=tenant_id)


def facts_for(facts, *, sequence=None, tenant_id="tenant-a"):
    return facts.list_member_return_facts(
        tenant_id=tenant_id,
        composite_id="COMPOSITE",
        period_start=date(2026, 1, 5),
        period_end=date(2026, 1, 5),
        return_view=CompositeReturnView.NET_ACTUAL,
        reporting_currency="USD",
        restatement_sequence=sequence,
    )
