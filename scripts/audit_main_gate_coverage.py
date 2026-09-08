"""Fail-closed audit of verdict-bearing Main Releasability runs on main."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys

WORKFLOW = "main-releasability.yml"
VERDICTS = {"success", "failure"}


def _git(*args: str) -> list[str]:
    completed = subprocess.run(["git", *args], check=True, capture_output=True, text=True)
    return [line for line in completed.stdout.splitlines() if line.strip()]


def _run_conclusions(sha: str) -> list[str] | None:
    completed = subprocess.run(
        ["gh", "run", "list", "--workflow", WORKFLOW, "--commit", sha, "--json", "conclusion,status"],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return None
    try:
        runs = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError:
        return None
    return [str(run.get("conclusion") or run.get("status") or "") for run in runs]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since-days", type=int, default=7)
    parser.add_argument("--limit", type=int, default=400)
    parser.add_argument("--fail-on-gap", action="store_true")
    args = parser.parse_args()
    if shutil.which("gh") is None:
        print("gh is not available; main-gate coverage is unverifiable.")
        return 1 if args.fail_on_gap else 0

    probed = _git(
        "log",
        f"--since-as-filter={args.since_days} days ago",
        f"-{args.limit + 1}",
        "--format=%H %h %s",
        "origin/main",
    )
    truncated = len(probed) > args.limit
    commits = probed[: args.limit]
    ungated: list[str] = []
    unknown: list[str] = []
    failing: list[str] = []
    passing = 0
    for entry in commits:
        sha, short, subject = entry.split(" ", 2)
        conclusions = _run_conclusions(sha)
        if conclusions is None:
            unknown.append(short)
            print(f"UNKNOWN  {short}  run listing could not be fetched")
            continue
        verdicts = [conclusion for conclusion in conclusions if conclusion in VERDICTS]
        if verdicts:
            if "success" in verdicts:
                passing += 1
            else:
                failing.append(f"{short}  {subject[:70]}")
            continue
        if conclusions:
            unknown.append(short)
            print(f"UNKNOWN  {short}  runs exist without a verdict: {sorted(set(conclusions))}")
        else:
            ungated.append(f"{short}  {subject[:70]}")
            print(f"UNGATED  {short}  {subject[:70]}")

    print(
        f"audited {len(commits)} commit(s); {len(ungated)} ungated; "
        f"{len(unknown)} unverifiable; {passing} passing; {len(failing)} failing verdict(s)."
    )
    if truncated:
        print(f"WINDOW TRUNCATED at {args.limit}; raise --limit and rerun.")
    for entry in failing:
        print(f"FAILING  {entry}")
    if args.fail_on_gap and (ungated or unknown or truncated):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
