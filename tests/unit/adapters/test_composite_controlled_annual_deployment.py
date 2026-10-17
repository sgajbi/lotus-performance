"""Public retained anchors, exact registration, time and immutable custody controls."""

import json
import logging
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from app.adapters import composite_controlled_annual_bootstrap as bootstrap
from app.adapters.composite_controlled_annual_configuration import CONFIG_ENV, decode_annual_configuration
from app.adapters.composite_controlled_annual_verification import ConfiguredControlledYearVerification
from app.models.composite_authority import authority_digest
from app.models.composite_controlled_annual_authority import ControlledYearBasisVerification
from app.observability import JsonFormatter
from app.ports import composite_controlled_annual_evidence as ports
from tests.composite_controlled_annual_deployment_helpers import annual_package, resign
from tests.composite_controlled_annual_helpers import competing_receipt


def verifier(payload=None, now=None):
    return ConfiguredControlledYearVerification(
        decode_annual_configuration(json.dumps(payload or annual_package())), now=now
    )


def test_exact_original_retains_raw_source_and_historical_admission_after_original_expiry():
    payload = annual_package()
    adapter = verifier(payload, now=lambda: datetime(2030, 1, 1, tzinfo=UTC))
    proof = ControlledYearBasisVerification.model_validate(payload["registrations"][0]["proof"])
    result = adapter.verify(proof.request)
    assert ports.admit_controlled_year_verification(proof, result) == proof
    assert result.proof.basis_mapping.raw_original_base64 == proof.basis_mapping.raw_original_base64
    result.proof.candidate_evidence.clear()
    payload["registrations"].clear()
    assert adapter.verify(proof.request).proof == proof


@pytest.mark.parametrize(
    "field,value",
    [
        ("revision", "foreign"),
        ("actor_id", "foreign"),
        ("intent_digest", "sha256:" + "0" * 64),
        ("tenant_id", "foreign"),
        ("profile_configuration_digest", "sha256:" + "0" * 64),
    ],
)
def test_unknown_exact_request_is_unavailable(field, value):
    adapter = verifier()
    request = ControlledYearBasisVerification.model_validate(annual_package()["registrations"][0]["proof"]).request
    assert adapter.verify(request.model_copy(update={field: value})) is None


@pytest.mark.parametrize(
    "field",
    [
        "verifier_id",
        "signer_principal_id",
        "verifier_principal_id",
        "configuration_digest",
        "revocation_revision",
        "revocation_digest",
        "source_evidence_digest",
        "signer_key_digest",
        "verifier_key_digest",
    ],
)
def test_independently_registered_anchor_mismatch_refuses_startup(field):
    payload = annual_package()
    payload["registrations"][0]["anchor"][field] = "sha256:" + "0" * 64 if "digest" in field else "foreign"
    with pytest.raises(ValueError):
        verifier(payload)


@pytest.mark.parametrize("field", ["source_key_valid_to", "verifier_key_valid_to"])
def test_original_key_validity_is_checked_at_original_signature_time(field):
    payload = annual_package()
    payload["registrations"][0]["anchor"][field] = "2026-01-01T00:00:00.000000Z"
    with pytest.raises(ValueError, match="KEY_WINDOW"):
        verifier(payload)


def test_current_deployment_expiry_future_start_and_revocation_refuse_new_operation():
    payload = annual_package()
    request = ControlledYearBasisVerification.model_validate(payload["registrations"][0]["proof"]).request
    for instant in (datetime(2025, 1, 1, tzinfo=UTC), datetime(2100, 1, 1, tzinfo=UTC)):
        assert verifier(payload, now=lambda: instant).verify(request) is None
    payload["revoked_request_digests"] = [payload["registrations"][0]["request_digest"]]
    assert verifier(payload).verify(request) is None


@pytest.mark.parametrize(
    "mutation", ["foreign_key", "foreign_source", "configuration", "revision", "candidate", "registry"]
)
def test_correctly_resigned_self_consistent_substitutions_cannot_replace_registered_original(mutation):
    payload = annual_package()
    registration = payload["registrations"][0]
    if mutation not in {"foreign_key", "foreign_source"}:
        # Independently provision the known test signer before constructing any changed proof.
        registration["anchor"].update(
            verifier_public_key_base64="Zs1gi5KLiOUODv6qM/rxxDzv4HKUsLh+n+CrpqPPdjM=",
            verifier_key_digest="sha256:56fae12f7716462746a3a802817ca762f4e6217028b66e1a70a2a6a2e71b7fc7",
        )
        resign(registration["proof"])
        registration["proof_digest"] = registration["proof"]["content_hash"]
    adapter = verifier(payload)
    proof = (
        competing_receipt()["finalization"]["year_authority_verification"]
        if mutation == "foreign_source"
        else deepcopy(payload["registrations"][0]["proof"])
    )
    if mutation == "configuration":
        proof["configuration_digest"] = proof["request"]["profile_configuration_digest"] = "sha256:" + "1" * 64
    elif mutation == "revision":
        proof["request"]["revision"] = "foreign-subject"
    elif mutation == "candidate":
        proof["candidate_evidence"][0]["generated_at"] = "2026-10-17T00:13:30.000000Z"
    elif mutation == "registry":
        proof["verifier_id"] = "foreign-registry-verifier"
    resign(proof)
    # Model acceptance proves a fresh, coherent cryptographic envelope rather than stale self hashes.
    if mutation == "candidate":
        from tests.composite_controlled_annual_helpers import hash_envelope

        hash_envelope(proof["candidate_evidence"][0])
        proof["source_evidence_digest"] = authority_digest(
            {"basis_mapping": proof["basis_mapping"], "candidate_evidence": proof["candidate_evidence"]}
        )
        resign(proof)
    decoded = ControlledYearBasisVerification.model_validate(proof)
    result = adapter.verify(decoded.request)
    if result is not None:
        with pytest.raises(ValueError, match="BINDING_MISMATCH"):
            ports.admit_controlled_year_verification(decoded, result)
    else:
        assert decoded.request != payload["registrations"][0]["proof"]["request"]
    payload["registrations"][0]["proof"] = proof
    # Update the proof fingerprint too; preserve the independent request pin for a changed revision.
    registration["proof_digest"] = proof["content_hash"]
    if mutation != "revision":
        registration["request_digest"] = authority_digest(proof["request"])
    with pytest.raises(ValueError):
        verifier(payload)


@pytest.mark.parametrize(
    "mutation", ["private", "institutional", "tenant", "duplicate", "month", "alias", "nonfinite", "unknown"]
)
def test_closed_package_refuses_invalid_or_ambiguous_custody(mutation, tmp_path, monkeypatch):
    payload = annual_package()
    if mutation == "private":
        payload["registrations"][0]["anchor"]["private_key"] = "forbidden"
    elif mutation == "institutional":
        payload["profile"] = "INSTITUTIONAL"
    elif mutation == "tenant":
        payload["tenant_id"] = "foreign"
    elif mutation == "duplicate":
        payload["registrations"].append(deepcopy(payload["registrations"][0]))
    elif mutation == "month":
        payload["registrations"][0]["proof"]["candidate_evidence"].pop()
    elif mutation == "alias":
        anchor = payload["registrations"][0]["anchor"]
        anchor["verifier_principal_id"] = anchor["signer_principal_id"]
    elif mutation == "nonfinite":
        payload["unexpected"] = float("nan")
    else:
        payload["unexpected"] = True
    with pytest.raises(ValueError):
        decode_annual_configuration(json.dumps(payload))
    monkeypatch.setattr(bootstrap, "_installed", None)
    monkeypatch.setattr(ports, "_installed_verifier", None)
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv(CONFIG_ENV, str(path))
    with pytest.raises(ValueError):
        bootstrap.bootstrap_composite_controlled_annual()
    assert isinstance(ports.controlled_year_verifier(), ports.UnavailableControlledYearVerification)


def test_duplicate_json_keys_and_oversize_refuse():
    with pytest.raises(ValueError):
        decode_annual_configuration('{"version":"a","version":"b"}')
    with pytest.raises(ValueError, match="bounded size"):
        decode_annual_configuration(" " * (4 * 1024 * 1024 + 1))


def test_default_off_and_once_installed_cannot_replace_remove_or_mutate(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap, "_installed", None)
    monkeypatch.setattr(ports, "_installed_verifier", None)
    monkeypatch.delenv(CONFIG_ENV, raising=False)
    assert bootstrap.bootstrap_composite_controlled_annual() is None
    assert isinstance(ports.controlled_year_verifier(), ports.UnavailableControlledYearVerification)
    monkeypatch.setenv(CONFIG_ENV, "relative.json")
    with pytest.raises(ValueError, match="absolute"):
        bootstrap.bootstrap_composite_controlled_annual()
    path = tmp_path / "annual.json"
    path.write_text(json.dumps(annual_package()), encoding="utf-8")
    monkeypatch.setenv(CONFIG_ENV, str(path))
    installed = bootstrap.bootstrap_composite_controlled_annual()
    assert bootstrap.bootstrap_composite_controlled_annual() == installed
    with pytest.raises(RuntimeError, match="already installed"):
        ports.install_controlled_year_verifier(verifier())
    path.write_text(json.dumps(annual_package()) + " ", encoding="utf-8")
    with pytest.raises(RuntimeError, match="cannot change"):
        bootstrap.bootstrap_composite_controlled_annual()
    monkeypatch.delenv(CONFIG_ENV)
    with pytest.raises(RuntimeError, match="cannot be removed"):
        bootstrap.bootstrap_composite_controlled_annual()


def test_installation_logs_once_with_only_nonsensitive_metadata(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(bootstrap, "_installed", None)
    monkeypatch.setattr(ports, "_installed_verifier", None)
    caplog.set_level(logging.INFO, logger=bootstrap.__name__)
    monkeypatch.delenv(CONFIG_ENV, raising=False)
    assert bootstrap.bootstrap_composite_controlled_annual() is None
    assert not caplog.records
    payload = annual_package()
    path = tmp_path / "do-not-log-operator-path.json"
    path.write_text('{"private_key":"must-not-be-logged"}', encoding="utf-8")
    monkeypatch.setenv(CONFIG_ENV, str(path))
    with pytest.raises(ValueError) as refused:
        bootstrap.bootstrap_composite_controlled_annual()
    assert str(refused.value) == "Controlled annual deployment configuration is invalid or unavailable."
    assert "must-not-be-logged" not in str(refused.value)
    assert not caplog.records
    path.write_text(json.dumps(payload), encoding="utf-8")
    installation = bootstrap.bootstrap_composite_controlled_annual()
    bootstrap.bootstrap_composite_controlled_annual()
    records = [record for record in caplog.records if record.name == bootstrap.__name__]
    assert len(records) == 1
    record = records[0]
    assert record.getMessage() == "Composite controlled annual verification installed"
    assert record.extra_fields == {**vars(installation), "qualification": "SYNTHETIC_NON_CERTIFYING"}
    emitted = JsonFormatter().format(record)
    proof = payload["registrations"][0]["proof"]
    for forbidden in (
        str(path),
        proof["verifier_public_key_base64"],
        proof["verifier_credential"],
        proof["basis_mapping"]["raw_original_base64"],
        proof["request"]["tenant_id"],
        proof["signer_principal_id"],
        proof["source_evidence_digest"],
    ):
        assert forbidden not in emitted
    assert json.loads(emitted)["configuration_digest"] == installation.configuration_digest


def _annual_overlay():
    return yaml.safe_load(Path("docker-compose.composite-controlled-annual.yml").read_text(encoding="utf-8"))[
        "services"
    ]


def _assert_annual_delivery(services):
    assert set(services) == {"performance-analytics", "performance-compute-executor"}
    for service in services.values():
        assert set(service) == {"environment", "volumes"}
        assert service["environment"] == {CONFIG_ENV: "/run/lotus/composite-controlled-annual.json"}
        assert service["volumes"] == [
            {
                "type": "bind",
                "source": "${LOTUS_COMPOSITE_CONTROLLED_ANNUAL_DEPLOYMENT_FILE:?An absolute admitted public operator package file is required}",
                "target": "/run/lotus/composite-controlled-annual.json",
                "read_only": True,
                "bind": {"create_host_path": False},
            }
        ]


def test_tracked_annual_overlay_is_explicit_readonly_and_scoped_to_api_compute():
    _assert_annual_delivery(_annual_overlay())
    base = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))["services"]
    for service in base.values():
        assert CONFIG_ENV not in service.get("environment", {})
        assert not any(
            isinstance(volume, dict) and volume.get("target") == "/run/lotus/composite-controlled-annual.json"
            for volume in service.get("volumes", [])
        )


@pytest.mark.parametrize(
    "mutation",
    ["missing", "lineage", "dependency", "credential", "host-path", "optional", "writable", "create", "target"],
)
def test_annual_overlay_boundary_guard_refuses_delivery_regressions(mutation):
    services = deepcopy(_annual_overlay())
    service = services["performance-analytics"]
    if mutation == "missing":
        services.pop("performance-compute-executor")
    elif mutation == "lineage":
        services["performance-lineage-worker"] = deepcopy(service)
    elif mutation == "dependency":
        service["depends_on"] = {}
    elif mutation == "credential":
        service["environment"]["PRIVATE_KEY"] = "${PRIVATE_KEY}"
    elif mutation == "host-path":
        service["environment"][CONFIG_ENV] = "${HOST_FILE}"
    elif mutation == "optional":
        service["volumes"][0]["source"] = "${LOTUS_COMPOSITE_CONTROLLED_ANNUAL_DEPLOYMENT_FILE:-}"
    elif mutation == "writable":
        service["volumes"][0]["read_only"] = False
    elif mutation == "create":
        service["volumes"][0]["bind"]["create_host_path"] = True
    else:
        service["volumes"][0]["target"] = "/app/foreign.json"
    with pytest.raises(AssertionError):
        _assert_annual_delivery(services)
