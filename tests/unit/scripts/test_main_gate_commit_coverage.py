from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from scripts import audit_main_gate_coverage as audit

ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = ROOT / ".github" / "workflows"


def _args(**overrides):
    values = {"limit": 400, "since_days": 7, "fail_on_gap": True} | overrides
    return argparse.Namespace(**values)


def test_dispatcher_enumerates_exact_landed_range_under_rebase_only_policy() -> None:
    workflow = (WORKFLOWS / "merged-pr-main-releasability.yml").read_text(encoding="utf-8")

    assert "fetch-depth: 0" in workflow
    assert 'git rev-list --reverse "$BASE_SHA..$MERGE_COMMIT_SHA"' in workflow
    assert '"${#revisions[@]}" -eq 0' in workflow
    assert '"${#revisions[@]}" -gt "$COMMIT_COUNT"' in workflow
    assert '"${#revisions[@]}" -lt "$COMMIT_COUNT"' in workflow
    assert "Rebase dropped" in workflow
    assert '"$merge_methods" != "false,false,true"' in workflow
    assert 'for revision in "${revisions[@]}"; do' in workflow
    assert '-f expected_sha="$revision"' in workflow
    guard = 'if ! git merge-base --is-ancestor "$revision" HEAD; then'
    assert workflow.index(guard) < workflow.index('dispatch_ref="main-releasability-${revision}"')


def _shipped_dispatcher_script() -> str:
    workflow = (WORKFLOWS / "merged-pr-main-releasability.yml").read_text(encoding="utf-8")
    start_marker = "        run: |\n"
    start = workflow.index(start_marker) + len(start_marker)
    return textwrap.dedent(workflow[start:])


def _run_shipped_dispatcher(
    tmp_path: Path,
    *,
    commit_count: int,
    landed_commit_count: int,
    base_sha_override: str | None = None,
    tag_lookup_mode: str = "missing",
) -> subprocess.CompletedProcess[str]:
    # Git for Windows exposes its Bash-compatible shell as ``sh``; the Windows
    # System32 ``bash`` launcher can point at an unavailable WSL distribution.
    shell = shutil.which("sh") if os.name == "nt" else (shutil.which("bash") or shutil.which("sh"))
    if shell is None:
        pytest.skip("Bash is required to execute the shipped dispatcher workflow")

    origin = tmp_path / "origin.git"
    source = tmp_path / "source"
    runner = tmp_path / "runner"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "clone", str(origin), str(source)], check=True, capture_output=True, text=True)
    landed_revisions: list[str] = []
    for index in range(landed_commit_count + 1):
        if index == 1:
            changed_path = source / "src" / "source-lineage.py"
        elif index == 2:
            changed_path = source / ".github" / "workflows" / "workflow-touch.yml"
        else:
            changed_path = source / "history.txt"
        changed_path.parent.mkdir(parents=True, exist_ok=True)
        changed_path.write_text(f"revision {index}\n", encoding="utf-8")
        subprocess.run(["git", "add", str(changed_path.relative_to(source))], cwd=source, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Lotus Test",
                "-c",
                "user.email=test@example.com",
                "commit",
                "-m",
                f"revision {index}",
            ],
            cwd=source,
            check=True,
            capture_output=True,
            text=True,
        )
        if index == 0:
            base_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=source, check=True, capture_output=True, text=True
            ).stdout.strip()
        else:
            landed_revisions.append(
                subprocess.run(
                    ["git", "rev-parse", "HEAD"], cwd=source, check=True, capture_output=True, text=True
                ).stdout.strip()
            )
    subprocess.run(["git", "branch", "-M", "main"], cwd=source, check=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=source, check=True, capture_output=True, text=True)
    merge_commit_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=source, check=True, capture_output=True, text=True
    ).stdout.strip()
    subprocess.run(
        ["git", "clone", "--branch", "main", str(origin), str(runner)], check=True, capture_output=True, text=True
    )
    call_log = tmp_path / "gh-calls.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh_stub = bin_dir / "gh"
    gh_stub.write_text(
        "#!/bin/sh\n"
        '{ for argument in "$@"; do printf \'%s\\t\' "$argument"; done; printf \'\\n\'; } >> "$GH_CALL_LOG"\n'
        'if [ "$1" = api ] && [ "$2" = "repos/$GITHUB_REPOSITORY" ]; then\n'
        "  printf '%s\\n' 'false,false,true'\n"
        "  exit 0\n"
        "fi\n"
        'case "$2" in\n'
        "  */git/ref/tags/*)\n"
        '    if [ "$GH_TAG_LOOKUP_MODE" = matching ]; then printf \'%s\\n\' "${2##*-}"; exit 0; fi\n'
        "    printf '%s\\n' '{\\\"message\\\":\\\"Not Found\\\"}'; exit 1 ;;\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    gh_stub.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "BASE_SHA": base_sha_override or base_sha,
            "MERGE_COMMIT_SHA": merge_commit_sha,
            "COMMIT_COUNT": str(commit_count),
            "GITHUB_REPOSITORY": "sgajbi/lotus-performance",
            "PR_NUMBER": "523",
            "GH_TOKEN": "test-token",
            "GH_CALL_LOG": str(call_log),
            "GH_TAG_LOOKUP_MODE": tag_lookup_mode,
            "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
        }
    )
    completed = subprocess.run(
        [shell, "-c", _shipped_dispatcher_script()],
        cwd=runner,
        env=env,
        capture_output=True,
        text=True,
    )
    completed.gh_calls = (  # type: ignore[attr-defined]
        [
            [argument for argument in line.split("\t") if argument]
            for line in call_log.read_text(encoding="utf-8").splitlines()
        ]
        if call_log.exists()
        else []
    )
    completed.landed_revisions = landed_revisions  # type: ignore[attr-defined]
    return completed


def test_shipped_dispatcher_accepts_a_rebase_drop_and_dispatches_exact_immutable_revisions(tmp_path: Path) -> None:
    completed = _run_shipped_dispatcher(tmp_path, commit_count=3, landed_commit_count=2)

    assert completed.returncode == 0, completed.stderr
    assert "Rebase dropped 1 already-landed revision(s)" in completed.stdout
    landed_revisions = completed.landed_revisions  # type: ignore[attr-defined]
    assert len(landed_revisions) == 2
    assert (
        "src/source-lineage.py"
        in subprocess.run(
            ["git", "show", "--format=", "--name-only", landed_revisions[0]],
            cwd=tmp_path / "runner",
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    assert (
        ".github/workflows/workflow-touch.yml"
        in subprocess.run(
            ["git", "show", "--format=", "--name-only", landed_revisions[1]],
            cwd=tmp_path / "runner",
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    expected_calls = [
        [
            "api",
            "repos/sgajbi/lotus-performance",
            "--jq",
            "[.allow_squash_merge, .allow_merge_commit, .allow_rebase_merge] | @csv",
        ]
    ]
    for revision in landed_revisions:
        dispatch_ref = f"main-releasability-{revision}"
        expected_calls.extend(
            [
                ["api", f"repos/sgajbi/lotus-performance/git/ref/tags/{dispatch_ref}", "--jq", ".object.sha"],
                [
                    "api",
                    "repos/sgajbi/lotus-performance/git/refs",
                    "-f",
                    f"ref=refs/tags/{dispatch_ref}",
                    "-f",
                    f"sha={revision}",
                ],
                [
                    "workflow",
                    "run",
                    "main-releasability.yml",
                    "--repo",
                    "sgajbi/lotus-performance",
                    "--ref",
                    dispatch_ref,
                    "-f",
                    f"expected_sha={revision}",
                    "-f",
                    "triggering_pr=523",
                ],
            ]
        )
    assert completed.gh_calls == expected_calls  # type: ignore[attr-defined]


def test_shipped_dispatcher_reuses_a_matching_existing_immutable_tag(tmp_path: Path) -> None:
    completed = _run_shipped_dispatcher(
        tmp_path,
        commit_count=1,
        landed_commit_count=1,
        tag_lookup_mode="matching",
    )

    assert completed.returncode == 0, completed.stderr
    revision = completed.landed_revisions[0]  # type: ignore[attr-defined]
    dispatch_ref = f"main-releasability-{revision}"
    assert completed.gh_calls == [  # type: ignore[attr-defined]
        [
            "api",
            "repos/sgajbi/lotus-performance",
            "--jq",
            "[.allow_squash_merge, .allow_merge_commit, .allow_rebase_merge] | @csv",
        ],
        ["api", f"repos/sgajbi/lotus-performance/git/ref/tags/{dispatch_ref}", "--jq", ".object.sha"],
        [
            "workflow",
            "run",
            "main-releasability.yml",
            "--repo",
            "sgajbi/lotus-performance",
            "--ref",
            dispatch_ref,
            "-f",
            f"expected_sha={revision}",
            "-f",
            "triggering_pr=523",
        ],
    ]


def test_dispatcher_refuses_an_empty_landed_range(tmp_path: Path) -> None:
    completed = _run_shipped_dispatcher(tmp_path, commit_count=1, landed_commit_count=0)

    assert completed.returncode != 0
    assert "produced no landed revisions" in completed.stdout
    assert completed.gh_calls == [
        [
            "api",
            "repos/sgajbi/lotus-performance",
            "--jq",
            "[.allow_squash_merge, .allow_merge_commit, .allow_rebase_merge] | @csv",
        ]
    ]  # type: ignore[attr-defined]


def test_dispatcher_refuses_more_landed_revisions_than_the_merge_event_reports(tmp_path: Path) -> None:
    completed = _run_shipped_dispatcher(tmp_path, commit_count=1, landed_commit_count=2)

    assert completed.returncode != 0
    assert "exceeding the PR event count" in completed.stdout
    assert completed.gh_calls == [
        [
            "api",
            "repos/sgajbi/lotus-performance",
            "--jq",
            "[.allow_squash_merge, .allow_merge_commit, .allow_rebase_merge] | @csv",
        ]
    ]  # type: ignore[attr-defined]


def test_shipped_dispatcher_refuses_a_non_ancestor_range_before_dispatch(tmp_path: Path) -> None:
    completed = _run_shipped_dispatcher(
        tmp_path,
        commit_count=2,
        landed_commit_count=2,
        base_sha_override="f" * 40,
    )

    assert completed.returncode != 0
    assert "is not an ancestor of landed tip" in completed.stdout
    assert completed.gh_calls == [
        [
            "api",
            "repos/sgajbi/lotus-performance",
            "--jq",
            "[.allow_squash_merge, .allow_merge_commit, .allow_rebase_merge] | @csv",
        ]
    ]  # type: ignore[attr-defined]


def test_releasability_evidence_is_never_cancelled() -> None:
    workflow = (WORKFLOWS / "main-releasability.yml").read_text(encoding="utf-8")
    assert "cancel-in-progress: false" in workflow


def test_scheduled_audit_fails_closed() -> None:
    workflow = (WORKFLOWS / "main-gate-coverage-audit.yml").read_text(encoding="utf-8")
    assert "schedule:" in workflow
    assert "--fail-on-gap" in workflow


def test_audit_refuses_ungated_cancelled_and_unverifiable(monkeypatch, capsys) -> None:
    commits = {"a" * 40: ["success"], "b" * 40: ["cancelled"], "c" * 40: None, "d" * 40: []}
    monkeypatch.setattr(audit, "_git", lambda *args: [f"{sha} {sha[:9]} subject" for sha in commits])
    monkeypatch.setattr(audit, "_run_conclusions", lambda sha: commits[sha])
    monkeypatch.setattr(audit.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(audit.argparse.ArgumentParser, "parse_args", lambda self: _args())

    assert audit.main() == 1
    output = capsys.readouterr().out
    assert "UNGATED  ddddddddd" in output
    assert "UNKNOWN  bbbbbbbbb" in output
    assert "UNKNOWN  ccccccccc" in output


def test_audit_reports_failing_verdict_as_covered(monkeypatch, capsys) -> None:
    commits = {"a" * 40: ["success"], "b" * 40: ["failure"]}
    monkeypatch.setattr(audit, "_git", lambda *args: [f"{sha} {sha[:9]} subject" for sha in commits])
    monkeypatch.setattr(audit, "_run_conclusions", lambda sha: commits[sha])
    monkeypatch.setattr(audit.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(audit.argparse.ArgumentParser, "parse_args", lambda self: _args())

    assert audit.main() == 0
    assert "1 failing verdict(s)" in capsys.readouterr().out


def test_audit_fails_when_window_is_truncated(monkeypatch) -> None:
    commits = [f"{index:040x}" for index in range(4)]
    monkeypatch.setattr(audit, "_git", lambda *args: [f"{sha} {sha[:9]} subject" for sha in commits])
    monkeypatch.setattr(audit, "_run_conclusions", lambda sha: ["success"])
    monkeypatch.setattr(audit.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(audit.argparse.ArgumentParser, "parse_args", lambda self: _args(limit=3))

    assert audit.main() == 1
