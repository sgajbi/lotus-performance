"""Nonfinancial capture descriptors owned by CompositeMetadataStore."""

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class CandidateBase(DeclarativeBase):
    pass


class CompositeResultCandidateModel(CandidateBase):
    __tablename__ = "composite_result_candidates"
    __table_args__ = (
        UniqueConstraint("calculation_id", name="uq_composite_candidate_original_result"),
        UniqueConstraint("tenant_id", "semantic_request_digest", name="uq_composite_candidate_semantic_request"),
    )
    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    calculation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    composite_id: Mapped[str] = mapped_column(String(128), nullable=False)
    semantic_request_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    semantic_response_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    original_response_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    build_commit: Mapped[str] = mapped_column(String(40), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(128), nullable=False)
    methodology: Mapped[str] = mapped_column(String(128), nullable=False)
    materialization_vector_json: Mapped[str] = mapped_column(Text, nullable=False)
    member_scope_json: Mapped[str] = mapped_column(Text, nullable=False)
    captured_by: Mapped[str] = mapped_column(String(128), nullable=False)
    principal_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    credential_id: Mapped[str] = mapped_column(String(128), nullable=False)
    delegated_actor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    captured_at_utc: Mapped[str] = mapped_column(String(40), nullable=False)
