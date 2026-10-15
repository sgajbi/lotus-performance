"""Config-driven BF on existing registered custody; not live producer qualification."""

import json
import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from app.adapters.composite_attribution_bootstrap import bootstrap_composite_attribution
from app.adapters.composite_attribution_configuration import CONFIG_ENV
from app.core.config import get_settings
from app.ports import composite_external_evidence as original_ports
from app.services.composite_materialization import authority_policy
from app.services.compute_job_store import get_compute_job_store
from app.workers.compute_executor_worker import process_pending_jobs
from main import app
from tests.composite_attribution_deployment_helpers import DeploymentControl, original_registrations, reset_installation
from tests.integration.test_composite_attribution_api import attribution_database_url, attribution_runtime

__all__ = ["attribution_database_url", "attribution_runtime"]

ORIGINAL_FACTORIES = {
    name: getattr(original_ports, name)
    for name in (
        "authority_approval_verifier",
        "eligibility_approval_verifier",
        "method_approval_verifier",
    )
}
ORIGINAL_PROVIDER_FACTORY = authority_policy.provider_trust_resolver


def configured_runtime(runtime, tmp_path, monkeypatch):
    _, request, source, _, _, fixture, *_ = runtime
    bundle = source.read_pinned(request, tenant_id="tenant-a")
    control = DeploymentControl(tmp_path, request=request, bundle=bundle)
    control.payload["source_authorities"] = original_registrations(control, fixture, monkeypatch)
    assert control.payload["source_authorities"]
    for name, factory in ORIGINAL_FACTORIES.items():
        monkeypatch.setattr(original_ports, name, factory)
    monkeypatch.setattr(authority_policy, "provider_trust_resolver", ORIGINAL_PROVIDER_FACTORY)
    reset_installation(monkeypatch)
    monkeypatch.setenv(CONFIG_ENV, control.write())
    monkeypatch.setattr(app.state, "composite_attribution_installation", None, raising=False)
    return control, {"Authorization": "Bearer " + control.mint(), "X-Tenant-Id": "tenant-a"}


def test_registered_configuration_bootstrap_executes_all_or17_cells_and_retained_replay(
    attribution_runtime, tmp_path, monkeypatch
):
    control, headers = configured_runtime(attribution_runtime, tmp_path, monkeypatch)
    with TestClient(app) as client:
        installed = app.state.composite_attribution_installation
        assert installed["profile"] == "CONTROLLED_SYNTHETIC_ONLY"
        # Explicit shared bootstrap is the deferred worker startup composition;
        # this test calls the existing executor, not a substitute worker.
        assert bootstrap_composite_attribution().configuration_digest == installed["configuration_digest"]
        submitted = client.post(
            "/performance/composites/analytics", json=control.request.model_dump(mode="json"), headers=headers
        )
        assert submitted.status_code == 202, submitted.text
        path = submitted.json()["result_path"]
        assert process_pending_jobs(limit=1, settings=get_settings()) == 1
        result = client.get(path, headers=headers)
        assert result.status_code == 200, result.text
        payload = result.json()
        outcome = payload["outcome"]
        assert [outcome[name] for name in ("portfolio_return", "benchmark_return", "active_return")] == pytest.approx(
            [0.068, 0.055, 0.013], abs=1e-12
        )
        for row, expected in zip(
            outcome["groups"], ((0.0025, 0.010, 0.002, 0.0145), (0.0025, -0.005, 0.001, -0.0015)), strict=True
        ):
            assert [row[name] for name in ("allocation", "selection", "interaction", "total")] == pytest.approx(
                expected, abs=1e-12
            )
        assert payload["official_scope_id"] is None and payload["official_revision"] is None
        control.bundle_path.unlink()
        assert client.get(path, headers=headers).json() == payload
        control.payload["sources"][0]["approval"]["credential"] = "withdrawn"
        control.write()
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                "import json,sys; from fastapi.testclient import TestClient; from main import app; "
                "client=TestClient(app); client.__enter__(); "
                "response=client.get(sys.argv[1],headers=json.loads(sys.argv[2])); "
                "print(json.dumps({'status':response.status_code,'payload':response.json()})); client.__exit__(None,None,None)",
                path,
                json.dumps(headers),
            ],
            env={**os.environ, "LINEAGE_METADATA_DATABASE_URL": get_settings().LINEAGE_METADATA_DATABASE_URL},
            capture_output=True,
            text=True,
            check=False,
        )
        assert probe.returncode == 0, probe.stderr
        assert json.loads(probe.stdout) == {"status": 200, "payload": payload}


def test_registered_configuration_refuses_scope_before_job_registration(attribution_runtime, tmp_path, monkeypatch):
    control, headers = configured_runtime(attribution_runtime, tmp_path, monkeypatch)
    request = control.request.model_copy(update={"source_manifest_id": "not-registered"})
    with TestClient(app) as client:
        response = client.post(
            "/performance/composites/analytics", json=request.model_dump(mode="json"), headers=headers
        )
        assert response.status_code == 503
        assert response.json()["error_code"] == "SOURCE_AUTHORITY_UNAVAILABLE"
        assert get_compute_job_store().get_job(request.calculation_id) is None
