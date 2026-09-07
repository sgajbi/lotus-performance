"""The blocking gates must be invoked by a governed lane, not merely exist.

`lotus-performance` scanned every pull request for container vulnerabilities,
uploaded the findings, and passed regardless of what they said. Two targets
wrap the same scanner: `container-vulnerability-report` with `--exit-code 0`
and `container-vulnerability-gate` with `--exit-code 1`. The workflows ran the
first. The second was correctly written and invoked by nothing, so the
required `Container Supply Chain Evidence` check was green by construction.

`license-compliance-gate` had the same shape one step further out: it existed
only inside `check` and `ci`, and no workflow runs either of those.

These tests assert the WIRING rather than the presence of a command string. A
gate that exists is not a gate that runs, and a green required check is not
evidence that anything was enforced.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]

#: The lanes whose results can block a merge or a release.
GOVERNED_WORKFLOWS = ("pr-merge-gate.yml", "main-releasability.yml")


def _workflow(name: str) -> dict:
    return yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))


def _makefile_target(target: str) -> str:
    lines = (ROOT / "Makefile").read_text(encoding="utf-8").splitlines()
    start = next(index for index, line in enumerate(lines) if line.startswith(f"{target}:"))
    block = [lines[start]]
    for line in lines[start + 1 :]:
        if line and not line.startswith(("\t", " ")):
            break
        block.append(line)
    return "\n".join(block)


def _steps_running(workflow: dict, target: str) -> list[tuple[str, list[dict]]]:
    """Every job containing a step whose `run` invokes the make target."""
    found = []
    for job_name, job in workflow.get("jobs", {}).items():
        steps = job.get("steps") or []
        if any(f"make {target}" in (step.get("run") or "") for step in steps):
            found.append((job_name, steps))
    return found


@pytest.mark.parametrize("workflow_name", GOVERNED_WORKFLOWS)
def test_the_blocking_container_gate_runs_in_a_governed_lane(workflow_name: str) -> None:
    assert _steps_running(_workflow(workflow_name), "container-vulnerability-gate"), (
        f"{workflow_name} does not invoke container-vulnerability-gate. The evidence target "
        "passes regardless of findings, so without the gate this lane cannot fail on a CVE."
    )


@pytest.mark.parametrize("workflow_name", GOVERNED_WORKFLOWS)
def test_the_license_gate_runs_in_a_governed_lane(workflow_name: str) -> None:
    assert _steps_running(_workflow(workflow_name), "license-compliance-gate"), (
        f"{workflow_name} does not invoke license-compliance-gate. Membership of `check` or "
        "`ci` is not enough: no workflow runs either aggregate."
    )


def test_the_report_and_the_gate_differ_only_in_whether_they_can_fail() -> None:
    """The defect was a pair of near-identical targets whose exit codes diverge.

    Pinning both directions keeps a future edit from quietly making the gate
    non-blocking, which is how the original hole was indistinguishable from
    coverage."""

    report = _makefile_target("container-vulnerability-report")
    gate = _makefile_target("container-vulnerability-gate")

    assert "--exit-code 0" in report, "the evidence target must stay non-blocking"
    assert "--exit-code 1" in gate, "the gate must fail the job when findings exist"
    assert "--exit-code 0" not in gate, "a gate that cannot fail is not a gate"


def test_the_gate_does_not_exclude_what_the_promotion_policy_requires_recorded() -> None:
    """`--ignore-unfixed` belongs to the report, not the gate.

    `quality/container_supply_chain_report.md` scopes that option to the
    report-only baseline phase, and its promotion policy requires every
    high/critical finding to be zero or explicitly accepted with owner, expiry
    and remediation path. A gate that silently drops unfixable advisories
    enforces something narrower than the policy it is promoted under, and the
    difference is invisible in a green run."""

    assert "--ignore-unfixed" in _makefile_target(
        "container-vulnerability-report"
    ), "the report observes the baseline and may exclude unfixed findings"
    assert "--ignore-unfixed" not in _makefile_target("container-vulnerability-gate"), (
        "the blocking gate must not exclude findings the promotion policy requires " "to be zero or explicitly accepted"
    )


@pytest.mark.parametrize("workflow_name", GOVERNED_WORKFLOWS)
def test_diagnostics_survive_a_failing_scan(workflow_name: str) -> None:
    """The gate must run AFTER the upload, and the upload must not be skipped.

    A gate placed before the upload destroys the evidence a reader needs to act
    on the failure, so the failure arrives with nothing attached to it."""

    for job_name, steps in _steps_running(_workflow(workflow_name), "container-vulnerability-gate"):
        upload_index = next(
            (index for index, step in enumerate(steps) if "upload-artifact" in str(step.get("uses", ""))),
            None,
        )
        gate_index = next(
            index for index, step in enumerate(steps) if "make container-vulnerability-gate" in (step.get("run") or "")
        )

        assert upload_index is not None, f"{workflow_name}:{job_name} uploads no evidence"
        assert upload_index < gate_index, (
            f"{workflow_name}:{job_name} runs the gate before uploading evidence, so a failing "
            "scan discards its own diagnostics"
        )
        assert str(steps[upload_index].get("if", "")).strip() == "always()", (
            f"{workflow_name}:{job_name} uploads evidence conditionally; a failing earlier step "
            "would skip it and leave the failure unexplained"
        )
