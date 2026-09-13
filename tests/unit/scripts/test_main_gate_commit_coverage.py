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


def _landed_range_guard_block() -> str:
    workflow = (WORKFLOWS / "merged-pr-main-releasability.yml").read_text(encoding="utf-8")
    start_marker = '          mapfile -t revisions < <(git rev-list --reverse "$BASE_SHA..$MERGE_COMMIT_SHA")\n'
    end_marker = '          for revision in "${revisions[@]}"; do\n'
    start = workflow.index(start_marker)
    end = workflow.index(end_marker, start)
    return textwrap.dedent(workflow[start:end])


def _run_landed_range_guard(
    tmp_path: Path,
    *,
    commit_count: int,
    landed_commit_count: int,
) -> subprocess.CompletedProcess[str]:
    # Git for Windows supplies a POSIX-compatible ``sh``. Prefer it over the
    # Windows System32 WSL launcher, while CI invokes Bash explicitly.
    shell = shutil.which("sh") if os.name == "nt" else shutil.which("bash")
    if shell is None:
        pytest.skip("Bash is required to execute the shipped workflow range guard")

    origin = tmp_path / "origin.git"
    source = tmp_path / "source"
    runner = tmp_path / "runner"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "clone", str(origin), str(source)], check=True, capture_output=True, text=True)
    for index in range(landed_commit_count + 1):
        (source / "history.txt").write_text(f"revision {index}\n", encoding="utf-8")
        subprocess.run(["git", "add", "history.txt"], cwd=source, check=True)
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
    subprocess.run(["git", "branch", "-M", "main"], cwd=source, check=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=source, check=True, capture_output=True, text=True)
    merge_commit_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=source, check=True, capture_output=True, text=True
    ).stdout.strip()
    subprocess.run(
        ["git", "clone", "--branch", "main", str(origin), str(runner)], check=True, capture_output=True, text=True
    )
    env = os.environ.copy()
    env.update(
        {
            "BASE_SHA": base_sha,
            "MERGE_COMMIT_SHA": merge_commit_sha,
            "COMMIT_COUNT": str(commit_count),
        }
    )
    return subprocess.run(
        [shell, "-eu", "-c", _landed_range_guard_block()],
        cwd=runner,
        env=env,
        capture_output=True,
        text=True,
    )


def test_dispatcher_accepts_a_rebase_drop_but_dispatches_only_landed_revisions(tmp_path: Path) -> None:
    completed = _run_landed_range_guard(tmp_path, commit_count=3, landed_commit_count=2)

    assert completed.returncode == 0, completed.stderr
    assert "Rebase dropped 1 already-landed revision(s)" in completed.stdout


def test_dispatcher_refuses_an_empty_landed_range(tmp_path: Path) -> None:
    completed = _run_landed_range_guard(tmp_path, commit_count=1, landed_commit_count=0)

    assert completed.returncode != 0
    assert "produced no landed revisions" in completed.stdout


def test_dispatcher_refuses_more_landed_revisions_than_the_merge_event_reports(tmp_path: Path) -> None:
    completed = _run_landed_range_guard(tmp_path, commit_count=1, landed_commit_count=2)

    assert completed.returncode != 0
    assert "exceeding the PR event count" in completed.stdout


def _dispatch_ref_resolution_block() -> str:
    workflow = (WORKFLOWS / "merged-pr-main-releasability.yml").read_text(encoding="utf-8")
    start_marker = '            existing_ref_sha=""\n            if existing_ref_sha='
    end_marker = "            gh workflow run main-releasability.yml"
    start = workflow.index(start_marker)
    end = workflow.index(end_marker, start)
    return textwrap.dedent(workflow[start:end])


def _run_dispatch_ref_resolution(tmp_path: Path, *, lookup_mode: str) -> list[str]:
    shell = shutil.which("sh")
    if shell is None:
        pytest.skip("POSIX shell is required to execute the workflow ref-resolution contract")

    revision = "a" * 40
    call_log = tmp_path / "gh-calls.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh_stub = bin_dir / "gh"
    gh_stub.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        "  *git/ref/tags/*)\n"
        '    if [ "$GH_LOOKUP_MODE" = missing ]; then\n'
        "      printf '%s\\n' '{\"message\":\"Not Found\"}'\n"
        "      exit 1\n"
        "    fi\n"
        f"    printf '%s\\n' '{revision}'\n"
        "    ;;\n"
        "  *git/refs*) printf '%s\\n' create-ref >> \"$GH_CALL_LOG\" ;;\n"
        "  *) exit 97 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    gh_stub.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "GH_CALL_LOG": str(call_log),
            "GH_LOOKUP_MODE": lookup_mode,
            "GITHUB_REPOSITORY": "sgajbi/lotus-performance",
            "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
            "dispatch_ref": f"main-releasability-{revision}",
            "revision": revision,
        }
    )
    subprocess.run(
        [shell, "-eu", "-c", _dispatch_ref_resolution_block()],
        check=True,
        env=env,
        text=True,
    )
    return call_log.read_text(encoding="utf-8").splitlines() if call_log.exists() else []


def test_dispatcher_creates_ref_after_lookup_returns_404_body(tmp_path: Path) -> None:
    assert _run_dispatch_ref_resolution(tmp_path, lookup_mode="missing") == ["create-ref"]


def test_dispatcher_reuses_matching_existing_ref(tmp_path: Path) -> None:
    assert _run_dispatch_ref_resolution(tmp_path, lookup_mode="existing") == []


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
