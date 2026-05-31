from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath


def is_safe_evidence_file_name(evidence_file_name: str) -> bool:
    return (
        bool(evidence_file_name)
        and PurePosixPath(evidence_file_name).name == evidence_file_name
        and PureWindowsPath(evidence_file_name).name == evidence_file_name
    )


def resolve_evidence_file_path(*, artifact_directory: Path, evidence_file_name: str) -> Path | None:
    if not is_safe_evidence_file_name(evidence_file_name):
        return None
    artifact_root = artifact_directory.resolve()
    evidence_path = (artifact_root / evidence_file_name).resolve()
    if not evidence_path.is_relative_to(artifact_root):
        return None
    return evidence_path
