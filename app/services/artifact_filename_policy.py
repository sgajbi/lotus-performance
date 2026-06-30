from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath


def validate_artifact_filename(filename: str, *, artifact_kind: str = "artifact") -> str:
    candidate = filename.strip()
    if is_unsafe_artifact_filename(candidate):
        raise ValueError(f"Unsafe {artifact_kind} filename: {filename}")
    return candidate


def is_unsafe_artifact_filename(candidate: str) -> bool:
    return any(
        (
            not candidate,
            candidate in {".", ".."},
            _contains_control_character(candidate),
            _is_unsafe_path(candidate, PurePosixPath(candidate)),
            _is_unsafe_path(candidate, PureWindowsPath(candidate)),
        )
    )


def _is_unsafe_path(candidate: str, path: PurePosixPath | PureWindowsPath) -> bool:
    return any(
        (
            path.is_absolute(),
            path.name != candidate,
            any(part == ".." for part in path.parts),
        )
    )


def _contains_control_character(candidate: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in candidate)
