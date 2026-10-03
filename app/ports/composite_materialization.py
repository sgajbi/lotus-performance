from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Protocol
from uuid import UUID

from app.models.composite_materialization import (
    CompositeMaterializationCommand,
    CompositeMaterializationState,
    CompositeMemberCalculationReference,
    CompositeMemberMaterializationOutcome,
)
from app.models.composites import CompositeDefinition, CompositeMemberReturnFact, CompositeReturnView
from app.services.composite_materialization.records import MaterializationRecord
from app.services.composite_materialization.source_contract import PinnedCompositeSource
from app.services.compute_job_store import ComputeJobLeaseOwnershipError, ComputeJobRecord, ComputeJobStatus

__all__ = [
    "CompositeMembershipSource",
    "CompositeMemberResultSource",
    "CompositeMaterializationRepository",
    "CompositeFactsRepository",
    "CompositeComputeLeaseReader",
    "MaterializationRecord",
    "ComputeJobLeaseOwnershipError",
    "ComputeJobRecord",
    "ComputeJobStatus",
]


class CompositeMaterializationRepository(Protocol):
    def register(
        self, command: CompositeMaterializationCommand, *, tenant_id: str, actor_id: str
    ) -> MaterializationRecord: ...

    def get(self, materialization_id: UUID, *, tenant_id: str) -> MaterializationRecord: ...

    def save(
        self,
        materialization_id: UUID,
        *,
        tenant_id: str,
        expected_revision: int,
        source: PinnedCompositeSource | None,
        outcomes: list[CompositeMemberMaterializationOutcome],
        state: CompositeMaterializationState,
        reason_code: str | None,
    ) -> MaterializationRecord: ...


class CompositeFactsRepository(Protocol):
    def upsert_definition(self, definition: CompositeDefinition, *, tenant_id: str) -> None: ...

    def upsert_member_return_fact(self, fact: CompositeMemberReturnFact, *, tenant_id: str) -> None: ...

    def complete_member_return_fact_publication(
        self,
        *,
        tenant_id: str,
        composite_id: str,
        return_view: CompositeReturnView,
        reporting_currency: str,
        restatement_sequence: int,
        period_start: date,
        period_end: date,
        expected_families: set[tuple[str, date, date]],
        source_fingerprint: str,
    ) -> None: ...


class CompositeComputeLeaseReader(Protocol):
    def get_job_for_tenant(self, calculation_id: UUID, *, tenant_id: str) -> ComputeJobRecord | None: ...

    def ensure_active_lease_owner(self, calculation_id: UUID, *, worker_id: str | None) -> None: ...


class CompositeMembershipSource(Protocol):
    async def read_pinned(
        self,
        command: CompositeMaterializationCommand,
        *,
        tenant_id: str,
        actor_id: str,
        role: str,
    ) -> PinnedCompositeSource: ...


class CompositeMemberResultSource(Protocol):
    def read_member(
        self,
        command: CompositeMaterializationCommand,
        reference: CompositeMemberCalculationReference,
        *,
        tenant_id: str,
        membership_snapshot_id: str,
        request_headers: Mapping[str, str],
    ) -> CompositeMemberMaterializationOutcome: ...
