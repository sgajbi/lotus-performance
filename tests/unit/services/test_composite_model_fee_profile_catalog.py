"""Real catalog custody, conflicting publication and owner rollback controls."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace
from unittest.mock import Mock

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm.exc import MultipleResultsFound

from app.adapters.composite_model_fee_profile_records import CompositeModelFeeProfileModel
from app.adapters.composite_model_fee_profile_schema import rollback_empty_model_fee_profile_catalog
from app.adapters.composite_model_fee_profile_storage import publish_profile, resolve_profile
from app.models.composite_model_fees import CompositePeriodicModelFeeProfile
from app.ports.composite_model_fees import CompositeModelFeeResolutionRequest
from app.services.composite_metadata_store import CompositeMetadataStore
from core.errors import APIConflictError, APIError
from scripts.durable_schema_apply import apply_durable_schema
from tests.composite_model_fee_helpers import profile_wire


@pytest.fixture
def catalog(tmp_path):
    url = "sqlite:///" + (tmp_path / "catalog.db").as_posix()
    evidence = apply_durable_schema(database_url=url)
    assert evidence.status == "passed", evidence
    assert len(evidence.schema_verification_checks) == 6
    store = CompositeMetadataStore(url)
    try:
        yield store
    finally:
        store.close()


def publish(store, wire=None, actor="original-publisher"):
    profile = CompositePeriodicModelFeeProfile.model_validate(wire or profile_wire())
    return store.publish_model_fee_profile(profile, tenant_id="TENANT_A", actor_id=actor)


def request(receipt):
    return CompositeModelFeeResolutionRequest(
        tenant_id="TENANT_A",
        composite_id=receipt.profile.composite_id,
        binding=receipt.binding,
        definition_content_hash="synthetic",
        membership_content_hash="synthetic",
        attestation_content_hash="synthetic",
        source_cut_id="synthetic",
        period_start="2026-01-01",
        period_end="2026-01-31",
        reporting_currency="USD",
        expected_members=("MEMBER_A",),
    )


def test_original_custody_retry_correction_and_exact_binding(catalog):
    original = publish(catalog)
    assert publish(catalog, actor="retry-publisher") == original
    corrected = deepcopy(profile_wire())
    corrected["revision"] = "profile.2"
    corrected["periods"][0]["member_rates"][0]["period_fee_fraction"] = "0.003"
    correction = publish(catalog, corrected, actor="correction-publisher")
    assert catalog.resolve_model_fee_profile(request(original)) == original
    assert catalog.resolve_model_fee_profile(request(correction)) == correction
    assert catalog.resolve_model_fee_profile(replace(request(original), tenant_id="TENANT_B")) is None
    assert catalog.resolve_model_fee_profile(replace(request(original), composite_id="OTHER")) is None
    assert (
        catalog.get_model_fee_profile(
            tenant_id="TENANT_A", profile_id=original.profile.profile_id, revision="profile.1"
        )
        == original
    )
    assert original.published_by == "original-publisher"
    assert original.posture == "UNAPPROVED_METHOD_INPUT"
    from app.adapters.composite_model_fee_profile_source import RetainedCompositeModelFeeSource
    from app.ports.composite_external_evidence import UnavailableCompositeEvidence

    source = RetainedCompositeModelFeeSource(catalog)
    assert source.resolve(request(original)) == original.profile.model_dump(mode="json")
    assert isinstance(source.resolve(replace(request(original), tenant_id="TENANT_B")), UnavailableCompositeEvidence)


def test_concurrent_conflicting_identity_preserves_one_original(catalog):
    corrected = deepcopy(profile_wire())
    corrected["periods"][0]["member_rates"][0]["period_fee_fraction"] = "0.003"

    def attempt(wire, actor):
        try:
            return publish(catalog, wire, actor)
        except APIConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(attempt, wire, actor)
            for wire, actor in ((profile_wire(), "publisher-a"), (corrected, "publisher-b"))
        ]
        results = [future.result() for future in futures]
    assert results.count("conflict") == 1
    winner = next(result for result in results if result != "conflict")
    assert catalog.resolve_model_fee_profile(request(winner)) == winner


@pytest.mark.parametrize(
    "operation",
    ["UPDATE composite_model_fee_profiles SET published_by='replacement'", "DELETE FROM composite_model_fee_profiles"],
)
def test_database_mutation_guard_rejects_retained_content(catalog, operation):
    original = publish(catalog)
    with pytest.raises(DBAPIError, match="immutable"):
        with catalog._engine.begin() as connection:
            connection.exec_driver_sql(operation)
    assert catalog.resolve_model_fee_profile(request(original)) == original


def test_populated_rollback_refuses_and_empty_rollback_is_owner_only(catalog):
    rollback_empty_model_fee_profile_catalog(catalog._engine)
    assert not inspect(catalog._engine).has_table("composite_model_fee_profiles")
    catalog.create_schema()
    catalog.verify_schema()
    original = publish(catalog)
    with pytest.raises(RuntimeError, match="refuses loss"):
        rollback_empty_model_fee_profile_catalog(catalog._engine)
    catalog.verify_schema()
    assert catalog.resolve_model_fee_profile(request(original)) == original


@pytest.mark.parametrize(
    "field,value",
    [("tenant_id", " bad tenant "), ("product_name", "UnapprovedOtherProduct"), ("content_digest", "sha256:short")],
)
def test_database_catalog_identity_guards_refuse_bad_insert(catalog, field, value):
    original = publish(catalog)
    columns = (
        "tenant_id",
        "profile_id",
        "revision",
        "composite_id",
        "product_name",
        "product_version",
        "content_digest",
        "profile_json",
        "published_by",
        "published_at_utc",
    )
    from sqlalchemy import text

    with catalog._engine.connect() as connection:
        retained = dict(connection.execute(text("SELECT * FROM composite_model_fee_profiles")).mappings().one())
    retained.update(profile_id="bad-profile", revision="bad-revision")
    retained[field] = value
    statement = text(
        f"INSERT INTO composite_model_fee_profiles ({','.join(columns)}) VALUES ({','.join(':'+column for column in columns)})"
    )
    with pytest.raises(DBAPIError):
        with catalog._engine.begin() as connection:
            connection.execute(statement, retained)
    assert catalog.resolve_model_fee_profile(request(original)) == original


def test_retained_hash_check_refuses_storage_corruption(catalog):
    original = publish(catalog)
    with catalog._engine.begin() as connection:
        # Diagnostic corruption in this owned test database bypasses a trigger;
        # the read must independently reject mismatched canonical evidence.
        connection.exec_driver_sql("DROP TRIGGER trg_model_fee_profiles_immutable_update")
        connection.exec_driver_sql("UPDATE composite_model_fee_profiles SET profile_json='{}'")
    with pytest.raises(APIError) as refused:
        catalog.resolve_model_fee_profile(request(original))
    assert refused.value.error_code == "COMPOSITE_MODEL_FEE_PROFILE_RETAINED_EVIDENCE_REFUSED"


@pytest.mark.parametrize("actor", ["", " actor ", "a" * 129])
def test_storage_publication_refuses_bad_original_actor_without_database_calls(actor):
    session = Mock()
    with pytest.raises(APIError) as refused:
        publish_profile(
            session,
            CompositePeriodicModelFeeProfile.model_validate(profile_wire()),
            tenant_id="TENANT_A",
            actor_id=actor,
        )
    assert refused.value.error_code == "COMPOSITE_MODEL_FEE_PROFILE_ACTOR_REQUIRED"
    assert session.mock_calls == []


def test_storage_publication_refuses_cross_tenant_profile_without_database_calls():
    session = Mock()
    with pytest.raises(APIConflictError) as refused:
        publish_profile(
            session,
            CompositePeriodicModelFeeProfile.model_validate(profile_wire()),
            tenant_id="TENANT_B",
            actor_id="publisher",
        )
    assert refused.value.error_code == "COMPOSITE_MODEL_FEE_PROFILE_TENANT_MISMATCH"
    assert session.mock_calls == []


@pytest.mark.parametrize("winner", ["same", "conflicting", "absent"])
def test_failed_insert_rechecks_exact_committed_winner(catalog, winner):
    original = publish(catalog)
    with catalog._session() as retained:
        row = retained.get(
            CompositeModelFeeProfileModel, ("TENANT_A", original.profile.profile_id, original.profile.revision)
        )
        retained.expunge(row)
    session = Mock()
    session.get.side_effect = [None, row if winner != "absent" else None]
    session.begin_nested.return_value = nullcontext()
    session.flush.side_effect = IntegrityError("controlled unique collision", {}, Exception("collision"))
    wire = deepcopy(profile_wire())
    if winner == "conflicting":
        wire["periods"][0]["member_rates"][0]["period_fee_fraction"] = "0.004"
    profile = CompositePeriodicModelFeeProfile.model_validate(wire)
    if winner == "same":
        assert publish_profile(session, profile, tenant_id="TENANT_A", actor_id="retry") == original
    else:
        with pytest.raises(APIError) as refused:
            publish_profile(session, profile, tenant_id="TENANT_A", actor_id="retry")
        assert refused.value.error_code == (
            "COMPOSITE_MODEL_FEE_PROFILE_CONTENT_CONFLICT"
            if winner == "conflicting"
            else "COMPOSITE_MODEL_FEE_PROFILE_RETAINED_EVIDENCE_REFUSED"
        )
    assert session.get.call_args.kwargs == {"populate_existing": True}
    assert catalog.resolve_model_fee_profile(request(original)) == original


def test_ambiguous_binding_refuses_instead_of_selecting_an_arbitrary_profile(catalog):
    original = publish(catalog)
    session = Mock()
    session.scalars.return_value.one_or_none.side_effect = MultipleResultsFound("controlled corrupt binding")
    with pytest.raises(APIError) as refused:
        resolve_profile(session, request(original))
    assert refused.value.error_code == "COMPOSITE_MODEL_FEE_PROFILE_RETAINED_EVIDENCE_REFUSED"
    assert catalog.resolve_model_fee_profile(request(original)) == original


@pytest.mark.parametrize("corruption", ["canonical_layout", "digest", "actor", "naive_time"])
def test_valid_json_with_corrupt_identity_or_custody_refuses_on_read(catalog, corruption):
    from sqlalchemy import text

    original = publish(catalog)
    statements = {
        "canonical_layout": ("profile_json", " " + original.profile.model_dump_json()),
        "digest": ("content_digest", "sha256:" + "0" * 64),
        "actor": ("published_by", " actor "),
        "naive_time": ("published_at_utc", "2026-01-01T00:00:00"),
    }
    column, value = statements[corruption]
    with catalog._engine.begin() as connection:
        connection.exec_driver_sql("DROP TRIGGER trg_model_fee_profiles_immutable_update")
        connection.execute(text(f"UPDATE composite_model_fee_profiles SET {column}=:value"), {"value": value})
    with pytest.raises(APIError) as refused:
        catalog.get_model_fee_profile(
            tenant_id="TENANT_A", profile_id=original.profile.profile_id, revision=original.profile.revision
        )
    assert refused.value.error_code == "COMPOSITE_MODEL_FEE_PROFILE_RETAINED_EVIDENCE_REFUSED"
