"""Persistence-independent snapshot returned by the materialization ledger port."""

from dataclasses import dataclass

from app.models.composite_materialization import (
    CompositeMaterializationCommand,
    CompositeMaterializationState,
    CompositeMemberMaterializationOutcome,
)
from app.services.composite_materialization.source_contract import PinnedCompositeSource


@dataclass(frozen=True)
class MaterializationRecord:
    command: CompositeMaterializationCommand
    actor_id: str
    source: PinnedCompositeSource | None
    outcomes: list[CompositeMemberMaterializationOutcome]
    state: CompositeMaterializationState
    reason_code: str | None
    revision: int
