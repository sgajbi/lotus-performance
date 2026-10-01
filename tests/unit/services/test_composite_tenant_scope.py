from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError

from app.models.composites import (
    CompositeDefinition,
    CompositeMemberReturnFact,
    CompositeMembership,
    CompositeReturnView,
)
from app.services.composite_calculation_service import calculate_composite_twr_from_persisted_facts
from app.services.composite_metadata_store import (
    SQLITE_TENANT_ID_CHECK_SQL,
    CompositeDefinitionIdentityConflictError,
    CompositeDefinitionOwnershipError,
    CompositeMemberReturnFactSelectionError,
    CompositeMetadataStore,
    CompositeTenantMigrationRequiredError,
    _advisory_lock_key,
    _definition_key,
    _deserialize_fact_families,
    _publication_lock_key,
    _row_value,
    _validate_publication_identity_fields,
    _validate_publication_periods,
)
from app.services.core_tenant_authority import (
    COMPOSITE_TENANT_AUTHORITY_REQUIRED_DETAIL,
    DUPLICATE_TENANT_AUTHORITY_DETAIL,
    MissingCompositeTenantAuthorityError,
)
from main import app


def _definition(display_name: str) -> CompositeDefinition:
    return CompositeDefinition.model_validate(
        {
            "composite_id": "SHARED_COMPOSITE",
            "display_name": display_name,
            "strategy_code": "BALANCED",
            "reporting_currency": "USD",
            "inception_date": "2026-01-01",
            "source_authority": {
                "definition_owner": "lotus-manage",
                "membership_owner": "lotus-manage",
                "member_return_owner": "lotus-performance",
                "asset_owner": "lotus-core",
                "benchmark_owner": "lotus-core",
                "policy_version": "composite-source-authority.v1",
            },
        }
    )


def _fact(return_value: str, fingerprint: str) -> CompositeMemberReturnFact:
    return CompositeMemberReturnFact.model_validate(
        {
            "composite_id": "SHARED_COMPOSITE",
            "portfolio_id": "SHARED_PORTFOLIO",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "return_value": return_value,
            "return_view": "NET_ACTUAL",
            "beginning_market_value": "100.00",
            "ending_market_value": "101.00",
            "reporting_currency": "USD",
            "calculation_id": fingerprint,
            "source_snapshot_id": fingerprint,
            "source_fingerprint": fingerprint,
            "restatement_version": "v1",
            "restatement_sequence": 1,
            "status": "READY",
            "reason_codes": [],
        }
    )


def _membership(snapshot: str) -> CompositeMembership:
    return CompositeMembership.model_validate(
        {
            "composite_id": "SHARED_COMPOSITE",
            "portfolio_id": "SHARED_PORTFOLIO",
            "effective_from": "2026-01-01",
            "status": "INCLUDED",
            "discretionary": True,
            "source_snapshot_id": snapshot,
        }
    )


def _seed(store: CompositeMetadataStore, *, tenant_id: str, return_value: str) -> None:
    fact = _fact(return_value, f"sha256:{tenant_id}")
    store.upsert_definition(_definition(tenant_id), tenant_id=tenant_id)
    store.upsert_member_return_fact(fact, tenant_id=tenant_id)
    store.complete_member_return_fact_publication(
        tenant_id=tenant_id,
        composite_id=fact.composite_id,
        return_view=CompositeReturnView.NET_ACTUAL,
        reporting_currency="USD",
        restatement_sequence=1,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        expected_families={(fact.portfolio_id, fact.period_start, fact.period_end)},
        source_fingerprint=f"sha256:publication-{tenant_id}",
    )


def _assert_publication_lock_identity_and_durable_family_evidence_are_canonical() -> None:
    assert _publication_lock_key("sha256:7fffffffffffffff") == 2**63 - 1
    assert _publication_lock_key("sha256:ffffffffffffffff") == -1

    tenant_key = _advisory_lock_key("composite-tenant-maintenance", tenant_id="tenant-a")
    assert tenant_key == _advisory_lock_key("composite-tenant-maintenance", tenant_id="tenant-a")
    assert tenant_key != _advisory_lock_key("composite-tenant-maintenance", tenant_id="tenant-b")
    assert tenant_key != _advisory_lock_key(
        "composite-tenant-maintenance",
        tenant_id="tenant-a",
        composite_id="COMPOSITE-1",
    )

    canonical = '[{"period_end":"2026-01-31","period_start":"2026-01-01","portfolio_id":"PORTFOLIO-1"}]'
    assert _deserialize_fact_families(canonical) == {("PORTFOLIO-1", date(2026, 1, 1), date(2026, 1, 31))}
    assert _row_value({"tenant_id": "tenant-a"}, "tenant_id") == "tenant-a"

    malformed_payloads = (
        None,
        "not-json",
        "{}",
        '[{"portfolio_id":"PORTFOLIO-1","period_start":"2026-01-01"}]',
        '[{"period_end":"2026-01-31","period_start":"2026-01-01","portfolio_id":"  "}]',
        '[{"period_end":"2026-01-31","period_start":20260101,"portfolio_id":"PORTFOLIO-1"}]',
        '[{"period_end":"2026-01-31","period_start":"20260101","portfolio_id":"PORTFOLIO-1"}]',
        '[{"period_end":"2026-01-01","period_start":"2026-01-31","portfolio_id":"PORTFOLIO-1"}]',
        f"[{canonical[1:-1]},{canonical[1:-1]}]",
    )
    for payload in malformed_payloads:
        with pytest.raises(
            CompositeMemberReturnFactSelectionError,
            match="malformed family evidence",
        ):
            _deserialize_fact_families(payload)  # type: ignore[arg-type]

    for sequence, fingerprint, expected_message in (
        (0, "sha256:source", "restatement_sequence must be positive"),
        (1, "  ", "source_fingerprint must not be blank"),
    ):
        with pytest.raises(ValueError, match=expected_message):
            _validate_publication_identity_fields(
                reporting_currency="USD",
                restatement_sequence=sequence,
                source_fingerprint=fingerprint,
            )

    for period_start, period_end, families, expected_message in (
        (
            date(2026, 1, 31),
            date(2026, 1, 1),
            set(),
            "publication period must be valid",
        ),
        (
            date(2026, 1, 1),
            date(2026, 1, 31),
            {("PORTFOLIO-1", date(2026, 1, 31), date(2026, 1, 1))},
            "publication fact-family periods must be valid",
        ),
        (
            date(2026, 1, 1),
            date(2026, 1, 31),
            {("PORTFOLIO-1", date(2025, 12, 31), date(2026, 1, 31))},
            "publication fact families must fall within its declared period",
        ),
    ):
        with pytest.raises(ValueError, match=expected_message):
            _validate_publication_periods(
                period_start=period_start,
                period_end=period_end,
                expected_families=families,
            )


def test_identical_external_ids_are_isolated_for_read_replay_and_cleanup(tmp_path) -> None:
    _assert_publication_lock_identity_and_durable_family_evidence_are_canonical()
    store = CompositeMetadataStore(f"sqlite:///{tmp_path / 'tenant-scope.db'}")
    store.create_schema()
    try:
        _seed(store, tenant_id="tenant-a", return_value="0.01")
        _seed(store, tenant_id="tenant-b", return_value="0.07")
        store.upsert_membership(_membership("membership-a"), tenant_id="tenant-a")
        store.upsert_membership(_membership("membership-b"), tenant_id="tenant-b")

        tenant_a = calculate_composite_twr_from_persisted_facts(
            tenant_id="tenant-a",
            composite_id="SHARED_COMPOSITE",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            restatement_sequence=1,
            store=store,
        )
        tenant_b = calculate_composite_twr_from_persisted_facts(
            tenant_id="tenant-b",
            composite_id="SHARED_COMPOSITE",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            restatement_sequence=1,
            store=store,
        )

        assert tenant_a.cumulative_return == Decimal("0.010000000000")
        assert tenant_b.cumulative_return == Decimal("0.070000000000")
        assert store.list_memberships("SHARED_COMPOSITE", tenant_id="tenant-a") == [_membership("membership-a")]
        assert store.list_memberships("SHARED_COMPOSITE", tenant_id="tenant-b") == [_membership("membership-b")]
        store.clear_records_for_composites({"SHARED_COMPOSITE"}, tenant_id="tenant-a")
        assert store.get_definition("SHARED_COMPOSITE", tenant_id="tenant-a") is None
        assert store.get_definition("SHARED_COMPOSITE", tenant_id="tenant-b") == _definition("tenant-b")
    finally:
        store.close()


def test_child_writes_require_same_tenant_definition_without_disclosing_foreign_owner(tmp_path) -> None:
    store = CompositeMetadataStore(f"sqlite:///{tmp_path / 'definition-ownership.db'}")
    store.create_schema()
    fact = _fact("0.01", "sha256:definition-owner")
    family = {(fact.portfolio_id, fact.period_start, fact.period_end)}
    try:
        store.upsert_definition(_definition("tenant-a"), tenant_id="tenant-a")
        for tenant_id in ("tenant-b", "tenant-without-definition"):
            with pytest.raises(CompositeDefinitionOwnershipError, match="unavailable"):
                store.upsert_membership(_membership(f"membership-{tenant_id}"), tenant_id=tenant_id)
            with pytest.raises(CompositeDefinitionOwnershipError, match="unavailable"):
                store.upsert_member_return_fact(fact, tenant_id=tenant_id)
            with pytest.raises(CompositeDefinitionOwnershipError, match="unavailable"):
                store.complete_member_return_fact_publication(
                    tenant_id=tenant_id,
                    composite_id=fact.composite_id,
                    return_view=fact.return_view,
                    reporting_currency=fact.reporting_currency,
                    restatement_sequence=fact.restatement_sequence,
                    period_start=fact.period_start,
                    period_end=fact.period_end,
                    expected_families=family,
                    source_fingerprint=f"sha256:publication-{tenant_id}",
                )
            counts = store.count_records(tenant_id=tenant_id)
            assert counts.memberships == 0
            assert counts.member_return_facts == 0
            with store._engine.connect() as connection:
                assert (
                    connection.execute(
                        text(
                            "SELECT count(*) FROM composite_member_return_fact_publications "
                            "WHERE tenant_id = :tenant_id"
                        ),
                        {"tenant_id": tenant_id},
                    ).scalar_one()
                    == 0
                )

        store.upsert_definition(_definition("tenant-b"), tenant_id="tenant-b")
        for tenant_id in ("tenant-a", "tenant-b"):
            store.upsert_membership(_membership(f"membership-{tenant_id}"), tenant_id=tenant_id)
            tenant_fact = _fact("0.01", f"sha256:{tenant_id}")
            store.upsert_member_return_fact(tenant_fact, tenant_id=tenant_id)
            store.complete_member_return_fact_publication(
                tenant_id=tenant_id,
                composite_id=tenant_fact.composite_id,
                return_view=tenant_fact.return_view,
                reporting_currency=tenant_fact.reporting_currency,
                restatement_sequence=tenant_fact.restatement_sequence,
                period_start=tenant_fact.period_start,
                period_end=tenant_fact.period_end,
                expected_families={(tenant_fact.portfolio_id, tenant_fact.period_start, tenant_fact.period_end)},
                source_fingerprint=f"sha256:publication-{tenant_id}",
            )
            counts = store.count_records(tenant_id=tenant_id)
            assert counts.definitions == 1
            assert counts.memberships == 1
            assert counts.member_return_facts == 1
            with store._engine.connect() as connection:
                assert (
                    connection.execute(
                        text(
                            "SELECT count(*) FROM composite_member_return_fact_publications "
                            "WHERE tenant_id = :tenant_id"
                        ),
                        {"tenant_id": tenant_id},
                    ).scalar_one()
                    == 1
                )
    finally:
        store.close()


def test_composite_routes_refuse_missing_blank_and_malformed_tenant_before_lookup(monkeypatch) -> None:
    payload = {
        "composite_id": "SHARED_COMPOSITE",
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
    }

    def _unexpected_durable_lookup(**_kwargs):
        pytest.fail("tenant admission refusal must precede durable composite access")

    monkeypatch.setattr(
        "app.api.endpoints.composites.calculate_composite_twr_from_persisted_facts",
        _unexpected_durable_lookup,
    )
    client = TestClient(app)
    try:
        missing = client.post("/performance/composites/twr", json=payload)
        blank = client.post("/performance/composites/twr", json=payload, headers={"X-Tenant-Id": "  "})
        malformed = client.post(
            "/performance/composites/twr",
            json=payload,
            headers={"X-Tenant-Id": "t" * 129},
        )
        duplicate_equal = client.post(
            "/performance/composites/twr",
            json=payload,
            headers=[("X-Tenant-Id", "tenant-a"), ("X-Tenant-Id", "tenant-a")],
        )
        duplicate_different = client.post(
            "/performance/composites/twr",
            json=payload,
            headers=[("X-Tenant-Id", "tenant-a"), ("X-Tenant-Id", "tenant-b")],
        )
    finally:
        client.close()

    assert missing.status_code == 401
    assert missing.json()["error_code"] == "TENANT_AUTHORITY_REQUIRED"
    assert missing.json()["detail"] == COMPOSITE_TENANT_AUTHORITY_REQUIRED_DETAIL
    assert missing.json()["message"] == COMPOSITE_TENANT_AUTHORITY_REQUIRED_DETAIL
    assert blank.status_code == 401
    assert blank.json()["error_code"] == "TENANT_AUTHORITY_REQUIRED"
    assert malformed.status_code == 400
    assert malformed.json()["error_code"] == "TENANT_AUTHORITY_MALFORMED"
    for duplicate in (duplicate_equal, duplicate_different):
        assert duplicate.status_code == 400
        assert duplicate.json()["error_code"] == "TENANT_AUTHORITY_MALFORMED"
        assert duplicate.json()["detail"] == DUPLICATE_TENANT_AUTHORITY_DETAIL

    schema = app.openapi()
    for path in ("/performance/composites/twr", "/performance/composites/inspect"):
        operation = schema["paths"][path]["post"]
        tenant_parameter = next(
            parameter for parameter in operation["parameters"] if parameter["name"] == "X-Tenant-Id"
        )
        assert tenant_parameter["required"] is True
        assert tenant_parameter["schema"]["example"] == "private-bank-sg"
        documented = operation["responses"]["401"]["content"]["application/json"]["example"]
        assert documented["detail"] == missing.json()["detail"]
        assert documented["message"] == missing.json()["message"]
        assert "duplicated" in operation["responses"]["400"]["description"]


def test_cleanup_refuses_missing_tenant_even_when_the_selection_is_empty(tmp_path) -> None:
    store = CompositeMetadataStore(f"sqlite:///{tmp_path / 'missing-cleanup-authority.db'}")
    store.create_schema()
    try:
        with pytest.raises(MissingCompositeTenantAuthorityError):
            store.clear_records_for_composites(set())
    finally:
        store.close()


def test_definition_lookup_requires_consistent_key_tenant_and_composite_identity(tmp_path) -> None:
    store = CompositeMetadataStore(f"sqlite:///{tmp_path / 'definition-integrity.db'}")
    store.create_schema()
    mismatched_key = _definition_key(tenant_id="tenant-b", composite_id="MISMATCHED")
    values = {
        "definition_key": mismatched_key,
        "tenant_id": "tenant-a",
        "composite_id": "MISMATCHED",
        "source_authority_json": _definition("mismatched").source_authority.model_dump_json(),
    }
    try:
        with store._engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO composite_definitions ("
                    "definition_key, tenant_id, composite_id, display_name, strategy_code, "
                    "reporting_currency, inception_date, termination_date, calculation_method, "
                    "source_authority_json) VALUES ("
                    ":definition_key, :tenant_id, :composite_id, 'Mismatched', 'BALANCED', "
                    "'USD', '2026-01-01', NULL, 'ASSET_WEIGHTED', :source_authority_json)"
                ),
                values,
            )

        assert store.get_definition("MISMATCHED", tenant_id="tenant-a") is None
        assert store.get_definition("MISMATCHED", tenant_id="tenant-b") is None
        with pytest.raises(CompositeDefinitionIdentityConflictError):
            definition = _definition("tenant-b").model_copy(update={"composite_id": "MISMATCHED"})
            store.upsert_definition(definition, tenant_id="tenant-b")

        with pytest.raises(IntegrityError):
            with store._engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO composite_definitions ("
                        "definition_key, tenant_id, composite_id, display_name, strategy_code, "
                        "reporting_currency, inception_date, termination_date, calculation_method, "
                        "source_authority_json) VALUES ("
                        "'duplicate-logical-key', 'tenant-a', 'MISMATCHED', 'Duplicate', 'BALANCED', "
                        "'USD', '2026-01-01', NULL, 'ASSET_WEIGHTED', :source_authority_json)"
                    ),
                    values,
                )

        with pytest.raises(IntegrityError):
            with store._engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO composite_definitions ("
                        "definition_key, tenant_id, composite_id, display_name, strategy_code, "
                        "reporting_currency, inception_date, termination_date, calculation_method, "
                        "source_authority_json) VALUES ("
                        "'padded-tenant-key', ' tenant-a ', 'PADDED', 'Padded', 'BALANCED', "
                        "'USD', '2026-01-01', NULL, 'ASSET_WEIGHTED', :source_authority_json)"
                    ),
                    values,
                )
    finally:
        store.close()


def test_populated_ownerless_schema_is_refused_without_partial_backfill(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'ownerless.db'}"
    engine = create_engine(database_url, future=True)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE composite_definitions ("
            "composite_id VARCHAR(128) PRIMARY KEY, display_name VARCHAR(256) NOT NULL, "
            "strategy_code VARCHAR(128) NOT NULL, reporting_currency VARCHAR(3) NOT NULL, "
            "inception_date DATE NOT NULL, termination_date DATE, calculation_method VARCHAR(64) NOT NULL, "
            "source_authority_json TEXT NOT NULL)"
        )
        connection.execute(
            text(
                "INSERT INTO composite_definitions VALUES ("
                "'LEGACY', 'Legacy', 'BALANCED', 'USD', '2026-01-01', NULL, "
                "'ASSET_WEIGHTED', '{}')"
            )
        )
    engine.dispose()

    store = CompositeMetadataStore(database_url)
    try:
        with pytest.raises(CompositeTenantMigrationRequiredError, match="cannot be assigned automatically"):
            store.create_schema()
        with store._engine.connect() as connection:
            inspector = inspect(connection)
            assert set(inspector.get_table_names()) == {"composite_definitions"}
            assert "tenant_id" not in {column["name"] for column in inspector.get_columns("composite_definitions")}
            assert connection.execute(text("SELECT composite_id FROM composite_definitions")).scalar_one() == "LEGACY"
    finally:
        store.close()


def test_empty_ownerless_schema_upgrades_to_tenant_identity_idempotently(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'empty-ownerless.db'}"
    engine = create_engine(database_url, future=True)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE composite_definitions ("
            "composite_id VARCHAR(128) PRIMARY KEY, display_name VARCHAR(256) NOT NULL, "
            "strategy_code VARCHAR(128) NOT NULL, reporting_currency VARCHAR(3) NOT NULL, "
            "inception_date DATE NOT NULL, termination_date DATE, calculation_method VARCHAR(64) NOT NULL, "
            "source_authority_json TEXT NOT NULL)"
        )
    engine.dispose()

    store = CompositeMetadataStore(database_url)
    try:
        store.create_schema()
        store.create_schema()
        with store._engine.connect() as connection:
            inspector = inspect(connection)
            assert inspector.get_pk_constraint("composite_definitions")["constrained_columns"] == ["definition_key"]
            assert {
                tuple(index["column_names"])
                for index in inspector.get_indexes("composite_member_return_facts")
                if index["name"].startswith("uq_composite_member_return_facts")
            } == {
                (
                    "tenant_id",
                    "composite_id",
                    "portfolio_id",
                    "period_start",
                    "period_end",
                    "return_view",
                    "reporting_currency",
                    "restatement_sequence",
                ),
                (
                    "tenant_id",
                    "composite_id",
                    "portfolio_id",
                    "period_start",
                    "period_end",
                    "return_view",
                    "reporting_currency",
                    "restatement_version",
                ),
            }
        store.upsert_definition(_definition("tenant-a"), tenant_id="tenant-a")
        store.upsert_definition(_definition("tenant-b"), tenant_id="tenant-b")
        assert store.count_records(tenant_id="tenant-a").definitions == 1
        assert store.count_records(tenant_id="tenant-b").definitions == 1
    finally:
        store.close()


def _create_partial_tenant_definition_schema(database_url: str, *, populated: bool) -> None:
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE composite_definitions ("
                "definition_key VARCHAR(80) PRIMARY KEY, tenant_id VARCHAR(128), "
                "composite_id VARCHAR(128) NOT NULL, display_name VARCHAR(256) NOT NULL, "
                "strategy_code VARCHAR(128) NOT NULL, reporting_currency VARCHAR(3) NOT NULL, "
                "inception_date DATE NOT NULL, termination_date DATE, calculation_method VARCHAR(64) NOT NULL, "
                "source_authority_json TEXT NOT NULL, "
                "CONSTRAINT uq_legacy_composite_strategy UNIQUE (strategy_code))"
            )
            connection.exec_driver_sql(
                "CREATE UNIQUE INDEX uq_composite_definitions_tenant_composite ON composite_definitions (composite_id)"
            )
            connection.exec_driver_sql(
                "CREATE TABLE composite_memberships ("
                "membership_key VARCHAR(320) PRIMARY KEY, tenant_id VARCHAR(128), "
                "composite_id VARCHAR(128) NOT NULL, portfolio_id VARCHAR(128) NOT NULL, "
                "effective_from DATE NOT NULL, effective_to DATE, status VARCHAR(64) NOT NULL, "
                "status_reason TEXT, discretionary VARCHAR(5) NOT NULL, source_snapshot_id VARCHAR(256) NOT NULL, "
                "CONSTRAINT uq_legacy_membership_identity UNIQUE "
                "(composite_id, portfolio_id, effective_from))"
            )
            connection.exec_driver_sql(
                "CREATE TABLE composite_member_return_facts ("
                "fact_key VARCHAR(360) PRIMARY KEY, tenant_id VARCHAR(128), composite_id VARCHAR(128) NOT NULL, "
                "portfolio_id VARCHAR(128) NOT NULL, period_start DATE NOT NULL, period_end DATE NOT NULL, "
                "return_value TEXT NOT NULL, return_view VARCHAR(32) NOT NULL, beginning_market_value TEXT NOT NULL, "
                "ending_market_value TEXT NOT NULL, reporting_currency VARCHAR(3) NOT NULL, "
                "calculation_id VARCHAR(64) NOT NULL, source_snapshot_id VARCHAR(256) NOT NULL, "
                "source_fingerprint VARCHAR(256) NOT NULL, restatement_version VARCHAR(64) NOT NULL, "
                "restatement_sequence INTEGER NOT NULL DEFAULT 1, status VARCHAR(64) NOT NULL, "
                "reason_codes_json TEXT NOT NULL)"
            )
            connection.exec_driver_sql(
                "CREATE UNIQUE INDEX uq_composite_member_return_facts_sequence_identity "
                "ON composite_member_return_facts (composite_id, portfolio_id, period_start, period_end, "
                "return_view, reporting_currency, restatement_sequence)"
            )
            connection.exec_driver_sql(
                "CREATE TABLE composite_member_return_fact_publications ("
                "publication_key VARCHAR(80) PRIMARY KEY, tenant_id VARCHAR(128), "
                "composite_id VARCHAR(128) NOT NULL, return_view VARCHAR(32) NOT NULL, "
                "reporting_currency VARCHAR(3) NOT NULL, restatement_sequence INTEGER NOT NULL, "
                "period_start DATE NOT NULL, period_end DATE NOT NULL, expected_families_json TEXT NOT NULL, "
                "source_fingerprint VARCHAR(256) NOT NULL)"
            )
            connection.exec_driver_sql(
                "CREATE UNIQUE INDEX uq_composite_fact_publication_identity "
                "ON composite_member_return_fact_publications "
                "(composite_id, return_view, reporting_currency, restatement_sequence)"
            )
            if populated:
                connection.exec_driver_sql(
                    "INSERT INTO composite_definitions VALUES ("
                    "'legacy-key', 'tenant-a', 'SHARED_COMPOSITE', 'Legacy', 'BALANCED', "
                    "'USD', '2026-01-01', NULL, 'ASSET_WEIGHTED', '{}')"
                )
    finally:
        engine.dispose()


def test_populated_partial_tenant_schema_is_refused_with_shape_evidence_and_no_ddl(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'populated-partial-tenant.db'}"
    _create_partial_tenant_definition_schema(database_url, populated=True)
    store = CompositeMetadataStore(database_url)
    try:
        with pytest.raises(CompositeTenantMigrationRequiredError) as exc_info:
            store.create_schema()
        assert "composite_definitions" in str(exc_info.value)
        assert "tenant_id is nullable" in str(exc_info.value)
        assert "uq_composite_definitions_tenant_composite" in str(exc_info.value)
        assert "global unique constraint" in str(exc_info.value)
        assert "composite_memberships" in str(exc_info.value)
        assert "composite_member_return_facts" in str(exc_info.value)
        assert "composite_member_return_fact_publications" in str(exc_info.value)
        assert "foreign key fk_composite_memberships_tenant_definition is missing or stale" in str(exc_info.value)
        with store._engine.connect() as connection:
            inspector = inspect(connection)
            assert set(inspector.get_table_names()) == {
                "composite_definitions",
                "composite_memberships",
                "composite_member_return_facts",
                "composite_member_return_fact_publications",
            }
            assert connection.execute(text("SELECT definition_key FROM composite_definitions")).scalar_one() == (
                "legacy-key"
            )
            assert {
                index["name"]: tuple(index["column_names"]) for index in inspector.get_indexes("composite_definitions")
            }["uq_composite_definitions_tenant_composite"] == ("composite_id",)
    finally:
        store.close()


def test_empty_partial_tenant_schema_rebuilds_for_equal_ids_and_second_bootstrap_is_ddl_free(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'empty-partial-tenant.db'}"
    _create_partial_tenant_definition_schema(database_url, populated=False)
    store = CompositeMetadataStore(database_url)
    try:
        store.create_schema()
        store.upsert_definition(_definition("tenant-a"), tenant_id="tenant-a")
        store.upsert_definition(_definition("tenant-b"), tenant_id="tenant-b")
        assert store.count_records(tenant_id="tenant-a").definitions == 1
        assert store.count_records(tenant_id="tenant-b").definitions == 1
        with store._engine.connect() as connection:
            assert {
                foreign_key["name"] for foreign_key in inspect(connection).get_foreign_keys("composite_memberships")
            } == {"fk_composite_memberships_tenant_definition"}

        second_bootstrap_statements: list[str] = []

        def _capture_statement(_connection, _cursor, statement, _parameters, _context, _executemany):
            second_bootstrap_statements.append(statement)

        event.listen(store._engine, "before_cursor_execute", _capture_statement)
        try:
            store.create_schema()
        finally:
            event.remove(store._engine, "before_cursor_execute", _capture_statement)
        assert not [statement for statement in second_bootstrap_statements if "ALTER TABLE" in statement.upper()]
        assert not [statement for statement in second_bootstrap_statements if "DROP TABLE" in statement.upper()]
    finally:
        store.close()


def test_populated_current_schema_missing_tenant_unique_index_refuses_without_repair(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'missing-tenant-index.db'}"
    store = CompositeMetadataStore(database_url)
    store.create_schema()
    try:
        store.upsert_definition(_definition("tenant-a"), tenant_id="tenant-a")
        with store._engine.begin() as connection:
            connection.exec_driver_sql("DROP INDEX uq_composite_definitions_tenant_composite")

        with pytest.raises(
            CompositeTenantMigrationRequiredError,
            match="unique index uq_composite_definitions_tenant_composite is None",
        ):
            store.create_schema()

        with store._engine.connect() as connection:
            inspector = inspect(connection)
            assert "uq_composite_definitions_tenant_composite" not in {
                index["name"] for index in inspector.get_indexes("composite_definitions")
            }
            assert connection.execute(text("SELECT tenant_id FROM composite_definitions")).scalar_one() == "tenant-a"
    finally:
        store.close()


def _drop_sqlite_tenant_check(database_url: str, table_name: str, constraint_name: str) -> None:
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            installed_sql = connection.execute(
                text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = :table_name"),
                {"table_name": table_name},
            ).scalar_one()
            constraint_sql = f", \n\tCONSTRAINT {constraint_name} CHECK ({SQLITE_TENANT_ID_CHECK_SQL})"
            updated_sql = installed_sql.replace(constraint_sql, "")
            assert updated_sql != installed_sql
            schema_version = connection.exec_driver_sql("PRAGMA schema_version").scalar_one()
            connection.exec_driver_sql("PRAGMA writable_schema = ON")
            connection.execute(
                text("UPDATE sqlite_master SET sql = :sql WHERE type = 'table' AND name = :table_name"),
                {"sql": updated_sql, "table_name": table_name},
            )
            connection.exec_driver_sql(f"PRAGMA schema_version = {schema_version + 1}")
            connection.exec_driver_sql("PRAGMA writable_schema = OFF")
    finally:
        engine.dispose()


def test_populated_current_schema_missing_tenant_check_refuses_without_ddl(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'missing-tenant-check.db'}"
    store = CompositeMetadataStore(database_url)
    store.create_schema()
    store.upsert_definition(_definition("tenant-a"), tenant_id="tenant-a")
    store.close()
    _drop_sqlite_tenant_check(
        database_url,
        "composite_definitions",
        "ck_composite_definitions_tenant_id",
    )

    store = CompositeMetadataStore(database_url)
    try:
        with pytest.raises(CompositeTenantMigrationRequiredError, match="tenant check.*missing or stale"):
            store.create_schema()
        with store._engine.connect() as connection:
            assert "ck_composite_definitions_tenant_id" not in {
                constraint["name"] for constraint in inspect(connection).get_check_constraints("composite_definitions")
            }
            assert connection.execute(text("SELECT tenant_id FROM composite_definitions")).scalar_one() == "tenant-a"
    finally:
        store.close()


def test_empty_schema_missing_tenant_checks_rebuilds_and_rejects_bad_raw_tenants(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'empty-missing-tenant-checks.db'}"
    store = CompositeMetadataStore(database_url)
    store.create_schema()
    store.close()
    for table_name, constraint_name in (
        ("composite_definitions", "ck_composite_definitions_tenant_id"),
        ("composite_memberships", "ck_composite_memberships_tenant_id"),
        ("composite_member_return_facts", "ck_composite_member_return_facts_tenant_id"),
        ("composite_member_return_fact_publications", "ck_composite_fact_publications_tenant_id"),
    ):
        _drop_sqlite_tenant_check(database_url, table_name, constraint_name)

    store = CompositeMetadataStore(database_url)
    try:
        store.create_schema()
        store.create_schema()
        with store._engine.connect() as connection:
            inspector = inspect(connection)
            for table_name, constraint_name in (
                ("composite_definitions", "ck_composite_definitions_tenant_id"),
                ("composite_memberships", "ck_composite_memberships_tenant_id"),
                ("composite_member_return_facts", "ck_composite_member_return_facts_tenant_id"),
                ("composite_member_return_fact_publications", "ck_composite_fact_publications_tenant_id"),
            ):
                assert constraint_name in {
                    constraint["name"] for constraint in inspector.get_check_constraints(table_name)
                }
        for suffix, tenant_id in (("blank", ""), ("padded", " tenant-a "), ("overlong", "t" * 129)):
            with pytest.raises(IntegrityError):
                with store._engine.begin() as connection:
                    connection.execute(
                        text(
                            "INSERT INTO composite_definitions ("
                            "definition_key, tenant_id, composite_id, display_name, strategy_code, "
                            "reporting_currency, inception_date, termination_date, calculation_method, "
                            "source_authority_json) VALUES ("
                            ":definition_key, :tenant_id, :composite_id, 'Invalid tenant', 'BALANCED', "
                            "'USD', '2026-01-01', NULL, 'ASSET_WEIGHTED', '{}')"
                        ),
                        {
                            "definition_key": f"invalid-{suffix}",
                            "tenant_id": tenant_id,
                            "composite_id": f"INVALID_{suffix.upper()}",
                        },
                    )
    finally:
        store.close()


def test_concurrent_identical_fact_writes_are_fenced_per_tenant(tmp_path) -> None:
    store = CompositeMetadataStore(f"sqlite:///{tmp_path / 'tenant-concurrency.db'}")
    store.create_schema()
    try:
        store.upsert_definition(_definition("tenant-a"), tenant_id="tenant-a")
        store.upsert_definition(_definition("tenant-b"), tenant_id="tenant-b")
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    store.upsert_member_return_fact,
                    _fact(return_value, f"sha256:{tenant_id}"),
                    tenant_id=tenant_id,
                )
                for tenant_id, return_value in (("tenant-a", "0.01"), ("tenant-b", "0.07"))
            ]
            for future in futures:
                future.result()

        assert store.count_records(tenant_id="tenant-a").member_return_facts == 1
        assert store.count_records(tenant_id="tenant-b").member_return_facts == 1
    finally:
        store.close()
