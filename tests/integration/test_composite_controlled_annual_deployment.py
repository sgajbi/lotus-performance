"""Real annual installer and API/worker entrypoints; source evidence only."""

import json
import os
import subprocess
import sys
from datetime import date
from types import SimpleNamespace

import pytest

from app.adapters import composite_controlled_annual_bootstrap as bootstrap
from app.adapters.composite_controlled_annual_configuration import CONFIG_ENV
from app.adapters.composite_membership_source import ManageCompositeMembershipSource
from app.ports import composite_controlled_annual_evidence as ports
from app.services.composite_materialization.controlled_annual_authority import (
    admit_annual_authority,
    require_annual_internal_bindings,
)
from core.errors import APIError
from tests.composite_controlled_annual_deployment_helpers import annual_package
from tests.composite_controlled_annual_helpers import command, graph, install_independent_test_trust, source_packet
from tests.composite_controlled_scenario_helpers import install_http_transport


@pytest.mark.asyncio
async def test_real_installed_annual_adapter_admits_normal_manage_source_without_financial_inflation(
    tmp_path, monkeypatch
):
    # Other policy/method/provider seams remain independently supplied; annual lookup stays real.
    install_independent_test_trust(monkeypatch, install_year=False)
    monkeypatch.setattr(ports, "_installed_verifier", None)
    monkeypatch.setattr(bootstrap, "_installed", None)
    path = tmp_path / "annual.json"
    path.write_text(json.dumps(annual_package()), encoding="utf-8")
    monkeypatch.setenv(CONFIG_ENV, str(path))
    bootstrap.bootstrap_composite_controlled_annual()
    calls = install_http_transport(monkeypatch, packet=source_packet(), receipt=graph())
    source = await ManageCompositeMembershipSource().read_pinned(
        command(), tenant_id="synthetic-tenant", actor_id="reader", role="DPM_COMPOSITE_CONSUMER"
    )
    assert source.wire_evidence.model_dump() == source_packet()
    assert len(calls) == 4
    definition = source.definition
    member = definition.source_authority.payload.member_identities[0]
    with pytest.raises(APIError) as error:
        require_annual_internal_bindings(
            definition, command(), SimpleNamespace(portfolio_id=member.member_id), None, ["ENDING_ASSETS"]
        )
    assert error.value.error_code == "COMPOSITE_YEAR_RULE_COVERAGE_MISMATCH"
    for month, last in ((2, 28), (12, 31)):
        cmd = command().model_copy(update={"period_start": date(2025, month, 1), "period_end": date(2025, month, last)})
        members = definition.authority_approval.verification.candidate_evidence[month - 1].members
        with pytest.raises(APIError) as error:
            admit_annual_authority(definition, cmd, [item.member_id for item in members], source.published_eligibility)
        assert error.value.error_code == "COMPOSITE_ELIGIBILITY_RESOLUTION_WINDOW_MISMATCH"


@pytest.mark.parametrize("role", ["api", "worker", "retained"])
@pytest.mark.parametrize("enabled", [False, True, "malformed"])
def test_fresh_process_real_entrypoint_default_and_install(tmp_path, role, enabled):
    path = tmp_path / "annual.json"
    payload = annual_package()
    path.write_text(json.dumps(payload), encoding="utf-8")
    if enabled == "malformed":
        path.write_text('{"version":"one","version":"two","private_key":"must-not-be-logged"}', encoding="utf-8")
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {CONFIG_ENV, "LOTUS_COMPOSITE_ATTRIBUTION_DEPLOYMENT"}
    }
    env["LINEAGE_METADATA_DATABASE_URL"] = "sqlite:///" + (tmp_path / "startup.db").as_posix()
    if enabled:
        env[CONFIG_ENV] = str(path)
    setup = "from app.services.durable_metadata_bootstrap import bootstrap_durable_metadata_stores; bootstrap_durable_metadata_stores(); "
    startup = {
        "api": "from fastapi.testclient import TestClient; from main import app; client=TestClient(app); client.__enter__(); ",
        "worker": "from threading import Event; from app.workers.compute_executor_worker import run_forever; stop=Event(); stop.set(); run_forever(stop_event=stop); ",
        "retained": "from app.adapters.composite_controlled_annual_bootstrap import bootstrap_composite_controlled_annual; bootstrap_composite_controlled_annual(); ",
    }[role]
    probe = (
        setup
        + startup
        + (
            "import json,sys; from app.ports.composite_controlled_annual_evidence import controlled_year_verifier; "
            "from app.models.composite_controlled_annual_authority import ControlledYearBasisVerificationRequest; "
            "request=ControlledYearBasisVerificationRequest.model_validate(json.loads(sys.argv[1])); "
            "result=controlled_year_verifier().verify(request); "
            "print('ANNUAL_PROBE='+json.dumps(None if result is None else result.proof.content_hash)); "
        )
    )
    if role == "api":
        probe += "client.__exit__(None,None,None)"
    result = subprocess.run(
        [sys.executable, "-c", probe, json.dumps(payload["registrations"][0]["proof"]["request"])],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if enabled == "malformed":
        assert result.returncode != 0
        assert "ANNUAL_PROBE=" not in result.stdout
        assert "Controlled annual deployment configuration is invalid or unavailable." in result.stderr
        assert "must-not-be-logged" not in result.stderr
        return
    assert result.returncode == 0, result.stderr
    if role in {"api", "worker"}:
        records = [json.loads(line) for line in result.stderr.splitlines() if line.startswith("{")]
        installed = [
            row for row in records if row.get("message") == "Composite controlled annual verification installed"
        ]
        assert len(installed) == int(enabled is True)
        if enabled is True:
            assert installed[0]["profile"] == "CONTROLLED_SYNTHETIC_ONLY"
            assert installed[0]["qualification"] == "SYNTHETIC_NON_CERTIFYING"
        proof = payload["registrations"][0]["proof"]
        for forbidden in (proof["verifier_credential"], proof["verifier_public_key_base64"], str(path)):
            assert forbidden not in result.stderr
    output = next(
        line.removeprefix("ANNUAL_PROBE=") for line in result.stdout.splitlines() if line.startswith("ANNUAL_PROBE=")
    )
    assert json.loads(output) == (payload["registrations"][0]["proof_digest"] if enabled else None)
