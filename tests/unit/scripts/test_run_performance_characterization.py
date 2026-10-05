"""Deterministic proof of measurement evidence, refusal and native exit integrity."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest

from common.enums import PeriodType
from engine.config import EngineConfig
from scripts import run_performance_characterization as runner
from tests.benchmarks import test_engine_performance as engine_test


def _encoded(samples: list[float] | None = None) -> str:
    return runner.encode_engine_timing_evidence(
        [0.4, 0.3, 0.5, 0.2, 0.45] if samples is None else samples,
        row_count=75_000,
        budget_seconds=0.50,
        workload={"input_payload_sha256": "a" * 64, "engine_config": {"precision_mode": "FLOAT64"}},
    )


def _junit(path: Path, values: list[str], *, failed: bool = False, skipped: bool = False) -> None:
    root = ElementTree.Element("testsuites")
    suite = ElementTree.SubElement(
        root, "testsuite", tests="1", failures=str(int(failed)), errors="0", skipped=str(int(skipped))
    )
    case = ElementTree.SubElement(
        suite, "testcase", classname=runner.ENGINE_CONTRACT_CLASS, name=runner.ENGINE_CONTRACT_NAME
    )
    properties = ElementTree.SubElement(case, "properties")
    for value in values:
        ElementTree.SubElement(properties, "property", name=runner.ENGINE_EVIDENCE_PROPERTY, value=value)
    if failed:
        ElementTree.SubElement(case, "failure", message="unchanged budget failure")
    if skipped:
        ElementTree.SubElement(case, "skipped")
    ElementTree.ElementTree(root).write(path, encoding="unicode")


def test_samples_roundtrip_in_order_with_exact_recomputed_median(tmp_path: Path) -> None:
    path = tmp_path / "proof.xml"
    _junit(path, [_encoded()])
    evidence = runner._engine_evidence_from_junit(path, "full")
    assert evidence["status"] == "recorded"
    assert evidence["value"]["samples_seconds"] == [0.4, 0.3, 0.5, 0.2, 0.45]
    assert evidence["value"]["median_seconds"] == 0.4
    assert evidence["value"]["within_budget"] is True
    assert json.loads(runner.evidence_json(evidence)) == evidence


@pytest.mark.parametrize(
    "samples", [[], [0.1] * 4, [0.1] * 6, [float("nan")] * 5, [float("inf")] * 5, [-0.1] * 5, [True] * 5, ["0.1"] * 5]
)
def test_invalid_sample_shapes_cannot_serialize_as_completed_evidence(samples: list[float]) -> None:
    with pytest.raises((ValueError, TypeError)):
        _encoded(samples)


@pytest.mark.parametrize(
    "field,value",
    [
        ("median_seconds", 0.2),
        ("within_budget", False),
        ("row_count", 74000),
        ("budget_seconds", 0.6),
        ("warmup_runs", 0),
        ("measured_runs", 4),
        ("units", "milliseconds"),
        ("schema_version", True),
        ("timed_boundary", "run_calculations without copy"),
        ("workload", {}),
    ],
)
def test_evidence_contract_mismatch_is_refused(tmp_path: Path, field: str, value: object) -> None:
    evidence = json.loads(_encoded())
    evidence[field] = value
    path = tmp_path / "proof.xml"
    _junit(path, [json.dumps(evidence)])
    assert runner._engine_evidence_from_junit(path, "full")["status"] == "invalid"


@pytest.mark.parametrize(
    "values", [[], ["not JSON"], [_encoded(), _encoded()], ['{"schema_version":1,"schema_version":1}']]
)
def test_missing_duplicate_malformed_property_is_refused(tmp_path: Path, values: list[str]) -> None:
    path = tmp_path / "proof.xml"
    _junit(path, values)
    assert runner._engine_evidence_from_junit(path, "full")["status"] == "invalid"


def test_over_budget_samples_are_retained_only_with_failed_case(tmp_path: Path) -> None:
    path = tmp_path / "proof.xml"
    encoded = _encoded([0.6, 0.7, 0.8, 0.55, 0.65])
    _junit(path, [encoded], failed=True)
    evidence = runner._engine_evidence_from_junit(path, "full")
    assert evidence["status"] == "recorded" and evidence["value"]["median_seconds"] == 0.65
    assert evidence["value"]["within_budget"] is False
    _junit(path, [encoded])
    assert runner._engine_evidence_from_junit(path, "full")["status"] == "invalid"


def test_skipped_and_duplicate_engine_case_do_not_claim_completed_measurement(tmp_path: Path) -> None:
    path = tmp_path / "proof.xml"
    _junit(path, [_encoded()], skipped=True)
    assert runner._engine_evidence_from_junit(path, "full")["status"] == "invalid"
    _junit(path, [_encoded()])
    tree = ElementTree.parse(path)
    suite = tree.getroot()[0]
    suite.append(ElementTree.fromstring(ElementTree.tostring(suite[0])))
    tree.write(path, encoding="unicode")
    assert runner._engine_evidence_from_junit(path, "full")["status"] == "invalid"


def test_postgres_only_and_archived_missing_measurement_are_not_fabricated(tmp_path: Path) -> None:
    path = tmp_path / "absent.xml"
    evidence = runner._engine_evidence_from_junit(path, "postgres")
    assert evidence["status"] == "not_applicable" and evidence["value"] is None
    assert runner._engine_evidence_from_junit(path, "full")["status"] == "invalid"
    # An archived summary is not rewritten or assigned zero timings by the reader.
    assert "engine_timing_evidence" not in {"schema_version": 1, "return_code": 0}


@pytest.mark.parametrize("native_exit,properties,expected", [(0, True, 0), (0, False, 4), (2, True, 2), (2, False, 2)])
def test_runner_preserves_native_exit_separately_from_artifact_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, native_exit: int, properties: bool, expected: int
) -> None:
    args = argparse.Namespace(mode="full", output_dir=str(tmp_path), require_non_skipped=False)
    monkeypatch.setattr(runner, "_parse_args", lambda: args)
    monkeypatch.setattr(runner, "capture_runtime_context", lambda: {"scope": "synthetic test context"})

    def producing_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        _junit(tmp_path / "performance-characterization.junit.xml", [_encoded()] if properties else [])
        return subprocess.CompletedProcess(command, native_exit, "synthetic producing stdout", "synthetic stderr")

    monkeypatch.setattr(runner.subprocess, "run", producing_run)
    assert runner.main() == expected
    summary = json.loads((tmp_path / "performance-characterization.summary.json").read_text())
    assert summary["return_code"] == native_exit
    assert summary["artifact_validation_exit"] == (0 if properties else 4)
    assert summary["schema_version"] == 1 and summary["tests"] == 1
    assert (tmp_path / "performance-characterization.log").read_text() == "synthetic producing stdoutsynthetic stderr"


def test_malformed_junit_does_not_mask_original_subprocess_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args = argparse.Namespace(mode="full", output_dir=str(tmp_path), require_non_skipped=False)
    monkeypatch.setattr(runner, "_parse_args", lambda: args)
    monkeypatch.setattr(runner, "capture_runtime_context", lambda: {})
    (tmp_path / "performance-characterization.junit.xml").write_text("broken XML")
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 2, "", ""))
    assert runner.main() == 2
    summary = json.loads((tmp_path / "performance-characterization.summary.json").read_text())
    assert summary["artifact_validation_exit"] == 4 and summary["return_code"] == 2


@pytest.mark.parametrize("duration", [0.4, 0.6])
def test_actual_contract_records_after_six_stub_calls_before_original_assertion(
    monkeypatch: pytest.MonkeyPatch, duration: float
) -> None:
    events: list[str] = []

    class Frame:
        def __len__(self) -> int:
            return 75000

        def copy(self, *, deep: bool) -> Frame:
            assert deep
            events.append("copy")
            return self

    class Properties(list):
        def append(self, value: object) -> None:
            assert events.count("engine") == 6 and events[-1] == "clock"
            events.append("record")
            super().append(value)

    config = EngineConfig(date(2023, 12, 31), date(2229, 5, 5), "NET", PeriodType.YTD)
    payload = {
        "portfolio_id": "BENCHMARK_PORT_01",
        "valuation_points": [{"perf_date": "2024-01-01"}],
        "report_end_date": "2229-05-05",
    }
    model = SimpleNamespace(valuation_points=[SimpleNamespace(model_dump=lambda: {})])
    monkeypatch.setattr(engine_test.PerformanceRequest, "model_validate", lambda _: model)
    monkeypatch.setattr(engine_test, "create_engine_config", lambda *a: config)
    monkeypatch.setattr(engine_test, "create_engine_dataframe", lambda _: Frame())
    monkeypatch.setattr(engine_test, "run_calculations", lambda frame, cfg: events.append("engine"))
    clocks = iter(value for i in range(5) for value in (i * 2.0, i * 2.0 + duration))

    def clock() -> float:
        events.append("clock")
        return next(clocks)

    monkeypatch.setattr(engine_test, "perf_counter", clock)
    request = SimpleNamespace(node=SimpleNamespace(user_properties=Properties()))
    if duration > 0.5:
        with pytest.raises(AssertionError, match="exceeded budget 0.500s for 75000 daily rows"):
            engine_test.test_vectorized_engine_characterization_contract(payload, request)
    else:
        engine_test.test_vectorized_engine_characterization_contract(payload, request)
    assert events == ["copy", "engine"] + ["clock", "copy", "engine", "clock"] * 5 + ["record"]
    name, encoded = request.node.user_properties[0]
    evidence = json.loads(encoded)
    assert name == runner.ENGINE_EVIDENCE_PROPERTY and len(evidence["samples_seconds"]) == 5
    assert evidence["median_seconds"] == pytest.approx(duration)
    assert evidence["workload"]["engine_config_sha256"] == runner.evidence_sha256(asdict(config))


def test_direct_node_property_roundtrips_xunit2_without_warnings(tmp_path: Path) -> None:
    target = tmp_path / "test_property.py"
    target.write_text(
        "def test_property(request):\n    request.node.user_properties.append(('measurement', '[0.1,0.2]'))\n"
    )
    report = tmp_path / "report.xml"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(target),
            "-q",
            "-W",
            "error",
            "-o",
            "junit_family=xunit2",
            f"--junitxml={report}",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    property_node = ElementTree.parse(report).find(".//property")
    assert property_node is not None and property_node.get("value") == "[0.1,0.2]"
    assert "warnings summary" not in result.stdout.lower()


def test_context_records_unavailable_and_declared_provenance_without_environment_dump(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRIVATE_TOKEN", "must-not-appear")
    monkeypatch.setenv("OMP_NUM_THREADS", "2")
    monkeypatch.delenv("APP_IMAGE_DIGEST", raising=False)
    monkeypatch.setattr(runner, "_source_commit", lambda: None)
    monkeypatch.setattr(runner, "_physical_memory", lambda: {"total_bytes": 1024, "available_bytes": 512})
    monkeypatch.setattr(runner.os, "cpu_count", lambda: 0)
    monkeypatch.setattr(runner.metadata, "version", lambda package: "synthetic-installed-version")
    context = runner.capture_runtime_context()
    encoded = runner.evidence_json(context)
    assert "PRIVATE_TOKEN" not in encoded and "must-not-appear" not in encoded
    assert context["declared_context"]["OMP_NUM_THREADS"]["value"] == "2"
    assert context["declared_context"]["APP_IMAGE_DIGEST"]["value"] is None
    assert context["declared_context"]["APP_IMAGE_DIGEST"]["unavailable_reason"]
    assert context["logical_cpu_count"]["value"] == 0  # Not an unavailable sentinel.
    assert context["source_commit"]["value"] is None and context["source_commit"]["unavailable_reason"]
    assert context["physical_memory"]["value"]["available_bytes"] == 512
    assert context["unmeasured"]["deployment_resource_entitlement"]["value"] is None


def test_failed_probe_is_explicitly_unavailable_and_nonfinite_json_is_refused() -> None:
    def unavailable() -> object:
        raise OSError("private diagnostic text")

    observed = runner._observation(unavailable, "synthetic observed limit")
    assert observed == {"value": None, "provenance": "synthetic observed limit", "unavailable_reason": "OSError"}
    with pytest.raises(ValueError):
        runner.evidence_json({"sample": float("nan")})


def test_linux_memory_and_affinity_observations_retain_units_and_unavailability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner.sys, "platform", "linux")
    monkeypatch.setattr(runner.Path, "read_text", lambda *a, **k: "MemTotal: 2048 kB\nMemAvailable: 1024 kB\n")
    assert runner._physical_memory() == {"total_bytes": 2097152, "available_bytes": 1048576}
    monkeypatch.setattr(runner.os, "sched_getaffinity", lambda pid: {3, 1}, raising=False)
    assert runner._cpu_affinity() == [1, 3]
    monkeypatch.setattr(runner.Path, "read_text", lambda *a, **k: "MemTotal: 2048 kB\n")
    missing = runner._observation(runner._physical_memory, "synthetic incomplete host memory")
    assert missing["value"] is None and missing["unavailable_reason"] == "KeyError"
    monkeypatch.setattr(runner.os, "sched_getaffinity", None)
    unavailable = runner._observation(runner._cpu_affinity, "synthetic unsupported affinity")
    assert unavailable["value"] is None and unavailable["unavailable_reason"] == "NotImplementedError"


@pytest.mark.parametrize(
    "shape,native_exit,runner_exit", [("valid", 0, 0), ("missing", 0, 4), ("over_budget", 1, 1), ("interrupted", 2, 2)]
)
def test_real_synthetic_subprocess_preserves_producing_exit_and_failed_measurement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    shape: str,
    native_exit: int,
    runner_exit: int,
) -> None:
    target = tmp_path / "test_synthetic.py"
    values = [0.6] * 5 if shape == "over_budget" else [0.4] * 5
    property_statement = (
        ""
        if shape == "missing"
        else (f"    request.node.user_properties.append(({runner.ENGINE_EVIDENCE_PROPERTY!r}, {_encoded(values)!r}))\n")
    )
    target.write_text(
        "def test_vectorized_engine_characterization_contract(request):\n"
        + property_statement
        + (
            "    assert False, 'synthetic unchanged budget refusal'\n"
            if shape == "over_budget"
            else "    assert True\n"
        )
    )
    if shape == "interrupted":
        (tmp_path / "conftest.py").write_text(
            "def pytest_sessionfinish(session, exitstatus):\n    session.exitstatus = 2\n"
        )
    args = argparse.Namespace(mode="full", output_dir=str(tmp_path), require_non_skipped=False)
    monkeypatch.setattr(runner, "_parse_args", lambda: args)
    monkeypatch.setattr(runner, "capture_runtime_context", lambda: {"scope": "synthetic subprocess; no engine calls"})
    monkeypatch.setattr(runner, "BENCHMARK_PATHS", {"full": (str(target), "--rootdir", str(tmp_path))})
    monkeypatch.setattr(runner, "ENGINE_CONTRACT_CLASS", "test_synthetic")
    actual_exit = runner.main()
    summary = json.loads((tmp_path / "performance-characterization.summary.json").read_text())
    assert actual_exit == runner_exit and summary["return_code"] == native_exit
    if shape == "over_budget":
        assert summary["failures"] == 1
        assert summary["engine_timing_evidence"]["value"]["samples_seconds"] == [0.6] * 5
    request.node.user_properties.append(
        (
            "synthetic_native_receipt",
            runner.evidence_json(
                {
                    "shape": shape,
                    "pytest_exit": summary["return_code"],
                    "runner_exit": actual_exit,
                    "artifact_validation_exit": summary["artifact_validation_exit"],
                    "tests": summary["tests"],
                    "failures": summary["failures"],
                    "engine_evidence_status": summary["engine_timing_evidence"]["status"],
                }
            ),
        )
    )
