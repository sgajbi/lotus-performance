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


def _steps_reaching_the_verdict(workflow: dict) -> list[str]:
    """Jobs whose steps reach the acceptance decision, by either route.

    A lane may call `make container-vulnerability-gate`, which scans and then
    decides, or the script directly against a scan the job already produced. Both
    block on an unaccepted finding; only the second avoids scanning twice in a job
    that also uploads evidence, which is why the workflows use it and the Makefile
    target keeps its prerequisite for bare local runs.

    Matching either is not a weakening. The property is that the lane runs the
    thing that can fail on a CVE, and `container_acceptance_gate.py` *is* that
    thing -- `make container-vulnerability-gate` only reaches it by calling it.
    Pinning the earlier spelling would have made this test enforce the double
    scan.
    """

    reaching = []
    for job_name, job in workflow.get("jobs", {}).items():
        for step in job.get("steps") or []:
            run = step.get("run") or ""
            if "make container-vulnerability-gate" in run or "container_acceptance_gate.py" in run:
                reaching.append(job_name)
                break
    return reaching


@pytest.mark.parametrize("workflow_name", GOVERNED_WORKFLOWS)
def test_the_blocking_container_gate_runs_in_a_governed_lane(workflow_name: str) -> None:
    """The lane must run the decision, not only the evidence that feeds it."""

    workflow = _workflow(workflow_name)

    assert _steps_reaching_the_verdict(workflow), (
        f"{workflow_name} does not reach the container acceptance decision by either route. "
        "The evidence target scans with `--exit-code 0` and passes regardless of findings, so "
        "without the decision this lane cannot fail on a CVE."
    )
    assert not _steps_running(workflow, "container-supply-chain-evidence") or _steps_reaching_the_verdict(
        workflow
    ), "a lane that produces evidence and never judges it publishes a scan nobody acted on"


@pytest.mark.parametrize("workflow_name", GOVERNED_WORKFLOWS)
def test_the_license_gate_runs_in_a_governed_lane(workflow_name: str) -> None:
    assert _steps_running(_workflow(workflow_name), "license-compliance-gate"), (
        f"{workflow_name} does not invoke license-compliance-gate. Membership of `check` or "
        "`ci` is not enough: no workflow runs either aggregate."
    )


def test_one_scan_produces_the_evidence_and_the_verdict() -> None:
    """The evidence and the verdict must come from the same snapshot.

    Three separate `docker run --rm` invocations previously stood behind one
    answer: the uploaded artifact, the acceptance validation, and the blocking
    decision. With no shared Trivy cache, a vulnerability-database update between
    them could make the retained artifact omit the finding that failed the job --
    so the evidence could not explain the verdict it was filed against.

    The report target now produces one unfiltered scan, and the gate depends on
    it and decides from it. Pinning the dependency is what stops a future edit
    reintroducing a second scan.
    """

    report = _makefile_target("container-vulnerability-report")
    gate = _makefile_target("container-vulnerability-gate")

    assert "--exit-code 0" in report, "the scan itself must not decide; the gate does"
    assert "lotus-performance-image-vulnerabilities.json" in report
    assert "container-vulnerability-report" in gate, (
        "the gate must consume the scan the report produced, or it judges the current image "
        "by whatever report happens to be on disk"
    )
    assert "scripts/container_acceptance_gate.py" in gate
    assert "docker run" not in gate, "a second scan in the gate reintroduces the divergence this consolidation removed"


def test_the_retained_evidence_contains_what_the_gate_acts_on() -> None:
    """`--ignore-unfixed` must not filter the artifact or the verdict.

    `quality/container_supply_chain_report.md` requires every high/critical
    finding to be zero or explicitly accepted with owner, expiry and remediation
    path. A scan that drops unfixable advisories enforces something narrower than
    the policy it is promoted under -- and, once that scan is also the retained
    evidence, produces an artifact that cannot show why the job failed.

    Unfixable advisories are excluded by acceptance, in
    `quality/container_vulnerability_acceptances.v1.json`, where each carries an
    owner and an expiry. That is the difference between a recorded decision and a
    hidden one.
    """

    assert "--ignore-unfixed" not in _makefile_target(
        "container-vulnerability-report"
    ), "the retained artifact must contain the findings the gate acts on"
    assert "--ignore-unfixed" not in _makefile_target("container-vulnerability-gate")


def _verdict_jobs(workflow: dict) -> list[tuple[str, list[dict]]]:
    """Jobs whose steps reach the acceptance decision, by either route.

    This must recognise the same two spellings as `_steps_reaching_the_verdict`.
    It previously matched only `make container-vulnerability-gate`, and when both
    lanes moved to invoking the script directly it began returning an empty list
    -- so the ordering test below looped over nothing and passed while asserting
    nothing. Moving the upload after the verdict, or dropping its `if: always()`,
    would have stayed green.
    """

    found = []
    for job_name, job in workflow.get("jobs", {}).items():
        steps = job.get("steps") or []
        if any(
            "make container-vulnerability-gate" in (step.get("run") or "")
            or "container_acceptance_gate.py" in (step.get("run") or "")
            for step in steps
        ):
            found.append((job_name, steps))
    return found


@pytest.mark.parametrize("workflow_name", GOVERNED_WORKFLOWS)
def test_diagnostics_survive_a_failing_scan(workflow_name: str) -> None:
    """The gate must run AFTER the upload, and the upload must not be skipped.

    A gate placed before the upload destroys the evidence a reader needs to act
    on the failure, so the failure arrives with nothing attached to it."""

    jobs = _verdict_jobs(_workflow(workflow_name))
    assert jobs, (
        f"{workflow_name} has no job reaching the container acceptance decision, so every "
        f"assertion below would hold over an empty set and report success while checking nothing"
    )

    for job_name, steps in jobs:
        upload_index = next(
            (index for index, step in enumerate(steps) if "upload-artifact" in str(step.get("uses", ""))),
            None,
        )
        gate_index = next(
            index
            for index, step in enumerate(steps)
            if "make container-vulnerability-gate" in (step.get("run") or "")
            or "container_acceptance_gate.py" in (step.get("run") or "")
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
