from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import time
from datetime import UTC, date, datetime
from enum import Enum
from functools import partial
from importlib import metadata
from pathlib import Path
from statistics import median
from typing import Any, Callable
from xml.etree import ElementTree

BENCHMARK_PATHS = {
    "full": ("tests/benchmarks",),
    "postgres": (
        "tests/benchmarks/test_postgres_query_plans.py",
        "tests/benchmarks/test_postgres_concurrency_contracts.py",
    ),
}

DEFAULT_POSTGRES_URL = "postgresql+psycopg://lotus:lotus@127.0.0.1:5435/lotus_performance"
ENGINE_EVIDENCE_PROPERTY = "lotus_engine_timing_evidence"
ENGINE_CONTRACT_CLASS = "tests.benchmarks.test_engine_performance"
ENGINE_CONTRACT_NAME = "test_vectorized_engine_characterization_contract"
EVIDENCE_VALIDATION_EXIT = 4


def _json_default(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return str(value.value)
    raise TypeError(f"Unsupported evidence type: {type(value).__name__}")


def evidence_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=_json_default)


def evidence_sha256(value: Any) -> str:
    return hashlib.sha256(evidence_json(value).encode("utf-8")).hexdigest()


def _validate_samples(samples: Any) -> list[float]:
    if not isinstance(samples, list) or len(samples) != 5:
        raise ValueError("Engine evidence requires five ordered samples")
    if any(
        type(sample_seconds) not in (int, float) or not math.isfinite(sample_seconds) or sample_seconds < 0
        for sample_seconds in samples
    ):
        raise ValueError("Engine samples must be finite nonnegative numbers")
    return samples


def _validate_measurement_contract(evidence: dict[str, Any]) -> None:
    expected = {"row_count": 75_000, "budget_seconds": 0.50, "warmup_runs": 1, "measured_runs": 5, "units": "seconds"}
    if any(type(evidence.get(key)) is not type(value) or evidence[key] != value for key, value in expected.items()):
        raise ValueError("Governed engine measurement contract changed")


def _validate_statistics(evidence: dict[str, Any], samples: list[float]) -> None:
    actual_median = median(samples)
    if type(evidence.get("median_seconds")) not in (int, float) or evidence["median_seconds"] != actual_median:
        raise ValueError("Engine evidence median does not match samples")
    if type(evidence.get("within_budget")) is not bool or evidence["within_budget"] != (actual_median <= 0.50):
        raise ValueError("Engine evidence budget verdict does not match median")


def _validate_engine_evidence(evidence: Any) -> dict[str, Any]:
    if (
        not isinstance(evidence, dict)
        or type(evidence.get("schema_version")) is not int
        or evidence["schema_version"] != 1
    ):
        raise ValueError("Unsupported engine evidence schema")
    samples = _validate_samples(evidence.get("samples_seconds"))
    _validate_measurement_contract(evidence)
    _validate_statistics(evidence, samples)
    if evidence.get("timed_boundary") != "engine_df.copy(deep=True) + run_calculations":
        raise ValueError("Engine evidence timed boundary changed")
    if not isinstance(evidence.get("workload"), dict) or not evidence["workload"]:
        raise ValueError("Engine workload identity is missing")
    evidence_json(evidence)
    return evidence


def encode_engine_timing_evidence(
    samples: list[float], *, row_count: int, budget_seconds: float, workload: dict[str, Any]
) -> str:
    evidence = {
        "schema_version": 1,
        "samples_seconds": samples,
        "median_seconds": median(samples) if samples else None,
        "row_count": row_count,
        "budget_seconds": budget_seconds,
        "warmup_runs": 1,
        "measured_runs": 5,
        "units": "seconds",
        "timed_boundary": "engine_df.copy(deep=True) + run_calculations",
        "within_budget": median(samples) <= budget_seconds if samples else False,
        "workload": workload,
    }
    return evidence_json(_validate_engine_evidence(evidence))


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate engine evidence field")
        result[key] = value
    return result


def _owning_engine_case(root: ElementTree.Element) -> ElementTree.Element:
    cases = [
        case
        for case in root.iter("testcase")
        if case.get("classname") == ENGINE_CONTRACT_CLASS and case.get("name") == ENGINE_CONTRACT_NAME
    ]
    if len(cases) != 1 or cases[0].find("skipped") is not None:
        raise ValueError("Exactly one non-skipped engine contract is required")
    return cases[0]


def _measurement_property(case: ElementTree.Element) -> str:
    properties = [p for p in case.iter("property") if p.get("name") == ENGINE_EVIDENCE_PROPERTY]
    if len(properties) != 1:
        raise ValueError("Exactly one engine measurement property is required")
    return properties[0].get("value", "")


def _engine_evidence_from_junit(junit_path: Path, mode: str) -> dict[str, Any]:
    if mode == "postgres":
        return {
            "status": "not_applicable",
            "value": None,
            "reason": "PostgreSQL-only mode does not run the engine contract",
        }
    try:
        root = ElementTree.parse(junit_path).getroot()
        case = _owning_engine_case(root)
        evidence = _validate_engine_evidence(
            json.loads(_measurement_property(case), object_pairs_hook=_unique_json_object)
        )
        if not evidence["within_budget"] and case.find("failure") is None:
            raise ValueError("Over-budget engine evidence cannot describe a passed contract")
        return {"status": "recorded", "value": evidence, "reason": None}
    except (OSError, ElementTree.ParseError, ValueError, TypeError) as error:
        return {"status": "invalid", "value": None, "reason": str(error)}


def _observation(probe: Callable[[], Any], provenance: str) -> dict[str, Any]:
    try:
        value = probe()
        if value is None or value == "":
            return {"value": None, "provenance": provenance, "unavailable_reason": "Not recorded or not declared"}
        return {"value": value, "provenance": provenance, "unavailable_reason": None}
    except (OSError, ValueError, KeyError, AttributeError, NotImplementedError, metadata.PackageNotFoundError) as error:
        return {"value": None, "provenance": provenance, "unavailable_reason": type(error).__name__}


def _physical_memory() -> dict[str, int]:
    if sys.platform != "win32":
        fields = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines())
        return {
            "total_bytes": int(fields["MemTotal"].split()[0]) * 1024,
            "available_bytes": int(fields["MemAvailable"].split()[0]) * 1024,
        }

    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_ulong),
            ("load", ctypes.c_ulong),
            *[
                (name, ctypes.c_ulonglong)
                for name in (
                    "total",
                    "available",
                    "total_page",
                    "available_page",
                    "total_virtual",
                    "available_virtual",
                    "extended",
                )
            ],
        ]

    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise OSError("Memory observation unavailable")
    return {"total_bytes": status.total, "available_bytes": status.available}


def _source_commit() -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _cpu_affinity() -> list[int]:
    probe = getattr(os, "sched_getaffinity", None)
    if probe is None:
        raise NotImplementedError("Process affinity observation is unavailable")
    return sorted(probe(0))


def _mounted_cgroup_value(name: str) -> str:
    return Path("/sys/fs/cgroup", name).read_text(encoding="utf-8").strip()


def capture_runtime_context() -> dict[str, Any]:
    libraries = ("numpy", "pandas", "pydantic", "pytest", "pytest-benchmark", "pytest-randomly", "psycopg")
    declarations = (
        "GITHUB_SHA",
        "GITHUB_RUN_ID",
        "RUNNER_OS",
        "RUNNER_ARCH",
        "ImageOS",
        "ImageVersion",
        "APP_IMAGE_DIGEST",
        "APP_GIT_COMMIT_SHA",
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    )
    resources = {
        name: _observation(
            partial(_mounted_cgroup_value, name),
            f"mounted cgroup root /sys/fs/cgroup/{name}; not verified process entitlement",
        )
        for name in ("cpu.max", "memory.max", "cpuset.cpus.effective")
    }
    return {
        "schema_version": 1,
        "scope": "characterization runner process before pytest; not deployment qualification",
        "interpreter": {
            "executable": sys.executable,
            "version": sys.version,
            "implementation": platform.python_implementation(),
        },
        "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
        "installed_libraries": {
            name: _observation(partial(metadata.version, name), "installed distribution metadata") for name in libraries
        },
        "source_commit": _observation(_source_commit, "git checkout HEAD"),
        "logical_cpu_count": _observation(os.cpu_count, "os.cpu_count; host count, not quota"),
        "processor_identifier": _observation(platform.processor, "platform.processor; not a qualified CPU model"),
        "cpu_affinity": _observation(_cpu_affinity, "runner process affinity"),
        "physical_memory": _observation(_physical_memory, "host memory snapshot; not process memory entitlement"),
        "mounted_cgroup_resources": resources,
        "declared_context": {
            name: _observation(partial(os.environ.get, name), f"environment declaration {name}")
            for name in declarations
        },
        "unmeasured": {
            name: {"value": None, "unavailable_reason": "Not measured by this characterization"}
            for name in ("cpu_frequency_governor", "load_contention", "deployment_resource_entitlement")
        },
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run performance characterization with CI artifacts.")
    parser.add_argument("--mode", choices=sorted(BENCHMARK_PATHS), default="full")
    parser.add_argument("--output-dir", default="output/performance-characterization")
    parser.add_argument(
        "--require-non-skipped",
        action="store_true",
        help="Fail when the selected characterization suite only produced skipped tests.",
    )
    parser.add_argument(
        "--postgres-ready-timeout-seconds",
        type=int,
        default=45,
        help="Maximum readiness wait before PostgreSQL characterization fails closed.",
    )
    return parser.parse_args()


def _artifact_stem(mode: str) -> str:
    return "performance-characterization" if mode == "full" else "performance-characterization-postgres"


def _wait_for_postgres(database_url: str, timeout_seconds: int) -> bool:
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import OperationalError

    deadline = time.monotonic() + timeout_seconds
    while True:
        engine = create_engine(database_url, future=True, connect_args={"connect_timeout": 3})
        try:
            with engine.begin() as connection:
                connection.execute(text("SELECT 1"))
            return True
        except OperationalError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(2)
        finally:
            engine.dispose()


def _read_junit_counts(junit_path: Path) -> dict[str, int]:
    if not junit_path.exists():
        return {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}

    root = ElementTree.parse(junit_path).getroot()
    if root.tag == "testsuites":
        suites = list(root)
    else:
        suites = [root]

    counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for suite in suites:
        for key in counts:
            counts[key] += int(suite.attrib.get(key, "0"))
    return counts


def _write_summary(
    *,
    args: argparse.Namespace,
    command: list[str],
    junit_path: Path,
    log_path: Path,
    return_code: int,
    postgres_ready: bool | None,
    runtime_context: dict[str, Any],
) -> Path:
    junit_error = None
    try:
        counts = _read_junit_counts(junit_path)
        if counts["tests"] == 0:
            junit_error = "No characterization cases recorded"
    except (ElementTree.ParseError, ValueError) as error:
        counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
        junit_error = type(error).__name__
    engine_evidence = _engine_evidence_from_junit(junit_path, args.mode)
    summary: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": args.mode,
        "command": command,
        "junit_path": junit_path.as_posix(),
        "log_path": log_path.as_posix(),
        "return_code": return_code,
        "tests": counts["tests"],
        "failures": counts["failures"],
        "errors": counts["errors"],
        "skipped": counts["skipped"],
        "postgres_ready": postgres_ready,
        "require_non_skipped": bool(args.require_non_skipped),
        "runtime_context": runtime_context,
        "engine_timing_evidence": engine_evidence,
        "junit_validation_error": junit_error,
        "artifact_validation_exit": EVIDENCE_VALIDATION_EXIT
        if junit_error or engine_evidence["status"] == "invalid"
        else 0,
    }
    summary_path = Path(args.output_dir) / f"{_artifact_stem(args.mode)}.summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return summary_path


def main() -> int:
    args = _parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    stem = _artifact_stem(args.mode)
    junit_path = output_dir / f"{stem}.junit.xml"
    log_path = output_dir / f"{stem}.log"
    postgres_ready: bool | None = None
    runtime_context = capture_runtime_context()

    if args.mode == "postgres":
        database_url = os.getenv("LOTUS_POSTGRES_PLAN_DATABASE_URL", DEFAULT_POSTGRES_URL)
        postgres_ready = _wait_for_postgres(database_url, args.postgres_ready_timeout_seconds)
        if not postgres_ready:
            log_path.write_text(
                f"PostgreSQL characterization database was unavailable at {database_url}\n",
                encoding="utf-8",
            )
            _write_summary(
                args=args,
                command=[],
                junit_path=junit_path,
                log_path=log_path,
                return_code=2,
                postgres_ready=postgres_ready,
                runtime_context=runtime_context,
            )
            return 2

    command = [
        sys.executable,
        "-m",
        "pytest",
        *BENCHMARK_PATHS[args.mode],
        "-q",
        "--durations=0",
        f"--junitxml={junit_path}",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    log_path.write_text(completed.stdout + completed.stderr, encoding="utf-8")
    summary_path = _write_summary(
        args=args,
        command=command,
        junit_path=junit_path,
        log_path=log_path,
        return_code=completed.returncode,
        postgres_ready=postgres_ready,
        runtime_context=runtime_context,
    )

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if completed.returncode:
        return completed.returncode
    if args.require_non_skipped and summary["tests"] > 0 and summary["tests"] == summary["skipped"]:
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"\nPostgreSQL characterization produced only skipped tests; see {summary_path.as_posix()}.\n")
        return 3

    return int(summary["artifact_validation_exit"])


if __name__ == "__main__":
    raise SystemExit(main())
