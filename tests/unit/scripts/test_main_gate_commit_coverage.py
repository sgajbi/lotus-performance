from __future__ import annotations

import argparse
from pathlib import Path

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
    assert '"${#revisions[@]}" -ne "$COMMIT_COUNT"' in workflow
    assert '"$merge_methods" != "false,false,true"' in workflow
    assert 'for revision in "${revisions[@]}"; do' in workflow
    assert '-f expected_sha="$revision"' in workflow
    guard = 'if ! git merge-base --is-ancestor "$revision" HEAD; then'
    assert workflow.index(guard) < workflow.index('dispatch_ref="main-releasability-${revision}"')


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
