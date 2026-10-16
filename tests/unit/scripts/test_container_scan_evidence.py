"""Exercise native producer failures without Docker, a scanner or network access."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from scripts import container_scan_evidence as evidence

SOURCE = "a" * 40
RUN_ID = "12345"
SCANNER = "scanner@sha256:" + "b" * 64
METADATA = {
    "Version": 2,
    "UpdatedAt": "2026-10-16T01:13:54Z",
    "NextUpdate": "2026-10-17T01:13:54Z",
    "DownloadedAt": "2026-10-16T07:00:00Z",
}


def _report() -> dict:
    return {
        "Trivy": {"Version": "0.71.2"},
        "ArtifactID": "sha256:" + "c" * 64,
        "Metadata": {
            "ImageID": "sha256:" + "d" * 64,
            "ImageConfig": {
                "os": "linux",
                "architecture": "amd64",
                "config": {"Labels": {"org.opencontainers.image.revision": SOURCE, "lotus.ci.pipeline_run_id": RUN_ID}},
            },
        },
        "Results": [{"Vulnerabilities": [{"VulnerabilityID": "CVE-example", "Severity": "HIGH"}]}],
    }


class FakeTrivy:
    def __init__(self, output: Path, fault: str = "") -> None:
        self.output = output
        self.fault = fault
        self.commands: list[list[str]] = []
        self.cache = output

    def __call__(self, command: list[str], *, check: bool) -> subprocess.CompletedProcess:
        assert check is False
        self.commands.append(command)
        self.cache = Path(next(arg.removesuffix(":/cache") for arg in command if arg.endswith(":/cache")))
        if "--download-db-only" in command:
            self._download()
            return subprocess.CompletedProcess(command, 17 if self.fault == "download_exit" else 0)
        self._analysis()
        return subprocess.CompletedProcess(command, 19 if self.fault == "analysis_exit" else 0)

    def _download(self) -> None:
        directory = self.cache / "db"
        directory.mkdir()
        if self.fault != "missing_db":
            (directory / "trivy.db").write_bytes(b"" if self.fault == "empty_db" else b"actual synthetic DB bytes")
        metadata = dict(METADATA)
        if self.fault == "schema":
            metadata["Version"] = 3
        if self.fault == "missing_date":
            del metadata["DownloadedAt"]
        if self.fault == "bad_date":
            metadata["UpdatedAt"] = "not-a-date"
        if self.fault == "naive_date":
            metadata["UpdatedAt"] = "2026-10-16T01:13:54"
        if self.fault != "missing_metadata":
            (directory / "metadata.json").write_text(
                "invalid-json" if self.fault == "malformed_metadata" else json.dumps(metadata), encoding="utf-8"
            )

    def _analysis(self) -> None:
        report = _report()
        config = report["Metadata"]["ImageConfig"]
        if self.fault == "source":
            config["config"]["Labels"]["org.opencontainers.image.revision"] = "stale-source"
        if self.fault == "run":
            config["config"]["Labels"]["lotus.ci.pipeline_run_id"] = "stale-run"
        if self.fault == "platform":
            config["architecture"] = "arm64"
        if self.fault == "image":
            report["Metadata"]["ImageID"] = "mutable-tag"
        if self.fault == "version":
            report["Trivy"]["Version"] = "other"
        if self.fault == "results":
            del report["Results"]
        if self.fault == "db_changed":
            (self.cache / "db" / "trivy.db").write_bytes(b"different DB")
        if self.fault == "metadata_changed":
            (self.cache / "db" / "metadata.json").write_text(
                json.dumps({**METADATA, "DownloadedAt": "2026-10-16T08:00:00Z"})
            )
        if self.fault != "missing_report":
            (self.output / evidence.REPORT_NAME).write_text(
                "invalid-json" if self.fault == "malformed_report" else json.dumps(report), encoding="utf-8"
            )


def _produce(output: Path) -> dict:
    return evidence.produce(
        image="image:ci", scanner=SCANNER, severity="HIGH,CRITICAL", output=output, source=SOURCE, run_id=RUN_ID
    )


def test_one_analysis_is_bound_to_the_actual_unchanged_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeTrivy(tmp_path)
    monkeypatch.setattr(evidence.subprocess, "run", fake)
    result = _produce(tmp_path)
    assert result["status"] == "complete" and result["analysis_count"] == 1
    assert result["acceptance_verdict"] == "not-evaluated"
    assert result["database_binary_archived"] is False
    assert result["database_before"] == result["database_after"]
    assert result["database_before"]["binary_sha256"] == hashlib.sha256(b"actual synthetic DB bytes").hexdigest()
    assert (tmp_path / evidence.DB_METADATA_NAME).read_bytes() == (fake.cache / "db" / "metadata.json").read_bytes()
    assert result["report_sha256"] == hashlib.sha256((tmp_path / evidence.REPORT_NAME).read_bytes()).hexdigest()
    assert result["identity"]["source"] == SOURCE and result["identity"]["pipeline_run_id"] == RUN_ID
    assert len(fake.commands) == 2
    download, analysis = fake.commands
    assert "--download-db-only" in download and "--scanners" not in download
    assert "/var/run/docker.sock:/var/run/docker.sock" not in download
    assert "--skip-db-update" in analysis and "--download-db-only" not in analysis
    assert analysis[analysis.index("--scanners") + 1] == "vuln"
    assert analysis[analysis.index("--severity") + 1] == "HIGH,CRITICAL"
    assert analysis[analysis.index("--output") + 1] == f"/output/{evidence.REPORT_NAME}"
    assert f"{(fake.cache / 'db').as_posix()}:/cache/db:ro" in analysis
    assert not {"--ignore-unfixed", "--ignore-status", "--ignorefile", "--ignore-policy", "--vex", "-e", "--env"} & set(
        analysis
    )
    assert [operation["native_exit"] for operation in result["operations"]] == [0, 0]


@pytest.mark.parametrize(
    "fault",
    [
        "missing_db",
        "empty_db",
        "missing_metadata",
        "malformed_metadata",
        "schema",
        "missing_date",
        "bad_date",
        "naive_date",
        "download_exit",
    ],
)
def test_invalid_database_or_failed_acquisition_stops_before_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    fake = FakeTrivy(tmp_path, fault)
    monkeypatch.setattr(evidence.subprocess, "run", fake)
    with pytest.raises(ValueError, match="container evidence failed"):
        _produce(tmp_path)
    assert len(fake.commands) == 1
    proof = json.loads((tmp_path / evidence.PROVENANCE_NAME).read_bytes())
    assert proof["status"] == "failed" and "analysis_count" not in proof


@pytest.mark.parametrize(
    "fault",
    [
        "analysis_exit",
        "db_changed",
        "metadata_changed",
        "source",
        "run",
        "platform",
        "image",
        "version",
        "results",
        "missing_report",
        "malformed_report",
    ],
)
def test_failed_analysis_or_changed_inputs_cannot_produce_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    fake = FakeTrivy(tmp_path, fault)
    monkeypatch.setattr(evidence.subprocess, "run", fake)
    with pytest.raises(ValueError, match="container evidence failed"):
        _produce(tmp_path)
    proof = json.loads((tmp_path / evidence.PROVENANCE_NAME).read_bytes())
    assert proof["status"] == "failed" and "acceptance_verdict" not in proof
    assert len(fake.commands) == 2


def test_fresh_cache_and_failure_invalidate_only_fixed_old_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = FakeTrivy(tmp_path)
    monkeypatch.setattr(evidence.subprocess, "run", first)
    _produce(tmp_path)
    foreign = tmp_path / "foreign.txt"
    foreign.write_text("preserve", encoding="utf-8")
    second = FakeTrivy(tmp_path, "download_exit")
    monkeypatch.setattr(evidence.subprocess, "run", second)
    with pytest.raises(ValueError):
        _produce(tmp_path)
    assert first.cache != second.cache
    assert not (tmp_path / evidence.REPORT_NAME).exists()
    assert not (tmp_path / evidence.DB_METADATA_NAME).exists()
    assert json.loads((tmp_path / evidence.PROVENANCE_NAME).read_bytes())["status"] == "failed"
    assert foreign.read_text(encoding="utf-8") == "preserve"


def test_cli_returns_nonzero_for_a_native_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(evidence.subprocess, "run", FakeTrivy(tmp_path, "analysis_exit"))
    monkeypatch.setattr(
        "sys.argv",
        [
            "producer",
            "--image",
            "image:ci",
            "--scanner",
            SCANNER,
            "--output-dir",
            str(tmp_path),
            "--source",
            SOURCE,
            "--run-id",
            RUN_ID,
        ],
    )
    assert evidence.main() == 1
