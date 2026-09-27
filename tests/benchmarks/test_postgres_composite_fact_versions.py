from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier, Lock, local

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app.models.composites import CompositeDefinition, CompositeMemberReturnFact, CompositeReturnView
from app.services import composite_metadata_store as composite_metadata_store_module
from app.services.composite_calculation_service import calculate_composite_twr_from_persisted_facts
from app.services.composite_metadata_store import (
    COMPOSITE_DEFINITION_CURRENCY_CHECK,
    MEMBER_RETURN_FACT_COMPLETED_DELETE_TRIGGER,
    MEMBER_RETURN_FACT_CURRENCY_CHECK,
    MEMBER_RETURN_FACT_IMMUTABLE_UPDATE_TRIGGER,
    MEMBER_RETURN_FACT_SEQUENCE_CHECK,
    MEMBER_RETURN_FACT_VERSION_CHECK,
    POSTGRES_MEMBER_RETURN_FACT_VERSION_CHECK_MARKER,
    PUBLICATION_CURRENCY_CHECK,
    PUBLICATION_IMMUTABLE_UPDATE_TRIGGER,
    PUBLICATION_PERIOD_CHECK,
    PUBLICATION_SEQUENCE_CHECK,
    CompositeMemberReturnFactConflictError,
    CompositeMemberReturnFactSelectionError,
    CompositeMetadataStore,
    _publication_key,
    _serialize_fact_families,
)
from tests.benchmarks.postgres_runtime_helpers import get_postgres_database_url


def _definition() -> CompositeDefinition:
    return CompositeDefinition.model_validate(
        {
            "composite_id": "PB_GLOBAL_BALANCED_USD",
            "display_name": "Private Banking Global Balanced USD Composite",
            "strategy_code": "GLOBAL_BALANCED",
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


def _fact(
    *,
    return_value: str,
    return_view: str,
    restatement_version: str,
    restatement_sequence: int,
    fingerprint: str,
    composite_id: str = "PB_GLOBAL_BALANCED_USD",
    portfolio_id: str = "PB_SG_GLOBAL_BAL_001",
    period_start: str = "2026-01-01",
    period_end: str = "2026-01-31",
) -> CompositeMemberReturnFact:
    return CompositeMemberReturnFact.model_validate(
        {
            "composite_id": composite_id,
            "portfolio_id": portfolio_id,
            "period_start": period_start,
            "period_end": period_end,
            "return_value": return_value,
            "return_view": return_view,
            "beginning_market_value": "100.00",
            "ending_market_value": str(Decimal("100.00") * (Decimal("1") + Decimal(return_value))),
            "reporting_currency": "USD",
            "calculation_id": f"calc-{fingerprint}",
            "source_snapshot_id": f"snapshot-{fingerprint}",
            "source_fingerprint": f"sha256:{fingerprint}",
            "restatement_version": restatement_version,
            "restatement_sequence": restatement_sequence,
        }
    )


def _complete_publication(
    store: CompositeMetadataStore,
    *facts: CompositeMemberReturnFact,
    source_fingerprint: str,
) -> None:
    assert facts
    first = facts[0]
    assert all(
        (fact.composite_id, fact.return_view, fact.reporting_currency, fact.restatement_sequence)
        == (first.composite_id, first.return_view, first.reporting_currency, first.restatement_sequence)
        for fact in facts
    )
    store.complete_member_return_fact_publication(
        composite_id=first.composite_id,
        return_view=first.return_view,
        reporting_currency=first.reporting_currency,
        restatement_sequence=first.restatement_sequence,
        period_start=min(fact.period_start for fact in facts),
        period_end=max(fact.period_end for fact in facts),
        expected_families={(fact.portfolio_id, fact.period_start, fact.period_end) for fact in facts},
        source_fingerprint=source_fingerprint,
    )


def _create_pre_sequence_schema(database_url: str) -> None:
    legacy_publication_key = _publication_key(
        composite_id="PB_GLOBAL_BALANCED_USD",
        return_view=CompositeReturnView.NET_ACTUAL,
        reporting_currency="usd",
        restatement_sequence=1,
    )
    legacy_families = _serialize_fact_families({("PB_SG_GLOBAL_BAL_001", date(2026, 1, 1), date(2026, 1, 31))})
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                """
                CREATE TABLE composite_definitions (
                    composite_id VARCHAR(128) PRIMARY KEY,
                    display_name VARCHAR(256) NOT NULL,
                    strategy_code VARCHAR(128) NOT NULL,
                    reporting_currency VARCHAR(3),
                    inception_date DATE NOT NULL,
                    termination_date DATE,
                    calculation_method VARCHAR(64) NOT NULL,
                    source_authority_json TEXT NOT NULL
                )
                """
            )
            connection.exec_driver_sql(
                """
                INSERT INTO composite_definitions VALUES (
                    'PB_GLOBAL_BALANCED_USD', 'Legacy Global Balanced', 'GLOBAL_BALANCED',
                    'usd', '2026-01-01', NULL, 'ASSET_WEIGHTED', '{}'
                )
                """
            )
            connection.exec_driver_sql(
                """
                CREATE TABLE composite_member_return_facts (
                    fact_key VARCHAR(360) PRIMARY KEY,
                    composite_id VARCHAR(128) NOT NULL,
                    portfolio_id VARCHAR(128) NOT NULL,
                    period_start DATE NOT NULL,
                    period_end DATE NOT NULL,
                    return_value TEXT NOT NULL,
                    return_view VARCHAR(32) NOT NULL,
                    beginning_market_value TEXT NOT NULL,
                    ending_market_value TEXT NOT NULL,
                    reporting_currency VARCHAR(3) NOT NULL,
                    calculation_id VARCHAR(64) NOT NULL,
                    source_snapshot_id VARCHAR(256) NOT NULL,
                    source_fingerprint VARCHAR(256) NOT NULL,
                    restatement_version VARCHAR(64),
                    status VARCHAR(64) NOT NULL,
                    reason_codes_json TEXT NOT NULL
                )
                """
            )
            connection.exec_driver_sql(
                "ALTER TABLE composite_member_return_facts "
                f"ADD CONSTRAINT {MEMBER_RETURN_FACT_VERSION_CHECK} "
                "CHECK (length(trim(restatement_version)) > 0)"
            )
            connection.exec_driver_sql(
                """
                CREATE TABLE composite_member_return_fact_publications (
                    publication_key VARCHAR(80) PRIMARY KEY,
                    composite_id VARCHAR(128) NOT NULL,
                    return_view VARCHAR(32) NOT NULL,
                    reporting_currency VARCHAR(3),
                    restatement_sequence INTEGER,
                    period_start DATE NOT NULL,
                    period_end DATE NOT NULL,
                    expected_families_json TEXT NOT NULL,
                    source_fingerprint VARCHAR(256) NOT NULL
                )
                """
            )
            connection.execute(
                text(
                    """
                    INSERT INTO composite_member_return_fact_publications (
                        publication_key, composite_id, return_view, reporting_currency,
                        restatement_sequence, period_start, period_end,
                        expected_families_json, source_fingerprint
                    ) VALUES (
                        :publication_key, 'PB_GLOBAL_BALANCED_USD', 'NET_ACTUAL', 'usd',
                        1, '2026-01-01', '2026-01-31', :expected_families_json,
                        'sha256:legacy-publication-v1'
                    )
                    """
                ),
                {
                    "publication_key": legacy_publication_key,
                    "expected_families_json": legacy_families,
                },
            )
            connection.exec_driver_sql(
                """
                INSERT INTO composite_member_return_facts (
                    fact_key, composite_id, portfolio_id, period_start, period_end,
                    return_value, return_view, beginning_market_value, ending_market_value,
                    reporting_currency, calculation_id, source_snapshot_id, source_fingerprint,
                    restatement_version, status, reason_codes_json
                ) VALUES (
                    'PB_GLOBAL_BALANCED_USD|PB_SG_GLOBAL_BAL_001|2026-01-01|2026-01-31',
                    'PB_GLOBAL_BALANCED_USD', 'PB_SG_GLOBAL_BAL_001', '2026-01-01', '2026-01-31',
                    '0.0100', 'NET_ACTUAL', '100.00', '101.00', 'usd', 'calc-net-v1',
                    'snapshot-net-v1', 'sha256:net-v1', 'published', 'READY', '[]'
                )
                """
            )
    finally:
        engine.dispose()


def _create_null_publication_period_schema(database_url: str) -> None:
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                """
                CREATE TABLE composite_member_return_fact_publications (
                    publication_key VARCHAR(80) PRIMARY KEY,
                    composite_id VARCHAR(128) NOT NULL,
                    return_view VARCHAR(32) NOT NULL,
                    reporting_currency VARCHAR(3) NOT NULL,
                    restatement_sequence INTEGER NOT NULL,
                    period_start DATE,
                    period_end DATE,
                    expected_families_json TEXT NOT NULL,
                    source_fingerprint VARCHAR(256) NOT NULL
                )
                """
            )
            connection.exec_driver_sql(
                """
                INSERT INTO composite_member_return_fact_publications VALUES (
                    'legacy-null-publication-period', 'PB_GLOBAL_BALANCED_USD', 'NET_ACTUAL',
                    'USD', 1, NULL, '2026-01-31', '[]', 'sha256:legacy-null-period'
                )
                """
            )
    finally:
        engine.dispose()


def _create_whitespace_version_schema(database_url: str) -> None:
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                """
                CREATE TABLE composite_member_return_facts (
                    fact_key VARCHAR(640) PRIMARY KEY,
                    composite_id VARCHAR(128) NOT NULL,
                    portfolio_id VARCHAR(128) NOT NULL,
                    period_start DATE NOT NULL,
                    period_end DATE NOT NULL,
                    return_value VARCHAR(128) NOT NULL,
                    return_view VARCHAR(32) NOT NULL,
                    beginning_market_value VARCHAR(128) NOT NULL,
                    ending_market_value VARCHAR(128) NOT NULL,
                    reporting_currency VARCHAR(3) NOT NULL,
                    calculation_id VARCHAR(64) NOT NULL,
                    source_snapshot_id VARCHAR(256) NOT NULL,
                    source_fingerprint VARCHAR(256) NOT NULL,
                    restatement_version VARCHAR(64) NOT NULL,
                    restatement_sequence INTEGER NOT NULL,
                    status VARCHAR(64) NOT NULL,
                    reason_codes_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                text(
                    """
                    INSERT INTO composite_member_return_facts VALUES (
                        'legacy-whitespace-version', 'PB_GLOBAL_BALANCED_USD', 'P1',
                        '2026-01-01', '2026-01-31', '0.01', 'NET_ACTUAL', '100.00', '101.00',
                        'USD', 'legacy-calc', 'legacy-snapshot', 'sha256:legacy',
                        :restatement_version, 1, 'READY', '[]'
                    )
                    """
                ),
                {"restatement_version": "\t"},
            )
    finally:
        engine.dispose()


def _create_unicode_currency_schema(database_url: str) -> None:
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                """
                CREATE TABLE composite_definitions (
                    composite_id VARCHAR(128) PRIMARY KEY,
                    display_name VARCHAR(256) NOT NULL,
                    strategy_code VARCHAR(128) NOT NULL,
                    reporting_currency VARCHAR(3) NOT NULL,
                    inception_date DATE NOT NULL,
                    termination_date DATE,
                    calculation_method VARCHAR(64) NOT NULL,
                    source_authority_json TEXT NOT NULL
                )
                """
            )
            connection.exec_driver_sql(
                """
                INSERT INTO composite_definitions VALUES (
                    'UNICODE_CURRENCY', 'Unicode currency rejection', 'BALANCED',
                    'uſd', '2026-01-01', NULL, 'ASSET_WEIGHTED', '{}'
                )
                """
            )
    finally:
        engine.dispose()


def _assert_direct_bad_sequence_is_rejected(database_url: str) -> None:
    engine = create_engine(database_url, future=True)
    try:
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    """
                    INSERT INTO composite_member_return_facts (
                        fact_key, composite_id, portfolio_id, period_start, period_end,
                        return_value, return_view, beginning_market_value, ending_market_value,
                        reporting_currency, calculation_id, source_snapshot_id, source_fingerprint,
                        restatement_version, restatement_sequence, status, reason_codes_json
                    ) VALUES (
                        'direct-invalid-sequence', 'DIRECT_SQL', 'P1', '2026-01-01', '2026-01-31',
                        '0.01', 'NET_ACTUAL', '100.00', '101.00', 'USD', 'direct-invalid-sequence',
                        'direct-invalid-sequence', 'sha256:direct-invalid-sequence', 'invalid', 0,
                        'READY', '[]'
                    )
                    """
                )
    finally:
        engine.dispose()


def _assert_direct_blank_version_is_rejected(database_url: str) -> None:
    engine = create_engine(database_url, future=True)
    try:
        for fact_key, whitespace_only_version in (
            ("direct-null-version", None),
            ("direct-space-only-version", " "),
            ("direct-tab-only-version", "\t"),
            ("direct-newline-only-version", "\n"),
            ("direct-record-separator-only-version", "\x1e"),
            ("direct-nonbreaking-space-only-version", "\u00a0"),
            ("direct-em-space-only-version", "\u2003"),
        ):
            with pytest.raises(IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            """
                            INSERT INTO composite_member_return_facts (
                                fact_key, composite_id, portfolio_id, period_start, period_end,
                                return_value, return_view, beginning_market_value, ending_market_value,
                                reporting_currency, calculation_id, source_snapshot_id, source_fingerprint,
                                restatement_version, restatement_sequence, status, reason_codes_json
                            ) VALUES (
                                :fact_key, 'DIRECT_SQL', 'P2', '2026-01-01', '2026-01-31',
                                '0.01', 'NET_ACTUAL', '100.00', '101.00', 'USD', :fact_key,
                                :fact_key, 'sha256:direct-blank-version', :restatement_version,
                                1, 'READY', '[]'
                            )
                            """
                        ),
                        {
                            "fact_key": fact_key,
                            "restatement_version": whitespace_only_version,
                        },
                    )
    finally:
        engine.dispose()


def _assert_direct_malformed_currency_is_rejected(database_url: str) -> None:
    engine = create_engine(database_url, future=True)
    try:
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    """
                    INSERT INTO composite_member_return_facts (
                        fact_key, composite_id, portfolio_id, period_start, period_end,
                        return_value, return_view, beginning_market_value, ending_market_value,
                        reporting_currency, calculation_id, source_snapshot_id, source_fingerprint,
                        restatement_version, restatement_sequence, status, reason_codes_json
                    ) VALUES (
                        'direct-invalid-currency', 'DIRECT_SQL', 'P4', '2026-01-01', '2026-01-31',
                        '0.01', 'NET_ACTUAL', '100.00', '101.00', 'US1', 'direct-invalid-currency',
                        'direct-invalid-currency', 'sha256:direct-invalid-currency', 'published', 1,
                        'READY', '[]'
                    )
                    """
                )
    finally:
        engine.dispose()


def _assert_completed_fact_payload_mutation_is_rejected(
    database_url: str,
    *,
    calculation_id: str,
) -> None:
    engine = create_engine(database_url, future=True)
    try:
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE composite_member_return_facts "
                        "SET return_value = '0.9900', ending_market_value = '199.00', "
                        "source_fingerprint = 'sha256:mutated' "
                        "WHERE calculation_id = :calculation_id"
                    ),
                    {"calculation_id": calculation_id},
                )
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM composite_member_return_facts WHERE calculation_id = :calculation_id"),
                    {"calculation_id": calculation_id},
                )
    finally:
        engine.dispose()


def _assert_direct_invalid_publication_identity_is_rejected(
    database_url: str,
    publication_key: str,
    reporting_currency: str,
    restatement_sequence: int,
) -> None:
    engine = create_engine(database_url, future=True)
    try:
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        INSERT INTO composite_member_return_fact_publications (
                            publication_key, composite_id, return_view, reporting_currency,
                            restatement_sequence, period_start, period_end,
                            expected_families_json, source_fingerprint
                        ) VALUES (
                            :publication_key, 'DIRECT_SQL', 'NET_ACTUAL', :reporting_currency,
                            :restatement_sequence, '2026-01-01', '2026-01-31',
                            '[]', 'sha256:direct-invalid-publication'
                        )
                        """
                    ),
                    {
                        "publication_key": publication_key,
                        "reporting_currency": reporting_currency,
                        "restatement_sequence": restatement_sequence,
                    },
                )
    finally:
        engine.dispose()


def _assert_fresh_schema_defaults_legacy_writer_to_first_sequence(database_url: str) -> None:
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                """
                INSERT INTO composite_member_return_facts (
                    fact_key, composite_id, portfolio_id, period_start, period_end,
                    return_value, return_view, beginning_market_value, ending_market_value,
                    reporting_currency, calculation_id, source_snapshot_id, source_fingerprint,
                    restatement_version, status, reason_codes_json
                ) VALUES (
                    'fresh-schema-default-sequence', 'DIRECT_SQL', 'P3', '2026-01-01', '2026-01-31',
                    '0.01', 'NET_ACTUAL', '100.00', '101.00', 'USD', 'fresh-schema-default-sequence',
                    'fresh-schema-default-sequence', 'sha256:fresh-schema-default-sequence', 'published',
                    'READY', '[]'
                )
                """
            )
            persisted_sequence = connection.exec_driver_sql(
                "SELECT restatement_sequence FROM composite_member_return_facts "
                "WHERE fact_key = 'fresh-schema-default-sequence'"
            ).scalar_one()
    finally:
        engine.dispose()
    assert persisted_sequence == 1


def _calculated_return(
    store: CompositeMetadataStore,
    *,
    return_view: CompositeReturnView,
    restatement_sequence: int | None = None,
    composite_id: str = "PB_GLOBAL_BALANCED_USD",
) -> Decimal | None:
    result = calculate_composite_twr_from_persisted_facts(
        composite_id=composite_id,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        return_view=return_view,
        restatement_sequence=restatement_sequence,
        store=store,
    )
    return result.cumulative_return


def _run_forced_concurrent_writes(
    *,
    monkeypatch: pytest.MonkeyPatch,
    stores: tuple[CompositeMetadataStore, CompositeMetadataStore],
    facts: tuple[CompositeMemberReturnFact, CompositeMemberReturnFact],
) -> tuple[list[str], list[tuple[int, int, bool]]]:
    """Force both durable transactions past the absent-row lookup before either insert.

    A barrier at call entry would not prove a database race. This wrapper waits only after each
    independent PostgreSQL session has opened a transaction, recorded its backend/transaction
    identity, and observed that the immutable identity is absent. Both callers must therefore
    exercise the unique-index conflict path rather than an ordinary sequential replay lookup.
    """

    original_lookup = composite_metadata_store_module._find_member_return_fact_identity_collision
    lookup_barrier = Barrier(2, timeout=10)
    observation_lock = Lock()
    thread_state = local()
    observations: list[tuple[int, int, bool]] = []
    target_composite_id = facts[0].composite_id

    def synchronized_lookup(session, fact):
        row = original_lookup(session, fact)
        if fact.composite_id == target_composite_id and not getattr(thread_state, "initial_lookup_recorded", False):
            thread_state.initial_lookup_recorded = True
            backend_pid = session.scalar(text("SELECT pg_backend_pid()"))
            transaction_id = session.scalar(text("SELECT txid_current()"))
            with observation_lock:
                observations.append((backend_pid, transaction_id, row is None))
            lookup_barrier.wait()
        return row

    def write(store: CompositeMetadataStore, fact: CompositeMemberReturnFact) -> str:
        try:
            store.upsert_member_return_fact(fact)
            return "accepted"
        except CompositeMemberReturnFactConflictError:
            return "conflict"

    with monkeypatch.context() as patch_context:
        patch_context.setattr(
            composite_metadata_store_module,
            "_find_member_return_fact_identity_collision",
            synchronized_lookup,
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(write, store, fact) for store, fact in zip(stores, facts, strict=True)]
            outcomes = sorted(future.result(timeout=20) for future in futures)

    return outcomes, observations


def test_postgres_concurrent_composite_fact_replays_are_idempotent_and_conflicts_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = get_postgres_database_url()
    setup_store = CompositeMetadataStore(database_url)
    setup_store.create_schema()
    stores = (CompositeMetadataStore(database_url), CompositeMetadataStore(database_url))
    try:
        identical = _fact(
            composite_id="CONCURRENT_IDENTICAL",
            return_value="0.0100",
            return_view="NET_ACTUAL",
            restatement_version="published",
            restatement_sequence=1,
            fingerprint="concurrent-identical",
        )
        identical_outcomes, identical_observations = _run_forced_concurrent_writes(
            monkeypatch=monkeypatch,
            stores=stores,
            facts=(identical, identical),
        )

        assert identical_outcomes == ["accepted", "accepted"]
        assert len(identical_observations) == 2
        assert all(observed_absent for _, _, observed_absent in identical_observations)
        assert len({backend_pid for backend_pid, _, _ in identical_observations}) == 2
        assert len({transaction_id for _, transaction_id, _ in identical_observations}) == 2

        changed_a = _fact(
            composite_id="CONCURRENT_CONFLICT",
            return_value="0.0200",
            return_view="NET_ACTUAL",
            restatement_version="correction",
            restatement_sequence=2,
            fingerprint="concurrent-conflict-a",
        )
        changed_b = CompositeMemberReturnFact.model_validate(
            changed_a.model_dump(mode="json")
            | {
                "return_value": "0.0250",
                "ending_market_value": "102.5000",
                "calculation_id": "calc-concurrent-conflict-b",
                "source_snapshot_id": "snapshot-concurrent-conflict-b",
                "source_fingerprint": "sha256:concurrent-conflict-b",
            }
        )
        changed_outcomes, changed_observations = _run_forced_concurrent_writes(
            monkeypatch=monkeypatch,
            stores=stores,
            facts=(changed_a, changed_b),
        )

        assert changed_outcomes == ["accepted", "conflict"]
        assert len(changed_observations) == 2
        assert all(observed_absent for _, _, observed_absent in changed_observations)
        assert len({backend_pid for backend_pid, _, _ in changed_observations}) == 2
        assert len({transaction_id for _, transaction_id, _ in changed_observations}) == 2

        assert setup_store.count_records().member_return_facts == 2
        identical_rows = setup_store.list_member_return_facts(
            composite_id=identical.composite_id,
            period_start=identical.period_start,
            period_end=identical.period_end,
            return_view=identical.return_view,
            reporting_currency=identical.reporting_currency,
            restatement_sequence=identical.restatement_sequence,
        )
        changed_rows = setup_store.list_member_return_facts(
            composite_id=changed_a.composite_id,
            period_start=changed_a.period_start,
            period_end=changed_a.period_end,
            return_view=changed_a.return_view,
            reporting_currency=changed_a.reporting_currency,
            restatement_sequence=changed_a.restatement_sequence,
        )
        assert identical_rows == [identical]
        assert len(changed_rows) == 1
        assert changed_rows[0] in (changed_a, changed_b)
    finally:
        for store in (*stores, setup_store):
            store.close()


def test_postgres_migrates_and_retains_immutable_composite_fact_versions() -> None:
    database_url = get_postgres_database_url()
    _create_pre_sequence_schema(database_url)
    store = CompositeMetadataStore(database_url)
    store.create_schema()
    store.upsert_definition(_definition())

    migrated_v1 = store.list_member_return_facts(
        composite_id="PB_GLOBAL_BALANCED_USD",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        return_view=CompositeReturnView.NET_ACTUAL,
        reporting_currency="USD",
        restatement_sequence=1,
    )
    assert [fact.return_value for fact in migrated_v1] == [Decimal("0.0100")]
    assert migrated_v1[0].restatement_sequence == 1
    with pytest.raises(CompositeMemberReturnFactConflictError):
        store.upsert_member_return_fact(
            _fact(
                return_value="0.0150",
                return_view="NET_ACTUAL",
                restatement_version="legacy-late-family",
                restatement_sequence=1,
                fingerprint="legacy-late-family",
                portfolio_id="PB_SG_GLOBAL_BAL_002",
            )
        )

    net_v2 = _fact(
        return_value="0.0200",
        return_view="NET_ACTUAL",
        restatement_version="correction",
        restatement_sequence=2,
        fingerprint="net-v2",
    )
    gross_v1 = _fact(
        return_value="0.0300",
        return_view="GROSS",
        restatement_version="published",
        restatement_sequence=1,
        fingerprint="gross-v1",
    )
    store.upsert_member_return_fact(net_v2)
    store.upsert_member_return_fact(net_v2)
    store.upsert_member_return_fact(gross_v1)

    with pytest.raises(CompositeMemberReturnFactSelectionError, match="completed publication"):
        _calculated_return(store, return_view=CompositeReturnView.NET_ACTUAL)
    _complete_publication(store, net_v2, source_fingerprint="sha256:net-publication-v2")
    _complete_publication(store, gross_v1, source_fingerprint="sha256:gross-publication-v1")
    _assert_completed_fact_payload_mutation_is_rejected(
        database_url,
        calculation_id=net_v2.calculation_id,
    )
    assert _calculated_return(store, return_view=CompositeReturnView.NET_ACTUAL) == Decimal("0.020000000000")
    assert _calculated_return(
        store,
        return_view=CompositeReturnView.NET_ACTUAL,
        restatement_sequence=1,
    ) == Decimal("0.010000000000")
    assert _calculated_return(store, return_view=CompositeReturnView.GROSS) == Decimal("0.030000000000")
    store.close()

    restarted = CompositeMetadataStore(database_url)
    restarted.create_schema()
    assert restarted.count_records().member_return_facts == 3
    assert _calculated_return(restarted, return_view=CompositeReturnView.NET_ACTUAL) == Decimal("0.020000000000")
    try:
        restarted.list_member_return_facts(
            composite_id="PB_GLOBAL_BALANCED_USD",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            return_view=CompositeReturnView.NET_ACTUAL,
            reporting_currency="USD",
            restatement_sequence=99,
        )
    except CompositeMemberReturnFactSelectionError:
        pass
    else:
        raise AssertionError("Expected missing explicit fact sequence to fail closed")

    conflicting_v2 = CompositeMemberReturnFact.model_validate(
        net_v2.model_dump(mode="json") | {"return_value": "0.0250"}
    )
    try:
        restarted.upsert_member_return_fact(conflicting_v2)
    except CompositeMemberReturnFactConflictError:
        pass
    else:
        raise AssertionError("Expected immutable fact payload conflict")
    assert restarted.count_records().member_return_facts == 3

    partial_v1_a = _fact(
        return_value="0.0100",
        return_view="NET_ACTUAL",
        restatement_version="published",
        restatement_sequence=1,
        fingerprint="partial-v1-a",
        composite_id="PARTIAL_PUBLICATION",
        portfolio_id="P1",
    )
    partial_v1_b = _fact(
        return_value="0.0100",
        return_view="NET_ACTUAL",
        restatement_version="published",
        restatement_sequence=1,
        fingerprint="partial-v1-b",
        composite_id="PARTIAL_PUBLICATION",
        portfolio_id="P2",
    )
    partial_v2_a = _fact(
        return_value="0.0200",
        return_view="NET_ACTUAL",
        restatement_version="correction",
        restatement_sequence=2,
        fingerprint="partial-v2-a",
        composite_id="PARTIAL_PUBLICATION",
        portfolio_id="P1",
    )
    for fact in (partial_v1_a, partial_v1_b, partial_v2_a):
        restarted.upsert_member_return_fact(fact)
    _complete_publication(
        restarted,
        partial_v1_a,
        partial_v1_b,
        source_fingerprint="sha256:partial-publication-v1",
    )
    with pytest.raises(CompositeMemberReturnFactSelectionError):
        restarted.list_member_return_facts(
            composite_id="PARTIAL_PUBLICATION",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            return_view=CompositeReturnView.NET_ACTUAL,
            reporting_currency="USD",
        )

    complete_publication_id = "COMPLETE_PUBLICATION"
    restarted.upsert_definition(
        CompositeDefinition.model_validate(
            _definition().model_dump(mode="json")
            | {
                "composite_id": complete_publication_id,
                "display_name": "Complete publication control",
            }
        )
    )
    publication_v1_a = _fact(
        return_value="0.1000",
        return_view="NET_ACTUAL",
        restatement_version="published",
        restatement_sequence=1,
        fingerprint="complete-v1-a",
        composite_id=complete_publication_id,
        portfolio_id="P1",
    )
    publication_v1_b = _fact(
        return_value="0.0000",
        return_view="NET_ACTUAL",
        restatement_version="published",
        restatement_sequence=1,
        fingerprint="complete-v1-b",
        composite_id=complete_publication_id,
        portfolio_id="P2",
    )
    publication_v2_a = _fact(
        return_value="0.0800",
        return_view="NET_ACTUAL",
        restatement_version="correction",
        restatement_sequence=2,
        fingerprint="complete-v2-a",
        composite_id=complete_publication_id,
        portfolio_id="P1",
    )
    for fact in (publication_v1_a, publication_v1_b):
        restarted.upsert_member_return_fact(fact)
    _complete_publication(
        restarted,
        publication_v1_a,
        publication_v1_b,
        source_fingerprint="sha256:complete-publication-v1",
    )
    assert _calculated_return(
        restarted,
        return_view=CompositeReturnView.NET_ACTUAL,
        composite_id=complete_publication_id,
    ) == Decimal("0.050000000000")

    restarted.upsert_member_return_fact(publication_v2_a)
    with pytest.raises(CompositeMemberReturnFactSelectionError):
        _calculated_return(
            restarted,
            return_view=CompositeReturnView.NET_ACTUAL,
            composite_id=complete_publication_id,
        )

    publication_v2_b = _fact(
        return_value="0.0000",
        return_view="NET_ACTUAL",
        restatement_version="correction-confirmed",
        restatement_sequence=2,
        fingerprint="complete-v2-b-explicit-source",
        composite_id=complete_publication_id,
        portfolio_id="P2",
    )
    restarted.upsert_member_return_fact(publication_v2_b)
    restarted.complete_member_return_fact_publication(
        composite_id=complete_publication_id,
        return_view=CompositeReturnView.NET_ACTUAL,
        reporting_currency="USD",
        restatement_sequence=2,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        expected_families={
            ("P1", date(2026, 1, 1), date(2026, 1, 31)),
            ("P2", date(2026, 1, 1), date(2026, 1, 31)),
        },
        source_fingerprint="sha256:complete-publication-v2",
    )
    assert _calculated_return(
        restarted,
        return_view=CompositeReturnView.NET_ACTUAL,
        composite_id=complete_publication_id,
    ) == Decimal("0.040000000000")
    assert _calculated_return(
        restarted,
        return_view=CompositeReturnView.NET_ACTUAL,
        restatement_sequence=1,
        composite_id=complete_publication_id,
    ) == Decimal("0.050000000000")
    completed_v2 = restarted.list_member_return_facts(
        composite_id=complete_publication_id,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        return_view=CompositeReturnView.NET_ACTUAL,
        reporting_currency="USD",
        restatement_sequence=2,
    )
    assert [fact.source_fingerprint for fact in completed_v2] == [
        "sha256:complete-v2-a",
        "sha256:complete-v2-b-explicit-source",
    ]

    removal_id = "MEMBERSHIP_REMOVAL"
    removal_v1_a = _fact(
        return_value="0.0100",
        return_view="NET_ACTUAL",
        restatement_version="published",
        restatement_sequence=1,
        fingerprint="removal-v1-a",
        composite_id=removal_id,
        portfolio_id="P1",
    )
    removal_v1_b = _fact(
        return_value="0.0200",
        return_view="NET_ACTUAL",
        restatement_version="published",
        restatement_sequence=1,
        fingerprint="removal-v1-b",
        composite_id=removal_id,
        portfolio_id="P2",
    )
    removal_v2_a = _fact(
        return_value="0.0300",
        return_view="NET_ACTUAL",
        restatement_version="membership-correction",
        restatement_sequence=2,
        fingerprint="removal-v2-a",
        composite_id=removal_id,
        portfolio_id="P1",
    )
    for fact in (removal_v1_a, removal_v1_b, removal_v2_a):
        restarted.upsert_member_return_fact(fact)
    _complete_publication(
        restarted,
        removal_v1_a,
        removal_v1_b,
        source_fingerprint="sha256:removal-publication-v1",
    )
    with pytest.raises(CompositeMemberReturnFactSelectionError):
        restarted.list_member_return_facts(
            composite_id=removal_id,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            return_view=CompositeReturnView.NET_ACTUAL,
            reporting_currency="USD",
        )
    restarted.complete_member_return_fact_publication(
        composite_id=removal_id,
        return_view=CompositeReturnView.NET_ACTUAL,
        reporting_currency="USD",
        restatement_sequence=2,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        expected_families={("P1", date(2026, 1, 1), date(2026, 1, 31))},
        source_fingerprint="sha256:removal-publication-v2",
    )
    restarted.close()
    restarted = CompositeMetadataStore(database_url)
    restarted.create_schema()
    assert restarted.list_member_return_facts(
        composite_id=removal_id,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        return_view=CompositeReturnView.NET_ACTUAL,
        reporting_currency="USD",
    ) == [removal_v2_a]
    with pytest.raises(CompositeMemberReturnFactConflictError):
        restarted.upsert_member_return_fact(
            _fact(
                return_value="0.0400",
                return_view="NET_ACTUAL",
                restatement_version="late-family",
                restatement_sequence=2,
                fingerprint="removal-v2-late-p3",
                composite_id=removal_id,
                portfolio_id="P3",
            )
        )

    windowed_id = "WINDOW_SCOPED_PUBLICATION"
    windowed_january = _fact(
        return_value="0.0100",
        return_view="NET_ACTUAL",
        restatement_version="january",
        restatement_sequence=1,
        fingerprint="windowed-january-v1",
        composite_id=windowed_id,
    )
    windowed_february = _fact(
        return_value="0.0200",
        return_view="NET_ACTUAL",
        restatement_version="february",
        restatement_sequence=2,
        fingerprint="windowed-february-v2",
        composite_id=windowed_id,
        period_start="2026-02-01",
        period_end="2026-02-28",
    )
    restarted.upsert_member_return_fact(windowed_january)
    restarted.upsert_member_return_fact(windowed_february)
    _complete_publication(
        restarted,
        windowed_january,
        source_fingerprint="sha256:windowed-january-publication-v1",
    )
    restarted.complete_member_return_fact_publication(
        composite_id=windowed_id,
        return_view=CompositeReturnView.NET_ACTUAL,
        reporting_currency="USD",
        restatement_sequence=2,
        period_start=date(2026, 2, 1),
        period_end=date(2026, 2, 28),
        expected_families={("PB_SG_GLOBAL_BAL_001", date(2026, 2, 1), date(2026, 2, 28))},
        source_fingerprint="sha256:windowed-february-publication-v2",
    )
    assert restarted.list_member_return_facts(
        composite_id=windowed_id,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        return_view=CompositeReturnView.NET_ACTUAL,
        reporting_currency="USD",
    ) == [windowed_january]
    assert restarted.list_member_return_facts(
        composite_id=windowed_id,
        period_start=date(2026, 2, 1),
        period_end=date(2026, 2, 28),
        return_view=CompositeReturnView.NET_ACTUAL,
        reporting_currency="USD",
    ) == [windowed_february]
    with pytest.raises(CompositeMemberReturnFactSelectionError):
        restarted.list_member_return_facts(
            composite_id=windowed_id,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 2, 28),
            return_view=CompositeReturnView.NET_ACTUAL,
            reporting_currency="USD",
        )

    pinned_v1 = _fact(
        return_value="0.0100",
        return_view="NET_ACTUAL",
        restatement_version="published",
        restatement_sequence=1,
        fingerprint="pinned-v1-a",
        composite_id="PINNED_HISTORY",
        portfolio_id="P1",
    )
    pinned_v2_a = _fact(
        return_value="0.0200",
        return_view="NET_ACTUAL",
        restatement_version="correction",
        restatement_sequence=2,
        fingerprint="pinned-v2-a",
        composite_id="PINNED_HISTORY",
        portfolio_id="P1",
    )
    pinned_v2_b = _fact(
        return_value="0.0300",
        return_view="NET_ACTUAL",
        restatement_version="added-member",
        restatement_sequence=2,
        fingerprint="pinned-v2-b",
        composite_id="PINNED_HISTORY",
        portfolio_id="P2",
    )
    for fact in (pinned_v1, pinned_v2_a, pinned_v2_b):
        restarted.upsert_member_return_fact(fact)
    retained_v1 = restarted.list_member_return_facts(
        composite_id="PINNED_HISTORY",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        return_view=CompositeReturnView.NET_ACTUAL,
        reporting_currency="USD",
        restatement_sequence=1,
    )
    assert retained_v1 == [pinned_v1]

    engine = create_engine(database_url, future=True)
    try:
        column_definitions = {
            column["name"]: column for column in inspect(engine).get_columns("composite_member_return_facts")
        }
        definition_columns = {column["name"]: column for column in inspect(engine).get_columns("composite_definitions")}
        definition_check_constraints = {
            constraint["name"] for constraint in inspect(engine).get_check_constraints("composite_definitions")
        }
        indexes = {index["name"] for index in inspect(engine).get_indexes("composite_member_return_facts")}
        check_constraints = {
            constraint["name"]: constraint["sqltext"]
            for constraint in inspect(engine).get_check_constraints("composite_member_return_facts")
        }
        publication_columns = {
            column["name"]: column
            for column in inspect(engine).get_columns("composite_member_return_fact_publications")
        }
        publication_check_constraints = {
            constraint["name"]
            for constraint in inspect(engine).get_check_constraints("composite_member_return_fact_publications")
        }
        with engine.connect() as connection:
            legacy_row = connection.exec_driver_sql(
                "SELECT fact_key, restatement_sequence FROM composite_member_return_facts "
                "WHERE calculation_id = 'calc-net-v1'"
            ).one()
            trigger_names = set(
                connection.scalars(
                    text(
                        "SELECT tgname FROM pg_trigger "
                        "WHERE tgrelid = 'composite_member_return_facts'::regclass "
                        "AND NOT tgisinternal"
                    )
                )
            )
            publication_trigger_names = set(
                connection.scalars(
                    text(
                        "SELECT tgname FROM pg_trigger "
                        "WHERE tgrelid = 'composite_member_return_fact_publications'::regclass "
                        "AND NOT tgisinternal"
                    )
                )
            )
    finally:
        engine.dispose()
        restarted.close()
    assert "restatement_sequence" in column_definitions
    assert definition_columns["reporting_currency"]["nullable"] is False
    assert COMPOSITE_DEFINITION_CURRENCY_CHECK in definition_check_constraints
    assert column_definitions["restatement_version"]["type"].length == 64
    assert column_definitions["restatement_version"]["nullable"] is False
    assert legacy_row == (
        "PB_GLOBAL_BALANCED_USD|PB_SG_GLOBAL_BAL_001|2026-01-01|2026-01-31",
        1,
    )
    assert "uq_composite_member_return_facts_sequence_identity" in indexes
    assert "uq_composite_member_return_facts_version_identity" in indexes
    assert MEMBER_RETURN_FACT_SEQUENCE_CHECK in check_constraints
    assert MEMBER_RETURN_FACT_VERSION_CHECK in check_constraints
    assert POSTGRES_MEMBER_RETURN_FACT_VERSION_CHECK_MARKER in check_constraints[MEMBER_RETURN_FACT_VERSION_CHECK]
    assert MEMBER_RETURN_FACT_CURRENCY_CHECK in check_constraints
    assert MEMBER_RETURN_FACT_IMMUTABLE_UPDATE_TRIGGER in trigger_names
    assert MEMBER_RETURN_FACT_COMPLETED_DELETE_TRIGGER in trigger_names
    assert PUBLICATION_IMMUTABLE_UPDATE_TRIGGER in publication_trigger_names
    assert publication_columns["restatement_sequence"]["nullable"] is False
    assert publication_columns["reporting_currency"]["nullable"] is False
    assert publication_columns["period_start"]["nullable"] is False
    assert publication_columns["period_end"]["nullable"] is False
    assert PUBLICATION_CURRENCY_CHECK in publication_check_constraints
    assert PUBLICATION_SEQUENCE_CHECK in publication_check_constraints
    assert PUBLICATION_PERIOD_CHECK in publication_check_constraints
    _assert_direct_bad_sequence_is_rejected(database_url)
    _assert_direct_blank_version_is_rejected(database_url)
    _assert_direct_malformed_currency_is_rejected(database_url)
    engine = create_engine(database_url, future=True)
    try:
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "UPDATE composite_definitions SET reporting_currency = 'US1' "
                    "WHERE composite_id = 'PB_GLOBAL_BALANCED_USD'"
                )
    finally:
        engine.dispose()
    _assert_direct_invalid_publication_identity_is_rejected(
        database_url,
        "direct-invalid-publication-currency",
        "usd",
        1,
    )
    _assert_direct_invalid_publication_identity_is_rejected(
        database_url,
        "direct-invalid-publication-sequence",
        "USD",
        0,
    )
    engine = create_engine(database_url, future=True)
    try:
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE composite_member_return_fact_publications "
                        "SET period_start = '2025-12-01', expected_families_json = '[]', "
                        "source_fingerprint = 'sha256:mutated-publication' "
                        "WHERE composite_id = :composite_id"
                    ),
                    {"composite_id": complete_publication_id},
                )
    finally:
        engine.dispose()
    maintenance_store = CompositeMetadataStore(database_url)
    try:
        maintenance_store.clear_records_for_composites({complete_publication_id})
        engine = create_engine(database_url, future=True)
        try:
            with engine.connect() as connection:
                retained_counts = connection.execute(
                    text(
                        "SELECT "
                        "(SELECT count(*) FROM composite_member_return_facts WHERE composite_id = :composite_id), "
                        "(SELECT count(*) FROM composite_member_return_fact_publications "
                        "WHERE composite_id = :composite_id)"
                    ),
                    {"composite_id": complete_publication_id},
                ).one()
        finally:
            engine.dispose()
        assert retained_counts == (0, 0)
    finally:
        maintenance_store.close()


def test_postgres_upgrade_rejects_invalid_retained_metadata() -> None:
    period_database_url = get_postgres_database_url()
    _create_null_publication_period_schema(period_database_url)
    store = CompositeMetadataStore(period_database_url)
    try:
        with pytest.raises(RuntimeError, match="invalid publication period"):
            store.create_schema()
    finally:
        store.close()

    currency_database_url = get_postgres_database_url()
    _create_unicode_currency_schema(currency_database_url)
    store = CompositeMetadataStore(currency_database_url)
    try:
        with pytest.raises(RuntimeError, match="invalid reporting_currency.*composite_definitions"):
            store.create_schema()
    finally:
        store.close()

    version_database_url = get_postgres_database_url()
    _create_whitespace_version_schema(version_database_url)
    store = CompositeMetadataStore(version_database_url)
    try:
        with pytest.raises(RuntimeError, match="invalid restatement_version"):
            store.create_schema()
    finally:
        store.close()


def test_postgres_fresh_schema_enforces_positive_composite_fact_sequence() -> None:
    database_url = get_postgres_database_url()
    store = CompositeMetadataStore(database_url)
    store.create_schema()
    store.close()

    engine = create_engine(database_url, future=True)
    try:
        check_constraints = {
            constraint["name"]: constraint["sqltext"]
            for constraint in inspect(engine).get_check_constraints("composite_member_return_facts")
        }
    finally:
        engine.dispose()
    assert MEMBER_RETURN_FACT_SEQUENCE_CHECK in check_constraints
    assert MEMBER_RETURN_FACT_VERSION_CHECK in check_constraints
    assert POSTGRES_MEMBER_RETURN_FACT_VERSION_CHECK_MARKER in check_constraints[MEMBER_RETURN_FACT_VERSION_CHECK]
    assert MEMBER_RETURN_FACT_CURRENCY_CHECK in check_constraints
    _assert_fresh_schema_defaults_legacy_writer_to_first_sequence(database_url)
    _assert_direct_bad_sequence_is_rejected(database_url)
    _assert_direct_blank_version_is_rejected(database_url)
    _assert_direct_malformed_currency_is_rejected(database_url)
