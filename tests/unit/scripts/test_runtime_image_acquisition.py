from __future__ import annotations

import gzip
import hashlib
import io
import json
import sys
import tarfile
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
    assert not output.exists()
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
    with pytest.raises(ValueError, match="output budget"):
        proof.command([sys.executable, "-c", "print('private-data' * 100)"])
    with pytest.raises(ValueError, match="time/output budget"):
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
