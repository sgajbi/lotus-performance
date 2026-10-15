"""Configured trust and exact-purpose refusal controls, independent of financial fixtures."""

import json
from dataclasses import replace
from datetime import timedelta
from threading import Event
from types import SimpleNamespace

import pytest

from app.adapters.composite_attribution_artifact_source import ConfiguredAttributionSource, decode_bundle
from app.adapters.composite_attribution_bootstrap import bootstrap_composite_attribution
from app.adapters.composite_attribution_configuration import CONFIG_ENV, decode_configuration
from app.adapters.composite_attribution_deployment import get_composite_attribution_deployment
from app.adapters.composite_attribution_purpose_verifier import ConfiguredAttributionPurposeVerifier
from app.adapters.composite_source_authority_deployment import ConfiguredSourceAuthorities, original_request_digest
from app.models.composite_authority import ManageCompositeDefinitionV2, authority_digest
from app.models.composite_eligibility_evidence import VerificationRequest
from app.ports import composite_external_evidence as ports
from app.ports.composite_attribution import AttributionAdmissionError
from app.services.composite_materialization.authority_policy import ProviderTrustRequest, provider_trust_resolver
from tests.composite_attribution_deployment_helpers import DeploymentControl, reset_installation
from tests.composite_authority_helpers import command_for_packet, rehash_definition, shared_packet


@pytest.fixture
def control(tmp_path):
    return DeploymentControl(tmp_path)


def source_for(control):
    return ConfiguredAttributionSource(control.configuration(), control.authority())


@pytest.mark.parametrize("configuration", ["absent", "valid", "malformed"])
def test_actual_worker_bootstraps_before_durable_verification_and_logs_only_valid_installation(
    control, monkeypatch, caplog, configuration
):
    from app.workers import compute_executor_worker as worker

    reset_installation(monkeypatch)
    monkeypatch.delenv(CONFIG_ENV, raising=False)
    if configuration != "absent":
        monkeypatch.setenv(CONFIG_ENV, control.write())
    if configuration == "malformed":
        control.config_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(worker, "setup_worker_logging", lambda level: None)
    calls = []

    def verify(**kwargs):
        installation = bootstrap_composite_attribution()
        assert (installation is not None) == (configuration == "valid")
        calls.append("verify")

    monkeypatch.setattr(worker, "verify_durable_metadata_stores", verify)
    monkeypatch.setattr(worker, "process_pending_jobs", lambda **kwargs: pytest.fail("No job may be claimed"))
    stop = Event()
    stop.set()
    settings = SimpleNamespace(LOG_LEVEL="INFO", COMPUTE_EXECUTOR_WORKER_ID="controlled-worker")
    with caplog.at_level("INFO", logger=worker.__name__):
        if configuration == "malformed":
            with pytest.raises(ValueError):
                worker.run_forever(stop_event=stop, settings=settings)
        else:
            worker.run_forever(stop_event=stop, settings=settings)
    assert calls == ([] if configuration == "malformed" else ["verify"])
    receipts = [record for record in caplog.records if record.message == "Composite attribution deployment installed"]
    if configuration == "valid":
        assert len(receipts) == 1
        installation = bootstrap_composite_attribution()
        assert receipts[0].extra_fields == {
            "worker_name": "compute_executor_worker",
            "worker_id": "controlled-worker",
            "queue": "compute",
            "configuration_digest": installation.configuration_digest,
            "revision": installation.revision,
            "profile": "CONTROLLED_SYNTHETIC_ONLY",
            "qualification": "SYNTHETIC_NON_CERTIFYING",
        }
    else:
        assert receipts == []


def test_configuration_accepts_valid_public_profile_and_refuses_duplicate_json(control):
    assert decode_configuration(json.dumps(control.payload)).profile == "CONTROLLED_SYNTHETIC_ONLY"
    with pytest.raises(ValueError, match="Duplicate"):
        decode_configuration('{"profile":"UNAVAILABLE","profile":"CONTROLLED_SYNTHETIC_ONLY"}')


@pytest.mark.parametrize(
    "change", ["private-key", "institutional", "duplicate-actor", "foreign-tenant", "duplicate-manifest", "naive-time"]
)
def test_configuration_rejects_unsupported_or_conflicting_deployment(control, change):
    if change == "private-key":
        control.payload["producer_trust"]["jwks"]["keys"][0]["d"] = "private"
    elif change == "institutional":
        control.payload["profile"] = "OWNER_QUALIFIED_SOURCE"
    elif change == "duplicate-actor":
        control.payload["actors"].append(control.payload["actors"][0])
    elif change == "foreign-tenant":
        control.payload["actors"][0]["tenant_id"] = "foreign"
    elif change == "duplicate-manifest":
        control.payload["sources"].append(control.payload["sources"][0])
    else:
        control.payload["valid_until"] = "2026-01-01T00:00:00"
    with pytest.raises(ValueError):
        control.configuration()


def test_source_retains_original_bytes_and_returns_fresh_nested_projections(control):
    source = source_for(control)
    first = source.read_pinned(control.request, tenant_id=control.bundle.tenant_id)
    first.raw_source_bodies.clear()
    control.bundle_path.write_text("withdrawn", encoding="utf-8")
    assert source.read_pinned(control.request, tenant_id=control.bundle.tenant_id) == control.bundle
    assert (
        source.read_population_scope(control.request, tenant_id=control.bundle.tenant_id)
        == control.bundle.expected_portfolio_ids
    )
    with pytest.raises(AttributionAdmissionError):
        source_for(control).read_pinned(control.request, tenant_id=control.bundle.tenant_id)


def test_source_refuses_foreign_tenant_and_scope_before_financial_read(control):
    source = source_for(control)
    with pytest.raises(AttributionAdmissionError, match="unavailable"):
        source.read_population_scope(control.request, tenant_id="foreign")
    changed = control.request.model_copy(update={"policy_binding_id": "another-policy"})
    with pytest.raises(AttributionAdmissionError, match="exact request"):
        source.read_population_scope(changed, tenant_id=control.bundle.tenant_id)


def test_signed_population_metadata_cannot_be_replaced_by_deployment_grants(control, monkeypatch):
    control.payload["sources"][0]["expected_portfolio_ids"] = ["different-member"]
    control.payload["expected_portfolio_ids"] = ["different-member"]
    control.payload["actors"][0]["portfolio_scope"].append("different-member")
    source = source_for(control)

    def forbidden_read(*args, **kwargs):
        raise AssertionError("Population admission cannot open financial source artifacts.")

    monkeypatch.setattr("app.adapters.composite_attribution_artifact_source.read_bounded", forbidden_read)
    with pytest.raises(AttributionAdmissionError):
        source.read_population_scope(control.request, tenant_id=control.bundle.tenant_id)


@pytest.mark.parametrize("bad", ["signature", "issuer", "audience", "purpose", "digest", "expired", "revoked", "scope"])
def test_source_evidence_rejects_bad_signature_authority_and_scope(control, bad):
    evidence = control.payload["sources"][0]["evidence"]
    if bad == "signature":
        evidence["credential"] = evidence["credential"][:-8] + "AAAAAAAA"
    elif bad == "revoked":
        control.payload["revoked_credential_ids"] = ["revoked"]
        control.resign(evidence, jti="revoked")
    elif bad == "scope":
        control.payload["actors"][0]["portfolio_scope"] = []
    else:
        changes = {
            "issuer": {"iss": "foreign"},
            "audience": {"aud": "foreign"},
            "purpose": {"purpose": "RETURN_METHOD_CALENDAR"},
            "digest": {"request_digest": "sha256:" + "f" * 64},
            "expired": {"exp": 1},
        }[bad]
        control.resign(evidence, **changes)
    with pytest.raises(AttributionAdmissionError):
        source_for(control).read_pinned(control.request, tenant_id=control.bundle.tenant_id)


def test_financial_artifact_rejects_duplicate_and_nonfinite_raw_numbers(control):
    with pytest.raises(ValueError, match="Duplicate"):
        decode_bundle('{"tenant_id":"a","tenant_id":"b"}')
    with pytest.raises(ValueError):
        decode_bundle('{"raw_source_bodies":{"bad":NaN}}')


def test_bf_approval_binds_complete_original_and_canonical_independence(control):
    source = source_for(control)
    verifier = ConfiguredAttributionPurposeVerifier(source)
    approval = verifier.verify(control.request, control.bundle)
    assert approval == verifier.verify(control.request, control.bundle)
    assert approval.qualification == "SYNTHETIC_NON_CERTIFYING"
    assert approval.canonical_maker != approval.canonical_checker
    assert approval.bundle_digest == authority_digest(control.bundle.model_dump(mode="json"))
    changed = control.bundle.model_copy(update={"benchmark_revision": "other"})
    with pytest.raises(AttributionAdmissionError):
        verifier.verify(control.request, changed)
    control.payload["actors"][1]["canonical_identity"] = "canonical-maker"
    with pytest.raises(AttributionAdmissionError):
        ConfiguredAttributionPurposeVerifier(source_for(control)).verify(control.request, control.bundle)


def test_expired_deployment_refuses_scope_without_refreshing_source(control):
    source = source_for(control)
    source.authority.now = lambda: control.now + timedelta(days=1)
    with pytest.raises(AttributionAdmissionError) as denied:
        source.read_population_scope(control.request, tenant_id=control.bundle.tenant_id)
    assert denied.value.code == "SOURCE_AUTHORITY_UNAVAILABLE"


def test_bootstrap_shared_once_only_installation_and_default_unavailable(control, monkeypatch):
    reset_installation(monkeypatch)
    monkeypatch.delenv(CONFIG_ENV, raising=False)
    assert bootstrap_composite_attribution() is None
    with pytest.raises(AttributionAdmissionError):
        get_composite_attribution_deployment().source.read_population_scope(
            control.request, tenant_id=control.bundle.tenant_id
        )
    monkeypatch.setenv(CONFIG_ENV, control.write())
    application = SimpleNamespace(state=SimpleNamespace())
    installed = bootstrap_composite_attribution(application=application)
    assert installed is bootstrap_composite_attribution()
    assert application.state.composite_attribution_installation["qualification"] == "SYNTHETIC_NON_CERTIFYING"
    control.payload["revision"] = "changed"
    control.write()
    with pytest.raises(RuntimeError, match="cannot change"):
        bootstrap_composite_attribution()


def original_request(control):
    packet = shared_packet("original")
    packet["definition"]["created_by"] = "maker"
    rehash_definition(packet["definition"])
    definition = ManageCompositeDefinitionV2.model_validate(packet["definition"])
    return ports.CompositeApprovalRequest(
        "RETURN_METHOD_CALENDAR",
        control.bundle.tenant_id,
        definition.composite_id,
        definition.definition_version,
        definition.source_authority.payload.return_method_binding,
        "2026-09-01",
        "2026-09-30",
        definition,
        command_for_packet(packet),
        authority_digest({"universe": "original"}),
        control.bundle.expected_portfolio_ids,
    )


def test_original_approval_is_exact_and_retained_attempt_identity_is_not_financial(control, monkeypatch):
    request = original_request(control)
    control.payload["source_authorities"] = [
        {
            "kind": "APPROVAL",
            "evidence": control.registration(
                request.purpose,
                original_request_digest(request),
                json.dumps({"maker_subject": "maker"}),
            ),
        }
    ]
    reset_installation(monkeypatch)
    monkeypatch.setenv(CONFIG_ENV, control.write())
    bootstrap_composite_attribution()
    assert ports.method_approval_verifier().verify(request) is True
    assert ports.method_approval_verifier().verify(replace(request, universe_digest="sha256:" + "f" * 64)) is False
    assert original_request_digest(request) == original_request_digest(
        replace(request, command=request.command.model_copy(update={"calculation_id": control.request.calculation_id}))
    )
    assert (
        ports.authority_approval_verifier().verify(replace(request, purpose="COMPOSITE_ECONOMIC_AUTHORITY_PROFILE"))
        is False
    )


def test_provider_registration_binds_product_revision_cut_and_tenant(control, monkeypatch):
    request = ProviderTrustRequest(
        control.bundle.tenant_id, "provider", "revision", "sha256:" + "e" * 64, "TWR", "2026-01-01", "2026-01-31"
    )
    control.payload["source_authorities"] = [
        {
            "kind": "PROVIDER",
            "evidence": control.registration(
                "PROVIDER_REGISTRATION",
                original_request_digest(request),
                json.dumps({"registration_digest": request.registry_digest}),
            ),
        }
    ]
    reset_installation(monkeypatch)
    monkeypatch.setenv(CONFIG_ENV, control.write())
    bootstrap_composite_attribution()
    assert provider_trust_resolver().resolve(request).posture == "SYNTHETIC_TEST_ONLY"
    assert provider_trust_resolver().resolve(replace(request, source_product="other")).posture == "UNAVAILABLE"
    assert (
        ConfiguredSourceAuthorities(control.authority()).resolve(replace(request, tenant_id="other")).posture
        == "UNAVAILABLE"
    )


def test_original_receipt_verifies_full_signed_wire_and_refuses_other_purpose(control, monkeypatch):
    digest = "sha256:" + "e" * 64
    request = VerificationRequest(
        binding=None,
        claims_digest=digest,
        composite_id=control.bundle.composite_id,
        definition_version="definition-v1",
        effective_from="2026-01-01",
        effective_to="2026-01-31",
        purpose="ELIGIBILITY_POLICY",
        source_product=None,
        subject_content_hash=digest,
        tenant_id=control.bundle.tenant_id,
    )
    payload = {
        "artifact_digest": digest,
        "artifact_revision": "artifact-v1",
        "issuer_id": "independent-verifier",
        "posture": "SYNTHETIC_NON_CERTIFYING",
        "product_name": "CompositeEvidenceVerificationReceipt",
        "product_version": "v1",
        "request": request.model_dump(mode="json"),
        "verifier_id": "verifier",
    }
    payload["content_hash"] = authority_digest(payload)
    control.payload["source_authorities"] = [
        {
            "kind": "RECEIPT",
            "evidence": control.registration(
                request.purpose,
                original_request_digest(request),
                json.dumps(payload),
            ),
        }
    ]
    reset_installation(monkeypatch)
    monkeypatch.setenv(CONFIG_ENV, control.write())
    bootstrap_composite_attribution()
    result = ports.composite_receipt_verifier().verify(request)
    assert (
        ports.admit_verified_receipt(result.expectation, result, allow_synthetic=True).model_dump(mode="json")
        == payload
    )
    assert isinstance(
        ports.composite_receipt_verifier().verify(request.model_copy(update={"purpose": "RETURN_METHOD_CALENDAR"})),
        ports.UnavailableCompositeEvidence,
    )


def test_fresh_bootstrap_never_reads_financial_source_or_reapproves_bf(control, monkeypatch):
    reset_installation(monkeypatch)
    control.bundle_path.unlink()
    control.payload["sources"][0]["approval"]["credential"] = "withdrawn-financial-authority"
    monkeypatch.setenv(CONFIG_ENV, control.write())
    assert bootstrap_composite_attribution().profile == "CONTROLLED_SYNTHETIC_ONLY"
    source = get_composite_attribution_deployment().source
    assert (
        source.read_population_scope(control.request, tenant_id=control.bundle.tenant_id)
        == control.bundle.expected_portfolio_ids
    )
    with pytest.raises(AttributionAdmissionError):
        source.read_pinned(control.request, tenant_id=control.bundle.tenant_id)


def test_original_authority_only_stage_needs_no_guessed_bf_candidate(control, monkeypatch):
    request = original_request(control)
    control.payload["source_authorities"] = [
        {
            "kind": "APPROVAL",
            "evidence": control.registration(
                request.purpose,
                original_request_digest(request),
                json.dumps({"maker_subject": "maker"}),
            ),
        }
    ]
    control.payload["sources"] = []
    control.bundle_path.unlink()
    reset_installation(monkeypatch)
    monkeypatch.setenv(CONFIG_ENV, control.write())
    bootstrap_composite_attribution()
    assert ports.method_approval_verifier().verify(request) is True
    with pytest.raises(AttributionAdmissionError) as refused:
        get_composite_attribution_deployment().source.read_population_scope(
            control.request, tenant_id=control.bundle.tenant_id
        )
    assert refused.value.code == "SOURCE_AUTHORITY_UNAVAILABLE"
