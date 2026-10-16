"""One vulnerability analysis per CI job, including the SBOM recipe.

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

import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts.container_scan_evidence import REPORT_NAME

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
PRODUCER = "scripts/container_scan_evidence.py"

_RULE = re.compile(r"^([A-Za-z0-9_.-]+)\s*:(?!=)\s*(.*)$")


def _rules(text: str) -> dict[str, tuple[list[str], str]]:
    """Every `target: prereqs` rule in the Makefile, which is all this needs.

    Deliberately not a Make implementation. It resolves the one construct that
    creates the hazard -- a target pulling in another target that scans -- and a
    recipe using anything more exotic would be worth failing on rather than
    modelling.
    """

    rules: dict[str, tuple[list[str], str]] = {}
    target = None
    for line in text.splitlines():
        if line.startswith("\t") and target:
            prerequisites, recipe = rules[target]
            rules[target] = prerequisites, recipe + line.strip() + "\n"
            continue
        if line.lstrip().startswith("#"):
            continue
        match = _RULE.match(line)
        if match and match.group(1) != ".PHONY":
            target = match.group(1)
            rules[target] = match.group(2).split(), ""
    return rules


def _prerequisites() -> dict[str, list[str]]:
    return {name: prerequisites for name, (prerequisites, _) in _rules(_makefile()).items()}


def _makefile() -> str:
    return (REPO_ROOT / "Makefile").read_text(encoding="utf-8")


def _analyses(command: str) -> int:
    """Count the bounded native/report-producer entrypoints, not target names."""
    command = command.replace("\\\n", " ")
    count = 0
    # These are the literal command separators admitted by this bounded guard.
    # Splitting per command keeps the next command's flags out of this one's options.
    for line in re.split(r"&&|;|\n", command):
        if line.lstrip().startswith("#"):
            continue
        relevant = re.search(r"\b(?:make|trivy|docker\s+run)\b|" + re.escape(PRODUCER), line)
        assert not relevant or not re.search(r"[|&<>`]", line), "unsupported scan command shell form"
        count += len(re.findall(r"\bpython(?:3)?\s+(?:-B\s+)?" + re.escape(PRODUCER) + r"\b", line))
        match = re.search(r"(?:docker\s+run\b|\btrivy\b).*?\bimage\s+(.*)", line)
        if not match or "--download-db-only" in match.group(1):
            continue
        options = match.group(1)
        scanners = re.search(r"--scanners(?:=|\s+)([^\s]+)", options)
        if scanners:
            count += "vuln" in scanners.group(1).strip("\"'").split(",")
        else:
            count += not re.search(r"--format(?:=|\s+)(?:cyclonedx|spdx(?:-json)?)\b", options)
    return count


def _scans(target: str | list[str], rules: dict[str, tuple[list[str], str]]) -> int:
    # All goals of ONE Make invocation share prerequisite evaluation, even with -j.
    visited: set[str] = set()

    def visit(name: str) -> int:
        if name in visited:
            return 0
        visited.add(name)
        prerequisites, recipe = rules.get(name, ([], ""))
        return sum(visit(prerequisite) for prerequisite in prerequisites) + _analyses(recipe)

    goals = [target] if isinstance(target, str) else target
    assert goals and all(goal in rules for goal in goals), f"unsupported or unknown Make goals: {goals}"
    return sum(visit(goal) for goal in goals)


def _make_invocations(job: dict) -> list[list[str]]:
    invocations: list[list[str]] = []
    for step in job.get("steps") or []:
        command = (step.get("run") or "").replace("\\\n", " ")
        # GitHub expression values are data in existing Make variable assignments.
        command = re.sub(r"\$\{\{.*?\}\}", "CI_VALUE", command)
        for segment in re.split(r"&&|;|\n", command):
            if segment.lstrip().startswith("#"):
                continue
            match = re.search(r"\bmake\b(.*)", segment)
            if not match:
                continue
            assert not re.search(r"[|&<>`]", match[1]), "unsupported Make command shell form"
            try:
                arguments = shlex.split(match[1], comments=True)
            except ValueError as exc:
                raise AssertionError("unsupported Make quoting") from exc
            goals: list[str] = []
            index = 0
            while index < len(arguments):
                argument = arguments[index]
                if argument in ("-j", "--jobs"):
                    if index + 1 < len(arguments) and arguments[index + 1].isdigit():
                        index += 1
                elif re.fullmatch(r"-j[1-9]\d*|--jobs=[1-9]\d*", argument):
                    pass
                elif re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", argument):
                    pass
                else:
                    assert re.fullmatch(r"[A-Za-z0-9_.-]+", argument) and not argument.startswith(
                        "-"
                    ), f"unsupported Make argument: {argument}"
                    goals.append(argument)
                index += 1
            assert goals, "unsupported Make invocation without explicit goals"
            invocations.append(goals)
    return invocations


def _jobs_that_scan() -> list[tuple[str, str, int]]:
    rules = _rules(_makefile())
    found: list[tuple[str, str, int]] = []
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        document = yaml.safe_load(workflow.read_text(encoding="utf-8")) or {}
        for job_name, job in (document.get("jobs") or {}).items():
            scans = sum(_scans(target, rules) for target in _make_invocations(job))
            scans += sum(_analyses(step.get("run") or "") for step in job.get("steps") or [])
            if scans:
                found.append((workflow.name, job_name, scans))
    return found


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("docker run scanner image --format cyclonedx image:ci", 0),
        ("docker run scanner image --scanners vuln --format cyclonedx image:ci", 1),
        ("docker run scanner image --scanners=vuln,secret --format json image:ci", 1),
        ("docker run scanner image --download-db-only", 0),
        ("trivy image --severity HIGH,CRITICAL --format json image:ci", 1),
        (f"python {PRODUCER} --image image:ci", 1),
        (f"python {PRODUCER}\npython {PRODUCER}", 2),
        ("trivy image --format json first && trivy image --format json second", 2),
        ("docker run scanner image --format cyclonedx first; trivy image --format json second", 1),
    ],
)
def test_analysis_counter_distinguishes_inventory_acquisition_and_analysis(command: str, expected: int) -> None:
    assert _analyses(command) == expected


def test_shared_prerequisite_is_counted_once_but_separate_make_calls_are_not() -> None:
    rules = _rules(
        "all: left right\nleft: report\nright: report\nreport:\n"
        "\ttrivy image --scanners vuln --format json image:ci\n"
    )
    assert _scans("all", rules) == 1
    assert _scans(["left", "right"], rules) == 1
    assert _scans(["all", "report"], rules) == 1
    assert sum(_scans(target, rules) for target in ["all", "report"]) == 2


@pytest.mark.parametrize(
    ("command", "native_invocations", "expected"),
    [
        ("make all", [["all"]], 1),
        ("make left right", [["left", "right"]], 1),
        ("make left\nmake right", [["left"], ["right"]], 2),
        ("make all report", [["all", "report"]], 1),
        ("make report independent", [["report", "independent"]], 2),
        ("make -j2 report independent", [["-j2", "report", "independent"]], 2),
        ("make inventory", [["inventory"]], 0),
        ("make inventory report", [["inventory", "report"]], 1),
        ("trivy image --scanners vuln --format json image:ci", [["report"]], 1),
        (f"python {PRODUCER} --image image:ci", [["helper"]], 1),
        (f"trivy image --format json image:ci\npython {PRODUCER}", [["report"], ["helper"]], 2),
        ("make hidden-direct", [["hidden-direct"]], 2),
        ("make hidden-helper", [["hidden-helper"]], 2),
    ],
)
def test_composition_count_matches_native_make_markers(
    tmp_path: Path, command: str, native_invocations: list[list[str]], expected: int
) -> None:
    """Execute only harmless markers; scanner commands exist only in the logical fixture."""
    fixture = (
        ".PHONY: all left right report independent inventory helper hidden-direct hidden-helper\n"
        "all: left right\nleft: report\nright: report\n"
        "report:\n\t@echo ANALYSIS_REPORT\n"
        "independent:\n\t@echo ANALYSIS_INDEPENDENT\n"
        "inventory:\n\t@echo INVENTORY_ONLY\n"
        "helper:\n\t@echo ANALYSIS_HELPER\n"
        "hidden-direct:\n\t@echo ANALYSIS_DIRECT_ONE && echo ANALYSIS_DIRECT_TWO\n"
        "hidden-helper:\n\t@echo ANALYSIS_HELPER_ONE && echo ANALYSIS_HELPER_TWO\n"
    )
    replacements = {
        "@echo ANALYSIS_REPORT": "trivy image --scanners vuln --format json image:ci",
        "@echo ANALYSIS_INDEPENDENT": "trivy image --scanners vuln --format json independent:ci",
        "@echo INVENTORY_ONLY": "docker run scanner image --format cyclonedx image:ci",
        "@echo ANALYSIS_HELPER\n": f"python {PRODUCER} --image image:ci\n",
        "@echo ANALYSIS_DIRECT_ONE && echo ANALYSIS_DIRECT_TWO": (
            "trivy image --format json first && trivy image --format json second"
        ),
        "@echo ANALYSIS_HELPER_ONE && echo ANALYSIS_HELPER_TWO": f"python {PRODUCER} && python {PRODUCER}",
    }
    logical = fixture
    for marker, entrypoint in replacements.items():
        assert logical.count(marker) == 1
        logical = logical.replace(marker, entrypoint)
    make = shutil.which("make")
    assert make, "native GNU Make is required for the composition premise check"
    path = tmp_path / "marker-fixture.mk"
    path.write_text(fixture, encoding="utf-8")
    environment = dict(os.environ)
    for name in ("MAKEFLAGS", "MFLAGS", "GNUMAKEFLAGS", "MAKEFILES"):
        environment.pop(name, None)
    observed = 0
    for goals in native_invocations:
        result = subprocess.run(
            [make, "--no-print-directory", "-rR", "-f", str(path), *goals],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        assert result.returncode == 0, result.stderr
        observed += len(re.findall(r"(?m)^ANALYSIS_[A-Z_]+\s*$", result.stdout))
    job = {"steps": [{"run": command}]}
    predicted = sum(_scans(goals, _rules(logical)) for goals in _make_invocations(job)) + _analyses(command)
    assert observed == expected == predicted


@pytest.mark.parametrize(
    "command",
    [
        "make -f other.mk report",
        "make -C other report",
        "make --eval=other report",
        "make ${GOAL}",
        "make",
        "make report | make independent",
        "make report > output.txt",
        "trivy image --format json first | trivy image --format json second",
    ],
)
def test_unsupported_composition_forms_fail_clearly(command: str) -> None:
    with pytest.raises(AssertionError, match="unsupported"):
        _make_invocations({"steps": [{"run": command}]})
        _analyses(command)


def test_sbom_recipe_cannot_enable_vulnerability_analysis() -> None:
    recipe = _rules(_makefile())["container-sbom"][1]
    assert "--format cyclonedx" in recipe
    assert "--scanners" not in recipe
    assert _analyses(recipe) == 0


def _producer_contract(text: str) -> None:
    rules = _rules(text)
    sbom = rules["container-sbom"][1]
    report = rules["container-vulnerability-report"][1]
    assert "--format cyclonedx" in sbom and "--scanners" not in sbom
    assert not re.search(r"(?:--env(?:-file)?|-e|--config)(?:=|\s)", sbom)
    assert re.search(r"^TRIVY_SEVERITY\s*\?=\s*HIGH,CRITICAL\s*$", text, re.MULTILINE)
    assert PRODUCER in report and _analyses(report) == 1
    assert report.count("--severity") == 1 and "--severity $(call shellquote,$(TRIVY_SEVERITY))" in report
    assert "--output-dir $(call shellquote,$(CONTAINER_SECURITY_OUTPUT_DIR))" in report
    assert not re.search(r"--(?:ignore-unfixed|ignore-status|ignorefile|ignore-policy|vex)\b", sbom + report)


def test_actual_producer_contract_preserves_inventory_severity_and_output() -> None:
    _producer_contract(_makefile())


@pytest.mark.parametrize(
    "bad", ["sbom_vuln", "sbom_env", "second_helper", "severity", "filter", "suppression", "output"]
)
def test_producer_contract_refuses_representative_bad_compositions(bad: str) -> None:
    text = _makefile()
    replacements = {
        "sbom_vuln": ("image --format cyclonedx", "image --scanners vuln --format cyclonedx"),
        "sbom_env": ("image --format cyclonedx", "image --env TRIVY_SCANNERS=vuln --format cyclonedx"),
        "second_helper": (f"python {PRODUCER}", f"python {PRODUCER}\n\tpython {PRODUCER}"),
        "severity": ("TRIVY_SEVERITY ?= HIGH,CRITICAL", "TRIVY_SEVERITY ?= LOW"),
        "filter": ("--severity $(call shellquote,$(TRIVY_SEVERITY))", "--severity LOW"),
        "suppression": (f"python {PRODUCER}", f"python {PRODUCER} --ignore-unfixed"),
        "output": ("--output-dir $(call shellquote,$(CONTAINER_SECURITY_OUTPUT_DIR))", "--output-dir other"),
    }
    old, new = replacements[bad]
    assert old in text, "bad-input fixture must alter the real producer contract"
    with pytest.raises(AssertionError):
        _producer_contract(text.replace(old, new, 1))


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
    produced = REPORT_NAME

    assert produced in judged, (
        f"the gate judges {judged.strip()} but the report target writes {produced!r}. The lanes "
        f"now invoke the script directly, so the Makefile no longer holds these together."
    )
    assert PRODUCER in _rules(makefile)["container-vulnerability-report"][1]
    assert "--output-dir $(call shellquote,$(CONTAINER_SECURITY_OUTPUT_DIR))" in makefile

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
