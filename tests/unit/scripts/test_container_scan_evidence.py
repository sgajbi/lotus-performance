"""Exercise native producer failures without Docker, a scanner or network access."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

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
        self.metadata_bytes: bytes | None = None

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
            self.metadata_bytes = (directory / "metadata.json").read_bytes()

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


def _linux_caller(monkeypatch: pytest.MonkeyPatch, uid: int = 1000, gid: int = 1000) -> None:
    monkeypatch.setattr(evidence, "os", os, raising=False)
    monkeypatch.setattr(evidence.sys, "platform", "linux")
    monkeypatch.setattr(evidence.os, "geteuid", lambda: uid, raising=False)
    monkeypatch.setattr(evidence.os, "getegid", lambda: gid, raising=False)
    monkeypatch.setattr(
        evidence,
        "DOCKER_SOCKET",
        SimpleNamespace(stat=lambda: SimpleNamespace(st_mode=stat.S_IFSOCK | 0o660, st_gid=998)),
        raising=False,
    )


@pytest.fixture(autouse=True)
def _synthetic_linux_host(monkeypatch: pytest.MonkeyPatch) -> None:
    # Keep the entire failure matrix independent of a real host Docker socket.
    _linux_caller(monkeypatch)


@pytest.mark.parametrize("uid,gid", [(0, 0), (1000, 2000)])
@pytest.mark.parametrize("fault", ["", "download_exit", "analysis_exit"])
def test_linux_scanner_writes_as_the_cleanup_caller_and_keeps_socket_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uid: int, gid: int, fault: str
) -> None:
    _linux_caller(monkeypatch, uid, gid)
    fake = FakeTrivy(tmp_path, fault)
    monkeypatch.setattr(evidence.subprocess, "run", fake)
    if fault:
        with pytest.raises(ValueError, match="container evidence failed"):
            _produce(tmp_path)
        result = json.loads((tmp_path / evidence.PROVENANCE_NAME).read_bytes())
    else:
        result = _produce(tmp_path)
        assert result["analysis_count"] == 1 and result["database_before"] == result["database_after"]
    for command in fake.commands:
        assert command[command.index("--user") + 1] == f"{uid}:{gid}"
        assert command.index("--user") < command.index(SCANNER), "identity is a Docker option"
        if "--download-db-only" in command:
            assert "--group-add" not in command
            assert "/var/run/docker.sock:/var/run/docker.sock" not in command
        else:
            assert command[command.index("--group-add") + 1] == "998"
            assert command.index("--group-add") < command.index(SCANNER)
            assert "/var/run/docker.sock:/var/run/docker.sock" in command
            assert f"{(fake.cache / 'db').as_posix()}:/cache/db:ro" in command
            assert (tmp_path / evidence.DB_METADATA_NAME).read_bytes() == fake.metadata_bytes
            assert (tmp_path / evidence.REPORT_NAME).is_file()
    assert result["cache_cleanup"] == {"status": "complete"} and not fake.cache.exists()


def test_windows_keeps_docker_desktop_identity_without_posix_probes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _linux_caller(monkeypatch)
    monkeypatch.setattr(evidence.sys, "platform", "win32")

    def unsupported_probe() -> int:
        raise AssertionError("Windows must not request Linux identity or socket ownership")

    monkeypatch.setattr(evidence.os, "geteuid", unsupported_probe)
    monkeypatch.setattr(evidence.os, "getegid", unsupported_probe)
    monkeypatch.setattr(evidence, "DOCKER_SOCKET", SimpleNamespace(stat=unsupported_probe), raising=False)
    fake = FakeTrivy(tmp_path)
    monkeypatch.setattr(evidence.subprocess, "run", fake)
    result = _produce(tmp_path)
    assert result["status"] == "complete" and not fake.cache.exists()
    assert len(fake.commands) == 2
    assert all("--user" not in command and "--group-add" not in command for command in fake.commands)
    assert "/var/run/docker.sock:/var/run/docker.sock" in fake.commands[1]


@pytest.mark.parametrize("fault", ["platform", "uid-api", "gid-api", "missing-socket", "denied-socket", "not-socket"])
def test_unsupported_linux_identity_or_socket_refuses_before_scanner_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    _linux_caller(monkeypatch)
    if fault == "platform":
        monkeypatch.setattr(evidence.sys, "platform", "darwin")
    elif fault in {"uid-api", "gid-api"}:
        monkeypatch.delattr(evidence.os, "geteuid" if fault == "uid-api" else "getegid")
    elif fault == "not-socket":
        monkeypatch.setattr(
            evidence, "DOCKER_SOCKET", SimpleNamespace(stat=lambda: SimpleNamespace(st_mode=stat.S_IFREG, st_gid=998))
        )
    else:

        def refuse_socket() -> None:
            raise (
                FileNotFoundError("synthetic socket missing")
                if fault == "missing-socket"
                else PermissionError("synthetic socket inaccessible")
            )

        monkeypatch.setattr(evidence, "DOCKER_SOCKET", SimpleNamespace(stat=refuse_socket))
    fake = FakeTrivy(tmp_path)
    monkeypatch.setattr(evidence.subprocess, "run", fake)
    with pytest.raises(ValueError, match="failed during initializing"):
        _produce(tmp_path)
    proof = json.loads((tmp_path / evidence.PROVENANCE_NAME).read_bytes())
    assert proof["status"] == "failed" and proof["phase"] == "initializing"
    assert proof["cache_cleanup"] == {"status": "complete"}
    assert fake.commands == [] and not list(tmp_path.glob(".trivy-cache-*"))


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
    assert (tmp_path / evidence.DB_METADATA_NAME).read_bytes() == fake.metadata_bytes
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
    assert not fake.cache.exists(), "the invocation-owned database cache must be removed after success"
    assert result["cache_cleanup"] == {"status": "complete"}
    assert json.loads((tmp_path / evidence.PROVENANCE_NAME).read_bytes()) == result


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
    assert not fake.cache.exists(), "acquisition or database validation failure must remove the owned cache"
    assert proof["cache_cleanup"] == {"status": "complete"}


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
    assert not fake.cache.exists(), "analysis or provenance validation failure must remove the owned cache"
    assert proof["cache_cleanup"] == {"status": "complete"}
    assert (tmp_path / evidence.DB_METADATA_NAME).read_bytes() == fake.metadata_bytes
    if fault != "missing_report":
        assert (tmp_path / evidence.REPORT_NAME).is_file()


def test_fresh_cache_and_failure_invalidate_only_fixed_old_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = FakeTrivy(tmp_path)
    monkeypatch.setattr(evidence.subprocess, "run", first)
    _produce(tmp_path)
    foreign = tmp_path / "foreign.txt"
    foreign.write_text("preserve", encoding="utf-8")
    foreign_cache = tmp_path / ".trivy-cache-foreign"
    foreign_cache.mkdir()
    (foreign_cache / "keep").write_bytes(b"other invocation")
    second = FakeTrivy(tmp_path, "download_exit")
    monkeypatch.setattr(evidence.subprocess, "run", second)
    with pytest.raises(ValueError):
        _produce(tmp_path)
    assert first.cache != second.cache
    assert not first.cache.exists() and not second.cache.exists()
    assert (foreign_cache / "keep").read_bytes() == b"other invocation"
    assert not (tmp_path / evidence.REPORT_NAME).exists()
    assert not (tmp_path / evidence.DB_METADATA_NAME).exists()
    assert json.loads((tmp_path / evidence.PROVENANCE_NAME).read_bytes())["status"] == "failed"
    assert foreign.read_text(encoding="utf-8") == "preserve"


def test_failure_before_download_removes_newly_allocated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeTrivy(tmp_path)
    monkeypatch.setattr(evidence.subprocess, "run", fake)
    with pytest.raises(ValueError, match="failed during initializing"):
        evidence.produce(
            image="image:ci", scanner=SCANNER, severity="HIGH,CRITICAL", output=tmp_path, source="", run_id=RUN_ID
        )
    assert fake.commands == []
    assert not list(tmp_path.glob(".trivy-cache-*")), "input validation failure must remove the newly allocated cache"
    proof = json.loads((tmp_path / evidence.PROVENANCE_NAME).read_bytes())
    assert proof["status"] == "failed" and proof["phase"] == "initializing"
    assert proof["cache_cleanup"] == {"status": "complete"}


def test_failed_cache_allocation_records_failure_without_removing_foreign_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    foreign = tmp_path / ".trivy-cache-foreign"
    foreign.mkdir()
    (foreign / "keep").write_bytes(b"other invocation")
    fake = FakeTrivy(tmp_path)
    monkeypatch.setattr(evidence.subprocess, "run", fake)

    def refuse_allocation(**kwargs: object) -> str:
        raise PermissionError("synthetic allocation failure")

    monkeypatch.setattr(evidence.tempfile, "mkdtemp", refuse_allocation)
    with pytest.raises(ValueError, match="failed during initializing") as failure:
        _produce(tmp_path)
    assert isinstance(failure.value.__cause__, PermissionError)
    assert fake.commands == []
    assert (foreign / "keep").read_bytes() == b"other invocation"
    proof = json.loads((tmp_path / evidence.PROVENANCE_NAME).read_bytes())
    assert proof["status"] == "failed" and proof["failure_type"] == "PermissionError"
    assert proof["cache_cleanup"] == {"status": "not-created"}


@pytest.mark.parametrize("fault", ["", "download_exit", "analysis_exit", "source"])
def test_cleanup_failure_is_observable_without_erasing_the_primary_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    fake = FakeTrivy(tmp_path, fault)
    monkeypatch.setattr(evidence.subprocess, "run", fake)

    def refuse_cleanup(cache: Path) -> None:
        assert cache == fake.cache
        raise PermissionError("synthetic cleanup failure")

    monkeypatch.setattr(evidence.shutil, "rmtree", refuse_cleanup)
    with pytest.raises(ValueError, match="container evidence failed") as failure:
        _produce(tmp_path)
    proof = json.loads((tmp_path / evidence.PROVENANCE_NAME).read_bytes())
    assert proof["status"] == "failed"
    assert proof["cache_cleanup"] == {"status": "failed", "failure_type": "PermissionError"}
    assert fake.cache.is_dir()
    expected_phase = {
        "": "cache-cleanup",
        "download_exit": "database-acquisition",
        "analysis_exit": "vulnerability-analysis",
        "source": "provenance-validation",
    }[fault]
    assert proof["phase"] == expected_phase
    assert proof["failure_type"] == ("ValueError" if fault else "PermissionError")
    if fault:
        assert isinstance(failure.value.__cause__, ValueError)
        if fault.endswith("_exit"):
            assert "nonzero native exit" in str(failure.value.__cause__)
    else:
        assert isinstance(failure.value.__cause__, PermissionError)
        assert proof["analysis_count"] == 1 and proof["database_before"] == proof["database_after"]
    if fault != "download_exit":
        assert (tmp_path / evidence.DB_METADATA_NAME).read_bytes() == fake.metadata_bytes
        assert (tmp_path / evidence.REPORT_NAME).is_file()


@pytest.mark.parametrize("cleanup_failure", [False, True])
def test_cli_returns_nonzero_for_a_native_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cleanup_failure: bool
) -> None:
    monkeypatch.setattr(evidence.subprocess, "run", FakeTrivy(tmp_path, "" if cleanup_failure else "analysis_exit"))
    if cleanup_failure:

        def refuse_cleanup(cache: Path) -> None:
            raise PermissionError("synthetic cleanup failure")

        monkeypatch.setattr(evidence.shutil, "rmtree", refuse_cleanup)
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
