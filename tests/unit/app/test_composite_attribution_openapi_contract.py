"""Executable BF examples, exact publication and failing certification controls."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from app.api.dependencies.composite_attribution import attribution_openapi_examples
from app.observability import correlation_id_var, request_id_var
from main import app
from tests.composite_attribution_example_contract import certify_attribution_examples
from tests.composite_attribution_example_factory import attribution_example_family

ROOT = Path(__file__).resolve().parents[3]


def ledger():
    return json.loads((ROOT / "docs/examples/composite_attribution_endpoint_family.json").read_text(encoding="utf-8"))


def test_bf_named_family_matches_executable_factory_openapi_and_behavior_ledger():
    correlation_token = correlation_id_var.set("preceding-unit-correlation")
    request_token = request_id_var.set("preceding-unit-request")
    try:
        certify_attribution_examples(
            app.openapi(), attribution_openapi_examples(), attribution_example_family(), ledger(), root=ROOT
        )
        assert correlation_id_var.get() == "preceding-unit-correlation"
        assert request_id_var.get() == "preceding-unit-request"
    finally:
        correlation_id_var.reset(correlation_token)
        request_id_var.reset(request_token)


@pytest.mark.parametrize(
    "defect", ["missing_mode", "missing_behavior", "absent_test", "changed_effect", "extra_mode", "approval_claim"]
)
def test_bf_named_family_guard_rejects_representative_bad_inputs(defect):
    evidence = ledger()
    spec = deepcopy(app.openapi())
    if defect == "missing_mode":
        evidence["modes"].pop()
    elif defect == "missing_behavior":
        evidence["modes"][0].pop("behavior")
    elif defect == "absent_test":
        evidence["modes"][0]["behavior"] = "tests/integration/test_composite_attribution_api.py::test_invented"
    elif defect == "changed_effect":
        spec["paths"]["/performance/composites/analytics/results/{calculation_id}"]["get"]["responses"]["200"][
            "content"
        ]["application/json"]["examples"]["bf_original_ready"]["value"]["outcome"]["groups"][0]["selection"] = 1.0
    elif defect == "extra_mode":
        spec["paths"]["/performance/composites/analytics"]["post"]["responses"]["202"]["content"]["application/json"][
            "examples"
        ]["bf_invented"] = {"value": {}}
    else:
        evidence["institutional_acceptance"] = "APPROVED"
    with pytest.raises(ValueError):
        certify_attribution_examples(
            spec, attribution_openapi_examples(), attribution_example_family(), evidence, root=ROOT
        )


@pytest.mark.parametrize(
    "mode,benchmark_return,active,rows",
    [
        ("original_ready", 0.055, 0.013, ((0.0025, 0.01, 0.002, 0.0145), (0.0025, -0.005, 0.001, -0.0015))),
        ("corrected_ready", 0.06, 0.008, ((0.003, 0.005, 0.001, 0.009), (0.003, -0.005, 0.001, -0.001))),
    ],
)
def test_bf_examples_preserve_every_effect_cell_and_source_qualification(mode, benchmark_return, active, rows):
    family = attribution_example_family()
    response = family[mode]
    result = response["outcome"]
    assert result["portfolio_return"] == pytest.approx(0.068, abs=1e-12)
    assert result["benchmark_return"] == pytest.approx(benchmark_return, abs=1e-12)
    assert result["active_return"] == pytest.approx(active, abs=1e-12)
    for actual, expected in zip(result["groups"], rows, strict=True):
        assert [actual[key] for key in ("allocation", "selection", "interaction", "total")] == pytest.approx(
            expected, abs=1e-12
        )
    assert response["official_scope_id"] is None and response["official_revision"] is None
    assert response["observation"]["source_bundle"]["qualification"] == "CONTROLLED_SYNTHETIC_ONLY"
    assert response["observation"]["approval"]["qualification"] == "SYNTHETIC_NON_CERTIFYING"
    assert result["units"] == "DECIMAL_RETURN" and result["precision_mode"] == "FLOAT64"
    assert family["original_ready"] == family["original_replay"]
    assert family["corrected_ready"]["correction_of_calculation_id"] == family["request"]["calculation_id"]
    assert family["corrected_ready"]["input_manifest_digest"] != family["original_ready"]["input_manifest_digest"]
