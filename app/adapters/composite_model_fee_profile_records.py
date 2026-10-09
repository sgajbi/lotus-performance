"""Immutable method-input catalog within the existing composite schema owner."""

from sqlalchemy import CheckConstraint, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.adapters.composite_schema_policy import POSTGRES_TENANT_ID_CHECK_SQL, SQLITE_TENANT_ID_CHECK_SQL


class ModelFeeProfileBase(DeclarativeBase):
    pass


class CompositeModelFeeProfileModel(ModelFeeProfileBase):
    __tablename__ = "composite_model_fee_profiles"
    __table_args__ = (
        CheckConstraint(SQLITE_TENANT_ID_CHECK_SQL, name="ck_model_fee_profile_tenant").ddl_if(dialect="sqlite"),
        CheckConstraint(POSTGRES_TENANT_ID_CHECK_SQL, name="ck_model_fee_profile_tenant").ddl_if(dialect="postgresql"),
        CheckConstraint(
            "product_name IN ('CompositePeriodicModelFeeProfile', 'CompositeScheduledModelFeeProfile') AND product_version = 'v1'",
            name="ck_model_fee_profile_product",
        ),
        CheckConstraint(
            "length(content_digest) = 71 AND substr(content_digest, 1, 7) = 'sha256:'",
            name="ck_model_fee_profile_digest",
        ),
        UniqueConstraint(
            "tenant_id",
            "composite_id",
            "product_name",
            "product_version",
            "revision",
            "content_digest",
            name="uq_model_fee_profile_binding",
        ),
    )
    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    revision: Mapped[str] = mapped_column(String(128), primary_key=True)
    composite_id: Mapped[str] = mapped_column(String(128), nullable=False)
    product_name: Mapped[str] = mapped_column(String(64), nullable=False)
    product_version: Mapped[str] = mapped_column(String(32), nullable=False)
    content_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    profile_json: Mapped[str] = mapped_column(Text, nullable=False)
    published_by: Mapped[str] = mapped_column(String(128), nullable=False)
    published_at_utc: Mapped[str] = mapped_column(String(64), nullable=False)
