"""Prove selected-base acquisition using central identity and exported config/RootFS bytes."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

if __package__:
    from . import ci_image_bindings_gate as bindings
else:
    import ci_image_bindings_gate as bindings

POLICY_REVISION = "df4da3bda773e9d0103b3a396d58110f49489ebc"
ROOT = Path(__file__).resolve().parents[1]
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024


def command(arguments: list[str], *, timeout: int = 30, artifact: Path | None = None) -> str:
    """Retain no raw subprocess output; bound capture on disk and wall time."""
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        with subprocess.Popen(arguments, cwd=ROOT, stdout=stdout, stderr=stderr) as process:
            deadline = time.monotonic() + timeout
            try:
                while process.poll() is None:
                    if time.monotonic() >= deadline or output_exceeded(stdout, stderr, artifact):
                        raise ValueError("Acquisition command exceeded time/output budget")
                    time.sleep(0.05)
                if process.returncode or output_exceeded(stdout, stderr, artifact):
                    raise ValueError("Required acquisition command failed or exceeded output budget")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
        stdout.seek(0)
        return stdout.read().decode("utf-8")


def output_exceeded(stdout, stderr, artifact: Path | None) -> bool:
    return (
        stdout.tell() > MAX_JSON_BYTES
        or stderr.tell() > MAX_JSON_BYTES
        or (artifact is not None and artifact.exists() and artifact.stat().st_size > MAX_ARCHIVE_BYTES)
    )


def source_identity(expected_source: str, policy_root: Path) -> dict[str, str]:
    if re.fullmatch(r"[0-9a-f]{40}", expected_source) is None:
        raise ValueError("Expected source must be an exact commit SHA")
    actual = command(["git", "rev-parse", "HEAD"]).strip()
    if actual != expected_source:
        raise ValueError("Acquisition source is not the expected clean revision")
    policy = qualified_policy_identity(policy_root)
    status = command(["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"])
    if any(entry not in {"", "?? .image-policy/"} for entry in status.split("\x00")):
        raise ValueError("Acquisition source has tracked or untracked changes")
    return {"commit": actual, "tree": command(["git", "rev-parse", "HEAD^{tree}"]).strip(), **policy}


def qualified_policy_identity(policy_root: Path) -> dict[str, str]:
    expected_root = ROOT.resolve() / ".image-policy"
    if policy_root.resolve() != expected_root or policy_root.is_symlink() or not policy_root.is_dir():
        raise ValueError("Policy checkout must be the exact owned nested path")
    actual_root = command(["git", "-C", str(policy_root), "rev-parse", "--show-toplevel"]).strip()
    policy_sha = command(["git", "-C", str(policy_root), "rev-parse", "HEAD"]).strip()
    policy_dirty = command(["git", "-C", str(policy_root), "status", "--porcelain", "--untracked-files=all"])
    if Path(actual_root).resolve() != expected_root or policy_sha != POLICY_REVISION or policy_dirty:
        raise ValueError("Acquisition policy is not the qualified clean revision")
    module = "automation/validate_technology_governance_policy.py"
    expected_blob = command(["git", "-C", str(policy_root), "rev-parse", "HEAD:" + module]).strip()
    actual_blob = command(["git", "-C", str(policy_root), "hash-object", module]).strip()
    if actual_blob != expected_blob:
        raise ValueError("Qualified policy module differs from its committed blob")
    return {"policy_commit": policy_sha, "policy_module_blob": actual_blob}


def central_admission(policy_root: Path):
    """Use only the reviewed, immutable central implementation; never pick another image."""
    path = policy_root / "automation/validate_technology_governance_policy.py"
    spec = importlib.util.spec_from_file_location("qualified_image_policy", path)
    if spec is None or spec.loader is None:
        raise ValueError("Qualified policy implementation is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True
    spec.loader.exec_module(module)
    policy = module.load_policy()
    errors = module.validate_policy(policy, exception_register_paths=[])
    if errors:
        raise ValueError("Qualified central policy validation failed")
    mapping = module.resolve_distribution(
        policy, bindings.ORIGINAL_RUNTIME_IMAGE, bindings.DEFAULT_RUNTIME_IMAGE, "linux/amd64"
    )
    return module, mapping


def fresh_manifest(module, mapping: dict, runtime_image: str) -> tuple[dict, bytes]:
    """Verify the already selected source through df4's bounded public verifier."""
    manifests = []

    class EvidenceBudget(module._AcquisitionBudget):
        def request(self, url, headers):
            body, response_headers = super().request(url, headers)
            if "/manifests/" in urlsplit(url).path:
                manifests.append(body)
            return body, response_headers

    budget = EvidenceBudget(None)
    if runtime_image == bindings.ORIGINAL_RUNTIME_IMAGE:
        module._verify_original_source(mapping, budget)
    else:
        module._verify_publisher_distribution(mapping, budget)
    if len(manifests) != 1:
        raise ValueError("Expected exactly the qualified child manifest")
    raw = manifests[0]
    if "sha256:" + hashlib.sha256(raw).hexdigest() != mapping["image_digest"]:
        raise ValueError("Fresh manifest bytes do not match admitted digest")
    manifest = json.loads(raw)
    if manifest["config"]["digest"] != mapping["platform_config_digest"]:
        raise ValueError("Fresh manifest config linkage differs from central admission")
    return manifest, raw


def archive_bytes(archive: tarfile.TarFile, name: str) -> bytes:
    member = archive.getmember(name)
    if not member.isfile() or member.size > MAX_JSON_BYTES:
        raise ValueError("Exported metadata must be a bounded regular file")
    stream = archive.extractfile(member)
    if stream is None:
        raise ValueError("Exported metadata is unreadable")
    return stream.read()


def layer_digest(archive: tarfile.TarFile, name: str) -> str:
    member = archive.getmember(name)
    if not member.isfile() or member.size > MAX_ARCHIVE_BYTES:
        raise ValueError("Exported layer must be a bounded regular file")
    stream = archive.extractfile(member)
    if stream is None:
        raise ValueError("Exported layer is unreadable")
    compressed = stream.read(2) == b"\x1f\x8b"
    stream.seek(0)
    content = gzip.GzipFile(fileobj=stream) if compressed else stream
    digest = hashlib.sha256()
    expanded_size = 0
    while chunk := content.read(1024 * 1024):
        expanded_size += len(chunk)
        if expanded_size > MAX_ARCHIVE_BYTES:
            raise ValueError("Exported layer expansion exceeds byte limit")
        digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def verify_export(path: Path, expected_config: str, inspect: dict) -> dict:
    """Docker save exposes config and uncompressed layer tars on both image stores.

    Image.Id is intentionally not treated as config: containerd may expose an index.
    The saved config's actual bytes and RootFS diffs establish that linkage instead.
    """
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("Export exceeds bounded base-image archive limit")
    with tarfile.open(path, "r:") as archive:
        entries = json.loads(archive_bytes(archive, "manifest.json"))
        if len(entries) != 1:
            raise ValueError("Export must contain exactly one platform image")
        entry = entries[0]
        raw_config = archive_bytes(archive, entry["Config"])
        if "sha256:" + hashlib.sha256(raw_config).hexdigest() != expected_config:
            raise ValueError("Exported config bytes do not match admitted config descriptor")
        config = json.loads(raw_config)
        verify_config_platform(config)
        actual = verify_exported_layers(archive, entry, config, inspect)
    return {
        "config_digest": expected_config,
        "platform": "linux/amd64",
        "rootfs_diff_ids": actual,
        "python_version_from_verified_config": config_python_version(config),
        "python_execution_verified": False,
    }


def verify_config_platform(config: dict) -> None:
    if (config.get("os"), config.get("architecture")) != ("linux", "amd64"):
        raise ValueError("Exported config is not linux/amd64")
    if config.get("rootfs", {}).get("type") != "layers":
        raise ValueError("Exported config does not describe layered RootFS")


def verify_exported_layers(archive: tarfile.TarFile, entry: dict, config: dict, inspect: dict) -> list[str]:
    diff_ids = config["rootfs"]["diff_ids"]
    layers = entry["Layers"]
    if not layers or len(layers) != len(diff_ids):
        raise ValueError("Exported layers do not cover config RootFS")
    actual = [layer_digest(archive, name) for name in layers]
    if actual != diff_ids or actual != inspect.get("RootFS", {}).get("Layers"):
        raise ValueError("Exported layer bytes differ from config/inspect RootFS")
    return actual


def config_python_version(config: dict) -> str:
    versions = [
        value.removeprefix("PYTHON_VERSION=")
        for value in config["config"]["Env"]
        if value.startswith("PYTHON_VERSION=")
    ]
    if len(versions) != 1 or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", versions[0]) is None:
        raise ValueError("Admitted config lacks an unambiguous Python runtime version")
    return versions[0]


def acquire(runtime_image: str, expected_source: str, policy_root: Path, output: Path) -> dict:
    bindings.verify_runtime_build_files(runtime_image)
    if output.exists():
        raise ValueError("Fresh acquisition requires an unused evidence directory")
    source = source_identity(expected_source, policy_root)
    module, mapping = central_admission(policy_root)
    manifest, raw_manifest = fresh_manifest(module, mapping, runtime_image)
    preexisting = cache_digest_present(mapping["image_digest"])
    exported = pull_and_verify_export(runtime_image, mapping["platform_config_digest"])
    if len(manifest["layers"]) != len(exported["rootfs_diff_ids"]):
        raise ValueError("Acquired RootFS count differs from fresh manifest layers")
    evidence = acquisition_evidence(runtime_image, source, mapping, manifest, preexisting, exported)
    output.mkdir(parents=True, exist_ok=True)
    (output / "manifest.json").write_bytes(raw_manifest)
    (output / "acquisition.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    return evidence


def cache_digest_present(image_digest: str) -> bool:
    # Enumerate successfully before pulling: an inspect error cannot masquerade as cold.
    cached = command(
        ["docker", "--context", "default", "image", "ls", "--no-trunc", "--digests", "--format", "{{json .}}"]
    )
    rows = [json.loads(line) for line in cached.splitlines() if line]
    return any(row.get("Digest") == image_digest for row in rows)


def pull_and_verify_export(runtime_image: str, config_digest: str) -> dict:
    command(["docker", "--context", "default", "pull", "--platform", "linux/amd64", runtime_image], timeout=180)
    inspected = json.loads(command(["docker", "--context", "default", "image", "inspect", runtime_image]))
    if len(inspected) != 1:
        raise ValueError("Inspect must resolve exactly one selected image")
    inspect = inspected[0]
    if not selected_repo_digest_present(runtime_image, inspect.get("RepoDigests", [])):
        raise ValueError("Pulled image is missing the selected repository digest")
    if (inspect.get("Os"), inspect.get("Architecture")) != ("linux", "amd64"):
        raise ValueError("Pulled image platform differs from admission")
    with tempfile.TemporaryDirectory(prefix="lotus-base-export-") as temporary:
        archive = Path(temporary) / "image.tar"
        command(
            [
                "docker",
                "--context",
                "default",
                "image",
                "save",
                "--platform",
                "linux/amd64",
                "--output",
                str(archive),
                runtime_image,
            ],
            timeout=180,
            artifact=archive,
        )
        return verify_export(archive, config_digest, inspect)


def selected_repo_digest_present(runtime_image: str, repo_digests: list[str]) -> bool:
    # Docker commonly abbreviates docker.io/library/python as python in RepoDigests.
    # These are metadata spellings of this one official repository, not pull choices.
    accepted = {runtime_image}
    if runtime_image == bindings.ORIGINAL_RUNTIME_IMAGE:
        accepted.update({f"python@{bindings.RUNTIME_DIGEST}", f"library/python@{bindings.RUNTIME_DIGEST}"})
    return bool(accepted.intersection(repo_digests))


def acquisition_evidence(runtime_image, source, mapping, manifest, preexisting, exported) -> dict:
    return {
        "schema_version": 1,
        "proof_type": "selected-python-base-acquisition",
        "repository": "lotus-performance",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "selected_image": runtime_image,
        "source": source,
        "manifest_digest": mapping["image_digest"],
        "manifest_config_descriptor": manifest["config"]["digest"],
        "distribution_layer_descriptors": [layer["digest"] for layer in manifest["layers"]],
        "cache_selected_digest_present_before_pull": preexisting,
        "cold_acquisition_proven": False,
        "cache_limit": "Digest inventory cannot prove absence of shared config/layers; no cold claim",
        "pull_attempts": 1,
        **exported,
        "non_proof": [
            "compressed transfer bytes",
            "application build",
            "security scan",
            "PostgreSQL readiness",
            "behavioral recovery",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-image", required=True)
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--policy-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        acquire(args.runtime_image, args.expected_source, args.policy_root.resolve(), args.output)
    except (
        ValueError,
        OSError,
        KeyError,
        TypeError,
        AttributeError,
        IndexError,
        EOFError,
        tarfile.TarError,
        subprocess.SubprocessError,
    ):
        print("Selected runtime acquisition refused; no successful proof was written", file=sys.stderr)
        return 1
    print("Selected runtime config and exported RootFS acquisition verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
