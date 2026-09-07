"""One image scan per CI job, so the artifact and the verdict describe one image.

`scripts/container_acceptance_gate.py` was rewritten to decide from a single scan
after review found three separate Trivy invocations behind one verdict. That fixed
the Makefile and left the same defect one level up: a workflow that runs
`make container-supply-chain-evidence` (which scans and uploads) and then
`make container-vulnerability-gate` (which depends on the same phony report target)
scans twice. The retained artifact is the first snapshot and the blocking decision
is made on the second, so a vulnerability-database update between them can upload
evidence that omits the finding which failed the job -- or pass a job whose
artifact contains a finding the verdict never saw.

The unit tests that existed did not cover this. They inspect each Make target on
its own, where each is correct: the gate genuinely must rebuild its report when
run bare, or it would judge whatever happens to be on disk. The defect only exists
in the *composition*, so a test of the parts cannot see it -- which is why this one
resolves prerequisites and counts the scans a job actually performs.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
SCAN_TARGET = "container-vulnerability-report"

_RULE = re.compile(r"^([A-Za-z0-9_.-]+)\s*:(?!=)\s*(.*)$")


def _prerequisites() -> dict[str, list[str]]:
    """Every `target: prereqs` rule in the Makefile, which is all this needs.

    Deliberately not a Make implementation. It resolves the one construct that
    creates the hazard -- a target pulling in another target that scans -- and a
    recipe using anything more exotic would be worth failing on rather than
    modelling.
    """

    rules: dict[str, list[str]] = {}
    for line in (REPO_ROOT / "Makefile").read_text(encoding="utf-8").splitlines():
        if line.startswith("\t") or line.lstrip().startswith("#"):
            continue
        match = _RULE.match(line)
        if match and match.group(1) != ".PHONY":
            rules[match.group(1)] = match.group(2).split()
    return rules


def _scans(target: str, rules: dict[str, list[str]], seen: frozenset[str] = frozenset()) -> int:
    """How many times invoking `target` reaches the scan target.

    Counted rather than tested for membership, because Make runs a phony
    prerequisite once per invocation that names it, and two invocations in one job
    are two scans.
    """

    if target in seen:
        return 0
    if target == SCAN_TARGET:
        return 1
    return sum(_scans(prereq, rules, seen | {target}) for prereq in rules.get(target, []))


def _make_invocations(job: dict) -> list[str]:
    targets: list[str] = []
    for step in job.get("steps") or []:
        for invocation in re.findall(r"\bmake\s+([A-Za-z0-9_.-]+)", step.get("run") or ""):
            targets.append(invocation)
    return targets


def _jobs_that_scan() -> list[tuple[str, str, int]]:
    rules = _prerequisites()
    found: list[tuple[str, str, int]] = []
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        document = yaml.safe_load(workflow.read_text(encoding="utf-8")) or {}
        for job_name, job in (document.get("jobs") or {}).items():
            scans = sum(_scans(target, rules) for target in _make_invocations(job))
            if scans:
                found.append((workflow.name, job_name, scans))
    return found


def test_at_least_one_job_scans_or_this_test_proves_nothing() -> None:
    """Guard against the vacuous pass.

    If a rename or a workflow move stopped this from matching any job, every
    assertion below would hold over an empty set and report success while checking
    nothing -- the failure mode this whole file exists to catch, reappearing in the
    check itself.
    """

    assert _jobs_that_scan(), (
        "no workflow job reaches the container scan target; either the scan moved and this "
        "test needs updating, or evidence production has been dropped from CI"
    )


@pytest.mark.parametrize(("workflow", "job", "scans"), _jobs_that_scan())
def test_a_job_scans_the_image_at_most_once(workflow: str, job: str, scans: int) -> None:
    """Two scans in one job means the uploaded evidence is not what was judged."""

    assert scans == 1, (
        f"{workflow} job {job!r} runs the image scan {scans} times. The uploaded artifact and "
        f"the blocking verdict would describe different scans, so a vulnerability-database "
        f"update between them can retain evidence that omits the finding which failed the "
        f"job. Invoke scripts/container_acceptance_gate.py against the scan already produced "
        f"rather than a target that rebuilds it."
    )


def test_the_judged_file_is_the_file_that_was_produced_and_uploaded() -> None:
    """Three artifacts name one path, and nothing connected them.

    While the lanes invoked `make container-vulnerability-gate`, the Makefile
    mediated this: the gate depended on the report target, so it judged whatever
    that target wrote. Calling the script directly removes that mediation and
    replaces it with the script's own `DEFAULT_SCAN` constant, which no test tied
    to the produced file. So the scan path, the judged path and the uploaded glob
    became three independent statements about one file.

    A mismatch fails closed today -- the script refuses a missing scan, and refuses
    a present one with no `Results` key, which is what the SBOM in the same
    directory would be. Fail-closed is the right behaviour and not a reason to
    leave the paths unpinned: it means the lane would break rather than pass
    wrongly, and a gate that cannot run is still a gate that is not running.
    """

    scan_path = re.search(
        r"DEFAULT_SCAN\s*=\s*(.+)", (REPO_ROOT / "scripts" / "container_acceptance_gate.py").read_text(encoding="utf-8")
    )
    assert scan_path is not None, "the gate no longer declares a default scan path"
    judged = scan_path.group(1)

    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    produced = "lotus-performance-image-vulnerabilities.json"

    assert produced in judged, (
        f"the gate judges {judged.strip()} but the report target writes {produced!r}. The lanes "
        f"now invoke the script directly, so the Makefile no longer holds these together."
    )
    assert (
        f"--output /output/{produced}" in makefile
    ), f"the report target no longer writes {produced!r}, which the gate judges by default"

    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        text = workflow.read_text(encoding="utf-8")
        if "container_acceptance_gate.py" not in text:
            continue
        assert "path: output/container-security/*.json" in text, (
            f"{workflow.name} judges the scan but does not upload the directory holding it, so "
            f"a failing verdict would have no evidence to explain it"
        )


def test_the_image_build_is_ordered_before_every_scan_of_it() -> None:
    """A sibling prerequisite is not an ordering.

    `container-vulnerability-gate: docker-build container-vulnerability-report`
    reads as "build, then scan" and is not: siblings may run concurrently under
    `make -j` or an inherited `MAKEFLAGS`. On a clean machine the scan fails
    because the tag does not exist yet; on a machine with a previous build it
    succeeds against the *older* image carrying the same tag, which is the worse
    outcome because the verdict looks valid.

    Both scanning targets consume the tag, so both must depend on the build
    rather than sit beside it. Asserted through the prerequisite graph rather
    than by reading one rule, because the property is reachability -- a target
    that reaches a scan without reaching the build is broken however the rule is
    spelled.
    """

    rules = _prerequisites()

    def reaches(target: str, goal: str, seen: frozenset[str] = frozenset()) -> bool:
        if target in seen:
            return False
        if target == goal:
            return True
        return any(reaches(prereq, goal, seen | {target}) for prereq in rules.get(target, []))

    scanning = {"container-sbom", "container-vulnerability-report"}
    assert scanning <= set(rules), f"a scanning target was renamed; this check now covers {scanning & set(rules)}"

    for scan_target in sorted(scanning):
        assert reaches(scan_target, "docker-build"), (
            f"{scan_target} scans the image tag without depending on docker-build, so under "
            f"`make -j` it can run before the build finishes -- failing on a clean machine, or "
            f"scanning a stale image of the same tag on one that has built before"
        )

    for entry_point in ("container-vulnerability-gate", "container-supply-chain-evidence"):
        assert reaches(entry_point, "docker-build"), f"{entry_point} judges an image it never builds"
