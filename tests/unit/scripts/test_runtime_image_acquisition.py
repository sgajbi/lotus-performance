from __future__ import annotations

import gzip
import hashlib
import io
import json
import subprocess
import sys
import tarfile
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import verify_runtime_image_acquisition as proof


def digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def exported_image(path, *, platform="amd64", config_override=None, layer_override=None, engine="classic"):
    layer = b"exported-uncompressed-layer-bytes"
    config = {
        "os": "linux",
        "architecture": platform,
        "rootfs": {"type": "layers", "diff_ids": [digest(layer)]},
        "config": {"Env": ["PYTHON_VERSION=3.11.17", "DO_NOT_EXPORT=sensitive"]},
    }
    raw = json.dumps(config).encode()
    config_name = "config.json" if engine == "classic" else "blobs/sha256/" + digest(raw).split(":")[1]
    layer_name = "layer.tar" if engine == "classic" else "blobs/sha256/" + digest(layer).split(":")[1]
    entries = [{"Config": config_name, "Layers": [layer_name]}]
    with tarfile.open(path, "w") as archive:
        for name, body in {
            "manifest.json": json.dumps(entries).encode(),
            config_name: config_override or raw,
            layer_name: layer_override or (gzip.compress(layer) if engine == "containerd" else layer),
        }.items():
            info = tarfile.TarInfo(name)
            info.size = len(body)
            archive.addfile(info, io.BytesIO(body))
    inspect = {
        "RootFS": {"Layers": [digest(layer)]},
        "Os": "linux",
        "Architecture": platform,
        "RepoDigests": [proof.bindings.ORIGINAL_RUNTIME_IMAGE],
    }
    return digest(raw), inspect


@pytest.mark.parametrize("engine", ["classic", "containerd"])
def test_export_validates_config_bytes_and_rootfs_independently_of_engine_id(tmp_path, engine):
    path = tmp_path / "image.tar"
    config, inspect = exported_image(path, engine=engine)
    inspect["Id"] = config if engine == "classic" else digest(b"index identity")
    result = proof.verify_export(path, config, inspect)
    assert result["config_digest"] == config
    assert result["python_version_from_verified_config"] == "3.11.17"
    assert result["python_execution_verified"] is False
    assert "DO_NOT_EXPORT" not in json.dumps(result)


@pytest.mark.parametrize("damage", ["index-as-config", "layer", "platform", "inspect-rootfs", "descriptor"])
def test_export_refuses_false_config_platform_and_layer_identity(tmp_path, damage):
    path = tmp_path / "image.tar"
    kwargs = {}
    if damage == "index-as-config":
        kwargs["config_override"] = b'{"schemaVersion":2,"manifests":[]}'
    if damage == "layer":
        kwargs["layer_override"] = b"different downloaded layer"
    if damage == "platform":
        kwargs["platform"] = "arm64"
    config, inspect = exported_image(path, **kwargs)
    if damage == "descriptor":
        config = digest(b"wrong config")
    if damage == "inspect-rootfs":
        inspect["RootFS"]["Layers"] = [digest(b"wrong rootfs")]
    with pytest.raises(ValueError):
        proof.verify_export(path, config, inspect)


@pytest.fixture
def acquisition(tmp_path, monkeypatch):
    path = tmp_path / "fixture.tar"
    config, inspect = exported_image(path)
    manifest = {"config": {"digest": config}, "layers": [{"digest": digest(b"compressed layer descriptor")}]}
    source = {"commit": "a" * 40, "tree": "b" * 40, "policy_commit": proof.POLICY_REVISION}
    mapping = {"platform_config_digest": config, "image_digest": proof.bindings.RUNTIME_DIGEST}
    monkeypatch.setattr(proof, "source_identity", lambda *_args: source)
    monkeypatch.setattr(proof, "central_admission", lambda *_args: (None, mapping))
    monkeypatch.setattr(proof, "fresh_manifest", lambda *_args: (manifest, json.dumps(manifest).encode()))
    calls = []

    def command(argv, **kwargs):
        calls.append((argv, kwargs))
        if "ls" in argv:
            return ""
        if "inspect" in argv:
            return json.dumps([inspect])
        if "save" in argv:
            Path(argv[argv.index("--output") + 1]).write_bytes(path.read_bytes())
        return ""

    monkeypatch.setattr(proof, "command", command)
    return tmp_path, inspect, calls


def test_actual_pull_export_sequence_retains_only_source_safe_evidence(acquisition):
    tmp_path, _, calls = acquisition
    output = tmp_path / "proof"
    result = proof.acquire(proof.bindings.ORIGINAL_RUNTIME_IMAGE, "a" * 40, tmp_path, output)
    assert sum("pull" in argv for argv, _ in calls) == 1
    assert [next(word for word in ("ls", "pull", "inspect", "save") if word in argv) for argv, _ in calls] == [
        "ls",
        "pull",
        "inspect",
        "save",
    ]
    assert all(argv[:3] == ["docker", "--context", "default"] for argv, _ in calls)
    assert result["cold_acquisition_proven"] is False
    assert result["cache_selected_digest_present_before_pull"] is False
    assert result["source"]["commit"] == "a" * 40
    evidence = (output / "acquisition.json").read_text()
    assert "DO_NOT_EXPORT" not in evidence and "sensitive" not in evidence
    assert json.loads(evidence) == result
    assert json.loads((output / "manifest.json").read_bytes())["config"]["digest"] == result["config_digest"]
    assert not (output / "failure.json").exists()


@pytest.mark.parametrize("damage", ["wrong-repo-digest", "wrong-platform", "cache-failure", "pull-failure"])
def test_failed_actual_acquisition_produces_no_success_artifact(acquisition, monkeypatch, damage):
    tmp_path, inspect, calls = acquisition
    original_command = proof.command
    if damage == "wrong-repo-digest":
        inspect["RepoDigests"] = []
    if damage == "wrong-platform":
        inspect["Architecture"] = "arm64"

    def fail(argv, **kwargs):
        if (damage == "cache-failure" and "ls" in argv) or (damage == "pull-failure" and "pull" in argv):
            raise ValueError("required command failed")
        return original_command(argv, **kwargs)

    monkeypatch.setattr(proof, "command", fail)
    output = tmp_path / "proof"
    with pytest.raises(ValueError):
        proof.acquire(proof.bindings.ORIGINAL_RUNTIME_IMAGE, "a" * 40, tmp_path, output)
    failure = json.loads((output / "failure.json").read_text())
    assert failure["phase"] == (
        "cache-inventory"
        if damage == "cache-failure"
        else "selected-pull"
        if damage == "pull-failure"
        else "selected-inspect"
    )
    assert failure["successful_acquisition_proven"] is False
    assert not (output / "acquisition.json").exists()
    assert sum("pull" in argv for argv, _ in calls) <= 1


@pytest.mark.parametrize("damage", ["selection", "source", "policy", "manifest", "stale-output"])
def test_untrusted_inputs_and_provenance_refuse_before_docker(acquisition, monkeypatch, damage):
    tmp_path, _, calls = acquisition
    runtime = proof.bindings.ORIGINAL_RUNTIME_IMAGE
    output = tmp_path / "proof"
    if damage == "selection":
        runtime = runtime.replace("docker.io", "unapproved.example")
    elif damage == "stale-output":
        output.mkdir()
    else:
        name = {"source": "source_identity", "policy": "central_admission", "manifest": "fresh_manifest"}[damage]
        monkeypatch.setattr(proof, name, lambda *_args: (_ for _ in ()).throw(ValueError("untrusted input")))
    with pytest.raises(ValueError):
        proof.acquire(runtime, "a" * 40, tmp_path, output)
    assert calls == []


@pytest.mark.parametrize("damage", ["source", "dirty", "policy", "policy-dirty", "malformed-source"])
def test_source_verification_requires_exact_clean_source_and_qualified_policy(exact_source, damage):
    policy, state, calls = exact_source
    key = {
        "source": "source_head",
        "dirty": "source_status",
        "policy": "policy_head",
        "policy-dirty": "policy_status",
    }.get(damage)
    if key is not None:
        state[key] = "untrusted"
    with pytest.raises(ValueError):
        proof.source_identity("bad" if damage == "malformed-source" else "a" * 40, policy)
    assert all(argv[0] == "git" for argv in calls)


@pytest.mark.parametrize("runtime", [proof.bindings.DEFAULT_RUNTIME_IMAGE, proof.bindings.ORIGINAL_RUNTIME_IMAGE])
def test_fresh_verification_uses_only_selected_central_verifier(runtime):
    raw = json.dumps({"config": {"digest": digest(b"config")}, "layers": [{"digest": digest(b"layer")}]}).encode()
    calls = []

    class Budget:
        def __init__(self, _):
            pass

        def request(self, url, headers):
            return raw, {}

    def verify(mapping, budget):
        calls.append(runtime)
        budget.request("https://admitted/v2/library/python/manifests/sha256:fixed", {})

    module = SimpleNamespace(
        _AcquisitionBudget=Budget, _verify_original_source=verify, _verify_publisher_distribution=verify
    )
    manifest, observed = proof.fresh_manifest(
        module, {"image_digest": digest(raw), "platform_config_digest": digest(b"config")}, runtime
    )
    assert observed == raw and manifest["config"]["digest"] == digest(b"config")
    assert calls == [runtime]


@pytest.mark.parametrize("damage", ["manifest-digest", "config-descriptor"])
def test_fresh_manifest_identity_refuses_before_acquisition_io(damage):
    raw = json.dumps({"config": {"digest": digest(b"config")}, "layers": [{}]}).encode()

    class Budget:
        def __init__(self, _):
            pass

        def request(self, url, headers):
            return raw, {}

    def verify(mapping, budget):
        budget.request("https://admitted/v2/python/manifests/fixed", {})

    module = SimpleNamespace(_AcquisitionBudget=Budget, _verify_publisher_distribution=verify)
    mapping = {"image_digest": digest(raw), "platform_config_digest": digest(b"config")}
    mapping["image_digest" if damage == "manifest-digest" else "platform_config_digest"] = digest(b"wrong")
    with pytest.raises(ValueError):
        proof.fresh_manifest(module, mapping, proof.bindings.DEFAULT_RUNTIME_IMAGE)


def test_command_limits_output_and_time_without_echoing_raw_data(monkeypatch):
    monkeypatch.setattr(proof, "MAX_JSON_BYTES", 32)
    with pytest.raises(proof.AcquisitionCommandError, match="output-budget-exceeded"):
        proof.command([sys.executable, "-c", "print('private-data' * 100)"])
    with pytest.raises(proof.AcquisitionCommandError, match="time-budget-exceeded"):
        proof.command([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0)


@pytest.mark.parametrize("name", ["docker.io/library/python", "library/python", "python"])
def test_original_repo_digest_accepts_only_docker_official_metadata_spellings(name):
    assert proof.selected_repo_digest_present(
        proof.bindings.ORIGINAL_RUNTIME_IMAGE, [name + "@" + proof.bindings.RUNTIME_DIGEST]
    )


@pytest.mark.parametrize("name", ["unapproved.example/python", "docker.io/other/python", "python-extra"])
def test_repo_digest_does_not_accept_an_unrelated_repository_with_matching_content(name):
    assert not proof.selected_repo_digest_present(
        proof.bindings.ORIGINAL_RUNTIME_IMAGE, [name + "@" + proof.bindings.RUNTIME_DIGEST]
    )


@pytest.fixture
def exact_source(tmp_path, monkeypatch):
    monkeypatch.setattr(proof, "ROOT", tmp_path)
    policy = tmp_path / ".image-policy"
    policy.mkdir()
    state = {
        "source_head": "a" * 40,
        "source_status": "?? .image-policy/\x00",
        "policy_status": "",
        "policy_head": proof.POLICY_REVISION,
        "policy_top": str(policy.resolve()),
        "module_blob": "c" * 40,
    }
    calls = []

    def command(argv, **kwargs):
        calls.append(argv)
        if "-C" in argv:
            if "--show-toplevel" in argv:
                return state["policy_top"]
            if "status" in argv:
                return state["policy_status"]
            if "hash-object" in argv:
                return state["module_blob"]
            if any(value.startswith("HEAD:") for value in argv):
                return "c" * 40
            return state["policy_head"]
        if "status" in argv:
            return "" if "--untracked-files=no" in argv else state["source_status"]
        return "b" * 40 if "HEAD^{tree}" in argv else state["source_head"]

    monkeypatch.setattr(proof, "command", command)
    return policy, state, calls


def test_exact_source_accepts_only_qualified_nested_policy_as_untracked(exact_source):
    policy, _, calls = exact_source
    result = proof.source_identity("a" * 40, policy)
    assert result["commit"] == "a" * 40
    assert all(argv[0] == "git" for argv in calls)


@pytest.mark.parametrize(
    "damage",
    [
        "untracked-source",
        "policy-prefix-lookalike",
        "policy-root-lookalike",
        "dirty-policy",
        "wrong-policy",
        "wrong-policy-root",
        "modified-policy-module",
    ],
)
def test_exact_source_refuses_untracked_pollution_and_untrusted_policy(exact_source, damage):
    policy, state, calls = exact_source
    if damage == "untracked-source":
        state["source_status"] += "?? app/untracked_import.py\x00"
    elif damage == "policy-prefix-lookalike":
        state["source_status"] += "?? .image-policy-evil/\x00"
    elif damage == "policy-root-lookalike":
        policy = policy.with_name(".image-policy-evil")
        policy.mkdir()
    elif damage == "dirty-policy":
        state["policy_status"] = " M automation/validate_technology_governance_policy.py"
    elif damage == "wrong-policy":
        state["policy_head"] = "d" * 40
    elif damage == "wrong-policy-root":
        state["policy_top"] = str(policy.parent)
    else:
        state["module_blob"] = "e" * 40
    with pytest.raises(ValueError):
        proof.source_identity("a" * 40, policy)
    assert all(argv[0] == "git" for argv in calls)


def test_export_archive_ceiling_uses_small_fixture(tmp_path, monkeypatch):
    path = tmp_path / "image.tar"
    config, inspect = exported_image(path)
    monkeypatch.setattr(proof, "MAX_ARCHIVE_BYTES", path.stat().st_size - 1)
    with pytest.raises(ValueError, match="archive limit"):
        proof.verify_export(path, config, inspect)


@pytest.mark.parametrize(
    "kind", ["metadata-size", "layer-size", "expanded-gzip", "malformed-gzip", "metadata-link", "layer-link"]
)
def test_archive_member_and_expansion_guards_with_bounded_fixtures(tmp_path, monkeypatch, kind):
    path = tmp_path / "small.tar"
    body = gzip.compress(b"a" * 4096) if kind == "expanded-gzip" else b"a" * 64
    if kind == "malformed-gzip":
        body = b"\x1f\x8btruncated"
    with tarfile.open(path, "w") as archive:
        member = tarfile.TarInfo("member")
        member.size = len(body)
        if kind.endswith("-link"):
            member.type = tarfile.SYMTYPE
            member.linkname = "outside-archive"
            archive.addfile(member)
        else:
            archive.addfile(member, io.BytesIO(body))
    if kind == "metadata-size":
        monkeypatch.setattr(proof, "MAX_JSON_BYTES", 8)
    if kind == "layer-size":
        monkeypatch.setattr(proof, "MAX_ARCHIVE_BYTES", 8)
    if kind == "expanded-gzip":
        monkeypatch.setattr(proof, "MAX_ARCHIVE_BYTES", 128)
    with tarfile.open(path) as archive, pytest.raises((ValueError, OSError, EOFError)):
        operation = proof.archive_bytes if kind.startswith("metadata") else proof.layer_digest
        operation(archive, "member")


@pytest.mark.parametrize(
    ("operation", "phase", "identity_keys"),
    [
        ("bindings", "runtime-bindings", set()),
        ("source_identity", "source-policy-identity", {"selected_image"}),
        ("central_admission", "central-admission", {"selected_image", "source"}),
        ("fresh_manifest", "fresh-manifest", {"selected_image", "source"}),
        ("verify_export", "export-content-verification", {"selected_image", "source"}),
        ("write_success_evidence", "evidence-publication", {"selected_image", "source"}),
    ],
)
def test_refusals_keep_actionable_phase_validated_identity_and_original_error(
    acquisition, monkeypatch, operation, phase, identity_keys
):
    tmp_path, _, _ = acquisition
    output = tmp_path / "proof"
    original = ValueError("Authorization: Bearer secret-marker" * 10000)

    def refuse(*_args):
        raise original

    owner = proof.bindings if operation == "bindings" else proof
    monkeypatch.setattr(owner, "verify_runtime_build_files" if operation == "bindings" else operation, refuse)
    with pytest.raises(ValueError) as raised:
        proof.acquire(proof.bindings.ORIGINAL_RUNTIME_IMAGE, "a" * 40, tmp_path, output)
    assert raised.value is original
    raw = (output / "failure.json").read_bytes()
    failure = json.loads(raw)
    assert failure["phase"] == phase
    assert failure["reason"] == "validation-refused"
    assert failure["error_class"] == "ValueError"
    assert failure["http_status"] is None and failure["command_status"] is None
    assert {key for key in ("selected_image", "source") if key in failure} == identity_keys
    assert len(raw) < 2048
    assert b"secret-marker" not in raw and b"Authorization" not in raw
    assert not (output / "acquisition.json").exists()


@pytest.mark.parametrize(
    ("word", "phase"),
    [
        ("ls", "cache-inventory"),
        ("pull", "selected-pull"),
        ("inspect", "selected-inspect"),
        ("save", "selected-export"),
    ],
)
def test_command_refusals_keep_phase_status_and_native_cli_exit(acquisition, monkeypatch, capsys, word, phase):
    tmp_path, _, _ = acquisition
    original_command = proof.command
    original_error = proof.AcquisitionCommandError("command-failed", 7)

    def command(argv, **kwargs):
        if word in argv:
            raise original_error
        return original_command(argv, **kwargs)

    monkeypatch.setattr(proof, "command", command)
    output = tmp_path / "proof"
    result = proof.main(
        [
            "--runtime-image",
            proof.bindings.ORIGINAL_RUNTIME_IMAGE,
            "--expected-source",
            "a" * 40,
            "--policy-root",
            str(tmp_path),
            "--output",
            str(output),
        ]
    )
    assert result == 1
    failure = json.loads((output / "failure.json").read_text())
    assert failure["phase"] == phase and failure["command_status"] == 7
    assert failure["reason"] == "command-failed"
    assert capsys.readouterr().err == "Selected runtime acquisition refused; no successful proof was written\n"
    assert not (output / "acquisition.json").exists()


@pytest.mark.parametrize("kind", ["directory", "successful-proof", "file", "dangling-symlink"])
def test_existing_evidence_paths_are_untouched_and_never_consumed(acquisition, kind):
    tmp_path, _, calls = acquisition
    output = tmp_path / "proof"
    if kind == "file":
        output.write_bytes(b"existing marker")
    elif kind == "dangling-symlink":
        try:
            output.symlink_to(tmp_path / "absent", target_is_directory=True)
        except OSError:
            pytest.skip("Windows symlink creation requires developer mode or elevation")
    else:
        output.mkdir()
        (output / ("acquisition.json" if kind == "successful-proof" else "marker")).write_bytes(b"existing marker")
    before = list(output.iterdir()) if output.is_dir() else []
    with pytest.raises(ValueError, match="unused evidence directory"):
        proof.acquire(proof.bindings.ORIGINAL_RUNTIME_IMAGE, "a" * 40, tmp_path, output)
    assert calls == []
    if before:
        assert list(output.iterdir()) == before and before[0].read_bytes() == b"existing marker"
    elif kind == "file":
        assert output.read_bytes() == b"existing marker"
    else:
        assert output.is_symlink() and not (tmp_path / "absent").exists()


def test_fresh_manifest_passes_owned_diagnostic_directory_to_central_budget(tmp_path):
    output = tmp_path / "http"
    original = urllib.error.HTTPError(
        "https://admitted/manifest", 503, "private reason", {}, io.BytesIO(b"private body")
    )

    class Budget:
        def __init__(self, evidence_dir):
            assert evidence_dir == output

        def request(self, _url, _headers):
            raise original

    def verify(_mapping, budget):
        budget.request("https://admitted/v2/python/manifests/fixed", {})

    module = SimpleNamespace(_AcquisitionBudget=Budget, _verify_publisher_distribution=verify)
    with pytest.raises(urllib.error.HTTPError) as raised:
        proof.fresh_manifest(module, {}, proof.bindings.DEFAULT_RUNTIME_IMAGE, output)
    assert raised.value is original
    assert proof.failure_details(original) == {
        "reason": "http-refused",
        "error_class": "HTTPError",
        "http_status": 503,
        "command_status": None,
    }


@pytest.mark.parametrize("status", [401, 429, 503, 600, "secret-marker"])
def test_causal_http_status_is_finite_without_copying_exception_or_headers(acquisition, monkeypatch, status):
    tmp_path, _, _ = acquisition
    http = urllib.error.HTTPError(
        "https://private/secret-marker",
        status,
        "secret-marker",
        {"Authorization": "secret-marker"},
        io.BytesIO(b"secret-marker"),
    )

    def refuse(*_args):
        raise ValueError("secret-marker") from http

    monkeypatch.setattr(proof, "fresh_manifest", refuse)
    output = tmp_path / "proof"
    with pytest.raises(ValueError):
        proof.acquire(proof.bindings.ORIGINAL_RUNTIME_IMAGE, "a" * 40, tmp_path, output)
    raw = (output / "failure.json").read_text()
    failure = json.loads(raw)
    assert failure["http_status"] == (status if type(status) is int and 100 <= status <= 599 else None)
    assert "secret-marker" not in raw and "Authorization" not in raw
    assert not (output / "acquisition.json").exists()


def test_real_subprocess_failure_keeps_only_fixed_reason_and_status(tmp_path, capsys):
    with pytest.raises(proof.AcquisitionCommandError) as raised:
        proof.command(
            [
                sys.executable,
                "-c",
                "import sys; print('secret-marker'); print('Authorization: secret-marker', file=sys.stderr); sys.exit(7)",
            ]
        )
    attempt = proof.AcquisitionAttempt(tmp_path, phase="selected-pull")
    attempt.record_failure(raised.value)
    raw = (tmp_path / "failure.json").read_text()
    assert json.loads(raw)["command_status"] == 7
    assert "secret-marker" not in raw and "Authorization" not in raw
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    "error",
    [
        subprocess.CalledProcessError(7, "secret-marker", output="secret-marker", stderr="secret-marker"),
        proof.AcquisitionCommandError("secret-marker", "secret-marker"),
    ],
)
def test_subprocess_and_untrusted_failure_metadata_do_not_escape(error):
    details = proof.failure_details(error)
    assert "secret-marker" not in json.dumps(details)
    assert details["command_status"] is None


def test_failure_writer_does_not_mask_original_error_or_overwrite_existing_diagnostics(acquisition, monkeypatch):
    tmp_path, _, _ = acquisition
    original = ValueError("private failure")

    def refuse(*_args):
        (tmp_path / "proof" / "failure.json").write_bytes(b"existing diagnostic")
        raise original

    monkeypatch.setattr(proof, "fresh_manifest", refuse)
    with pytest.raises(ValueError) as raised:
        proof.acquire(proof.bindings.ORIGINAL_RUNTIME_IMAGE, "a" * 40, tmp_path, tmp_path / "proof")
    assert raised.value is original
    assert (tmp_path / "proof" / "failure.json").read_bytes() == b"existing diagnostic"
    assert not (tmp_path / "proof" / "acquisition.json").exists()


def test_failure_identity_projection_excludes_unknown_and_malformed_source_values():
    source = {
        "commit": "a" * 40,
        "tree": "secret-marker",
        "policy_commit": proof.POLICY_REVISION,
        "policy_module_blob": "secret-marker",
        "Authorization": "secret-marker",
    }
    assert proof.validated_source_identity(source) == {"commit": "a" * 40, "policy_commit": proof.POLICY_REVISION}


@pytest.mark.parametrize("existing", [False, True])
def test_success_evidence_publication_is_complete_exclusive_and_cleans_pending_files(tmp_path, existing):
    path = tmp_path / "acquisition.json"
    if existing:
        path.write_bytes(b"existing successful proof")
        with pytest.raises(FileExistsError):
            proof.write_success_evidence(path, {"validated": True})
        assert path.read_bytes() == b"existing successful proof"
    else:
        proof.write_success_evidence(path, {"validated": True})
        assert json.loads(path.read_text()) == {"validated": True}
    assert list(tmp_path.iterdir()) == [path]


def test_publication_failure_preserves_native_refusal_and_never_exposes_success(acquisition, monkeypatch):
    tmp_path, _, _ = acquisition
    original = OSError("secret-marker")

    def refuse(*_args):
        raise original

    monkeypatch.setattr(proof.os, "link", refuse)
    output = tmp_path / "proof"
    with pytest.raises(OSError) as raised:
        proof.acquire(proof.bindings.ORIGINAL_RUNTIME_IMAGE, "a" * 40, tmp_path, output)
    assert raised.value is original
    assert {path.name for path in output.iterdir()} == {"manifest.json", "failure.json"}
    failure = json.loads((output / "failure.json").read_text())
    assert failure["phase"] == "evidence-publication" and failure["reason"] == "io-refused"
    assert "secret-marker" not in json.dumps(failure)
