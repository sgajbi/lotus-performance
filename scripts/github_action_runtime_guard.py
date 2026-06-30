from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKFLOW_DIR = ROOT / ".github" / "workflows"
ARTIFACT_ACTION_MINIMUM_MAJOR = {
    "actions/upload-artifact": 7,
    "actions/download-artifact": 8,
}
ARTIFACT_ACTION_PATTERN = re.compile(r"uses:\s*(?P<action>actions/(?:upload|download)-artifact)@(?P<ref>[^\s#]+)")
WORKFLOW_JOB_PATTERN = re.compile(r"^  (?P<job>[A-Za-z0-9_-]+):\s*(?:#.*)?$")
WORKFLOW_JOB_TIMEOUT_PATTERN = re.compile(r"^    timeout-minutes:\s*(?P<minutes>\d+)\s*(?:#.*)?$")


@dataclass(frozen=True)
class GitHubActionRuntimeFinding:
    path: str
    line: int
    action: str
    ref: str
    minimum_ref: str

    def format(self) -> str:
        return (
            f"{self.path}:{self.line}: {self.action}@{self.ref} must be "
            f"{self.minimum_ref} or newer for Node 24 runner compatibility"
        )


@dataclass(frozen=True)
class WorkflowJobTimeoutFinding:
    path: str
    line: int
    job: str

    def format(self) -> str:
        return f"{self.path}:{self.line}: workflow job {self.job} must declare timeout-minutes"


def validate_artifact_action_versions(workflow_dir: Path = DEFAULT_WORKFLOW_DIR) -> list[GitHubActionRuntimeFinding]:
    findings: list[GitHubActionRuntimeFinding] = []
    for path in sorted(workflow_dir.glob("*.yml")):
        findings.extend(_artifact_action_findings(path=path, root=workflow_dir.parents[1]))
    return findings


def validate_workflow_job_timeouts(workflow_dir: Path = DEFAULT_WORKFLOW_DIR) -> list[WorkflowJobTimeoutFinding]:
    findings: list[WorkflowJobTimeoutFinding] = []
    for path in sorted(workflow_dir.glob("*.yml")):
        findings.extend(_job_timeout_findings(path=path, root=workflow_dir.parents[1]))
    return findings


def _artifact_action_findings(path: Path, root: Path) -> list[GitHubActionRuntimeFinding]:
    findings: list[GitHubActionRuntimeFinding] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        match = ARTIFACT_ACTION_PATTERN.search(line)
        if match is None:
            continue
        action = match.group("action")
        ref = match.group("ref")
        minimum_major = ARTIFACT_ACTION_MINIMUM_MAJOR[action]
        if _major_version(ref) < minimum_major:
            findings.append(
                GitHubActionRuntimeFinding(
                    path=path.relative_to(root).as_posix(),
                    line=line_number,
                    action=action,
                    ref=ref,
                    minimum_ref=f"v{minimum_major}",
                )
            )
    return findings


def _job_timeout_findings(path: Path, root: Path) -> list[WorkflowJobTimeoutFinding]:
    findings: list[WorkflowJobTimeoutFinding] = []
    in_jobs_section = False
    current_job: str | None = None
    current_job_line = 0
    current_job_has_timeout = False

    def close_current_job() -> None:
        nonlocal current_job, current_job_line, current_job_has_timeout
        if current_job is not None and not current_job_has_timeout:
            findings.append(
                WorkflowJobTimeoutFinding(
                    path=path.relative_to(root).as_posix(),
                    line=current_job_line,
                    job=current_job,
                )
            )
        current_job = None
        current_job_line = 0
        current_job_has_timeout = False

    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line == "jobs:":
            in_jobs_section = True
            continue
        if not in_jobs_section:
            continue
        if line and not line.startswith((" ", "\t")):
            close_current_job()
            in_jobs_section = False
            continue
        job_match = WORKFLOW_JOB_PATTERN.match(line)
        if job_match is not None:
            close_current_job()
            current_job = job_match.group("job")
            current_job_line = line_number
            continue
        if current_job is not None and WORKFLOW_JOB_TIMEOUT_PATTERN.match(line) is not None:
            current_job_has_timeout = True

    close_current_job()
    return findings


def _major_version(ref: str) -> int:
    match = re.fullmatch(r"v(?P<major>\d+)(?:\.\d+){0,2}", ref)
    if match is None:
        return 0
    return int(match.group("major"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail when GitHub workflows miss runtime guardrails or use stale artifact actions."
    )
    parser.add_argument(
        "--workflow-dir",
        type=Path,
        default=DEFAULT_WORKFLOW_DIR,
        help="Directory containing GitHub workflow YAML files.",
    )
    args = parser.parse_args(argv)

    formatted_findings = [finding.format() for finding in validate_artifact_action_versions(args.workflow_dir)]
    formatted_findings.extend(finding.format() for finding in validate_workflow_job_timeouts(args.workflow_dir))
    if formatted_findings:
        for finding in formatted_findings:
            print(finding)
        return 1
    print("GitHub Actions runtime guard passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
