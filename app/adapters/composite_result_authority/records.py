"""Bounded pointers plus indexed append-only workflow history, without economics."""

from datetime import date

from sqlalchemy import CheckConstraint, Date, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.adapters.composite_schema_policy import POSTGRES_TENANT_ID_CHECK_SQL, SQLITE_TENANT_ID_CHECK_SQL


class AuthorityBase(DeclarativeBase):
    pass


class ProposalRow(AuthorityBase):
    __tablename__ = "composite_authority_proposals"
    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    proposal_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    content_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    response_json: Mapped[str] = mapped_column(Text, nullable=False)


class ApprovalRow(AuthorityBase):
    __tablename__ = "composite_authority_approvals"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "proposal_id"],
            ["composite_authority_proposals.tenant_id", "composite_authority_proposals.proposal_id"],
        ),
        UniqueConstraint("tenant_id", "proposal_id", name="uq_composite_authority_approval_proposal"),
    )
    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    approval_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    proposal_id: Mapped[str] = mapped_column(String(36), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    response_json: Mapped[str] = mapped_column(Text, nullable=False)
    financial_evidence: Mapped[str] = mapped_column(Text, nullable=False)
    checker_json: Mapped[str] = mapped_column(Text, nullable=False)


class ProposalScopeRow(AuthorityBase):
    __tablename__ = "composite_authority_proposal_scopes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "proposal_id"],
            ["composite_authority_proposals.tenant_id", "composite_authority_proposals.proposal_id"],
        ),
        Index("ix_composite_authority_pending_scope", "tenant_id", "scope_id", "observed_revision"),
        CheckConstraint("observed_revision >= 0", name="ck_composite_authority_observed_revision"),
    )
    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    proposal_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scope_id: Mapped[str] = mapped_column(String(71), primary_key=True)
    observed_revision: Mapped[int] = mapped_column(Integer, nullable=False)


class DecisionRow(AuthorityBase):
    __tablename__ = "composite_authority_decisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "proposal_id"],
            ["composite_authority_proposals.tenant_id", "composite_authority_proposals.proposal_id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "approval_id"],
            ["composite_authority_approvals.tenant_id", "composite_authority_approvals.approval_id"],
        ),
        UniqueConstraint("tenant_id", "proposal_id", name="uq_composite_authority_decision_proposal"),
    )
    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    decision_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    proposal_id: Mapped[str] = mapped_column(String(36), nullable=False)
    approval_id: Mapped[str] = mapped_column(String(36), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    receipt_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    response_json: Mapped[str] = mapped_column(Text, nullable=False)


class RevisionRow(AuthorityBase):
    __tablename__ = "composite_authority_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "decision_id"],
            ["composite_authority_decisions.tenant_id", "composite_authority_decisions.decision_id"],
        ),
        CheckConstraint("revision >= 1", name="ck_composite_authority_history_revision"),
        Index("ix_composite_authority_history_candidate", "tenant_id", "scope_id", "candidate_id"),
    )
    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    scope_id: Mapped[str] = mapped_column(String(71), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    candidate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    selection_json: Mapped[str] = mapped_column(Text, nullable=False)


class ScopeRow(AuthorityBase):
    __tablename__ = "composite_authority_scopes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "scope_id", "revision"],
            [
                "composite_authority_revisions.tenant_id",
                "composite_authority_revisions.scope_id",
                "composite_authority_revisions.revision",
            ],
        ),
        CheckConstraint("revision >= 1", name="ck_composite_authority_scope_revision"),
        CheckConstraint("period_end >= period_start", name="ck_composite_authority_scope_period"),
        Index("ix_composite_authority_scope_overlap", "tenant_id", "base_id", "period_start", "period_end"),
        Index("ix_composite_authority_scope_bundle", "tenant_id", "bundle_id"),
    )
    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    scope_id: Mapped[str] = mapped_column(String(71), primary_key=True)
    base_id: Mapped[str] = mapped_column(String(71), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    bundle_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


for _table in AuthorityBase.metadata.tables.values():
    for _dialect, _predicate in (("sqlite", SQLITE_TENANT_ID_CHECK_SQL), ("postgresql", POSTGRES_TENANT_ID_CHECK_SQL)):
        _table.append_constraint(CheckConstraint(_predicate, name=f"ck_{_table.name}_tenant").ddl_if(dialect=_dialect))
