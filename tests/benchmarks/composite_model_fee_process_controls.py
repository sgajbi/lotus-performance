"""Fresh reader of an owning test's frozen configuration, never production trust."""

import json
import os
import subprocess
import sys
from pathlib import Path


def assert_fresh_model_fee_replay(captured, tmp_path):
    """Execute retained financial replay in a separate interpreter, preserving logs."""
    case = tmp_path / "original-profile.json"
    case.write_text(json.dumps(captured), encoding="utf-8")
    root = Path(__file__).resolve().parents[2]
    environment = {**os.environ, "LINEAGE_METADATA_DATABASE_URL": captured["database_url"]}
    result = subprocess.run(
        [sys.executable, "-m", "tests.benchmarks.composite_model_fee_process_controls", str(case)],
        cwd=root,
        env=environment,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=60,
    )
    (tmp_path / "fresh-reader.stdout").write_text(result.stdout, encoding="utf-8")
    (tmp_path / "fresh-reader.stderr").write_text(result.stderr, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    proof = json.loads(result.stdout.strip().splitlines()[-1])
    assert proof["retained_equal"] and proof["periods_equal"]
    assert proof["latest_resolution"] == "NOT_USED"
    assert proof["child_execution_lookup"] == "REFUSED_IF_ATTEMPTED"


def main():
    from fastapi.testclient import TestClient
    from pytest import MonkeyPatch

    from app.core.config import get_settings
    from app.ports import composite_external_evidence, composite_model_fees
    from app.services.composite_materialization.source_contract import PinnedCompositeSource
    from app.services.execution_registry import execution_registry
    from main import app
    from tests.composite_authority_helpers import install_test_authorities
    from tests.composite_model_fee_helpers import SyntheticModelFeeApproval

    case = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    get_settings().LINEAGE_METADATA_DATABASE_URL = case["database_url"]
    packet, wire, command = case["packet"], case["wire"], case["command"]
    tenant = packet["definition"]["tenant_id"]
    source_wire = {key: packet[key] for key in ("definition", "membership", "attestation")}
    source = PinnedCompositeSource.model_validate({**source_wire, "wire_evidence": source_wire})
    patch = MonkeyPatch()
    try:
        install_test_authorities(patch, packet)
        frozen = SyntheticModelFeeApproval(wire, source)
        patch.setattr(composite_external_evidence, "method_approval_verifier", lambda: frozen)

        class NoResolver:
            def resolve(self, request):
                raise AssertionError("Retained reload must not resolve latest method content")

        patch.setattr(composite_model_fees, "composite_model_fee_resolver", NoResolver)

        def no_child_lookup(*args, **kwargs):
            raise AssertionError("Retained financial custody must survive unavailable child executions")

        patch.setattr(execution_registry, "get_execution_for_tenant", no_child_lookup)
        headers = {"X-Tenant-Id": tenant, "X-Actor-Id": "operator", "X-Role": "DPM_COMPOSITE_CONSUMER"}
        with TestClient(app, headers=headers) as client:
            retained = client.get(f"/performance/composites/materializations/{command['materialization_id']}")
            assert retained.status_code == 200, retained.text
            assert retained.json() == case["retained"]
            request = {
                key: command[key]
                for key in (
                    "composite_id",
                    "period_start",
                    "period_end",
                    "return_view",
                    "reporting_currency",
                    "restatement_sequence",
                )
            }
            response = client.post("/performance/composites/twr", json=request)
            assert response.status_code == 200, response.text
            assert response.json()["periods"] == case["periods"]
        print(
            json.dumps(
                {
                    "qualification": "SYNTHETIC_TEST_ONLY",
                    "state": "COMPLETE",
                    "retained_equal": True,
                    "periods_equal": True,
                    "latest_resolution": "NOT_USED",
                    "child_execution_lookup": "REFUSED_IF_ATTEMPTED",
                }
            )
        )
    finally:
        patch.undo()


if __name__ == "__main__":
    main()
