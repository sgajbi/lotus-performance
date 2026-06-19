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


def validate_artifact_action_versions(workflow_dir: Path = DEFAULT_WORKFLOW_DIR) -> list[GitHubActionRuntimeFinding]:
    findings: list[GitHubActionRuntimeFinding] = []
    for path in sorted(workflow_dir.glob("*.yml")):
        findings.extend(_artifact_action_findings(path=path, root=workflow_dir.parents[1]))
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


def _major_version(ref: str) -> int:
    match = re.fullmatch(r"v(?P<major>\d+)(?:\.\d+){0,2}", ref)
    if match is None:
        return 0
    return int(match.group("major"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail when GitHub artifact actions use Node 20-era major versions.")
    parser.add_argument(
        "--workflow-dir",
        type=Path,
        default=DEFAULT_WORKFLOW_DIR,
        help="Directory containing GitHub workflow YAML files.",
    )
    args = parser.parse_args(argv)

    findings = validate_artifact_action_versions(args.workflow_dir)
    if findings:
        for finding in findings:
            print(finding.format())
        return 1
    print("GitHub artifact action runtime guard passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
