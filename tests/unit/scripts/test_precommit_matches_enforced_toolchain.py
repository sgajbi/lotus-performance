"""pre-commit must run the lint and type-check versions CI enforces.

`requirements*.txt` pins ruff and mypy exactly, but pre-commit does not read
them: each hook resolves its own isolated environment from the `rev:` in
`.pre-commit-config.yaml`. Two independent pins for the same tool drift apart
silently, and nothing in either file mentions the other.

That drift is not cosmetic for a formatter, because the tool's *output* is the
contract rather than its API. Measured on this repository at the moment this
guard was written, on one unchanged tree:

    ruff 0.6.9   (requirements pin, what CI enforces)  665 files already formatted
    ruff 0.15.x  (what `rev:` resolved to)             3 files would be reformatted

So a contributor running `pre-commit` had its `ruff-format` hook rewrite three
files that CI considers correctly formatted already. Both tools gate this
repository and they disagreed about what formatted means.

The failure is worse than an inconvenience: it produces confident, wrong
reports. This drift is what made an earlier commit message here record "three
pre-existing format failures" that did not exist under the enforced pin.

The check compares versions rather than asserting a literal, so bumping the
requirements pin fails here until pre-commit is bumped with it, in the same
change.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

#: Each hook repository and the requirements distribution whose pin it must match.
_PINNED_TOOLCHAIN = {
    "https://github.com/astral-sh/ruff-pre-commit": "ruff",
    "https://github.com/pre-commit/mirrors-mypy": "mypy",
}

_REV_BLOCK = re.compile(r"- repo:\s*(?P<repo>\S+)\s*\n\s*rev:\s*(?P<rev>\S+)")


def _precommit_revisions() -> dict[str, str]:
    config = (REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    return {match["repo"]: match["rev"].lstrip("v") for match in _REV_BLOCK.finditer(config)}


def _requirements_pin(distribution: str) -> str:
    pattern = re.compile(rf"^{re.escape(distribution)}==(?P<version>\S+)\s*$", re.MULTILINE)
    found = {
        match["version"]
        for path in sorted(REPO_ROOT.glob("requirements*.txt"))
        for match in pattern.finditer(path.read_text(encoding="utf-8"))
    }
    assert len(found) == 1, (
        f"{distribution} must be pinned to exactly one version across requirements files; "
        f"found {sorted(found) or 'none'}."
    )
    return found.pop()


@pytest.mark.parametrize(
    ("hook_repository", "distribution"),
    sorted(_PINNED_TOOLCHAIN.items()),
    ids=sorted(_PINNED_TOOLCHAIN.values()),
)
def test_precommit_runs_the_version_ci_enforces(hook_repository: str, distribution: str) -> None:
    revisions = _precommit_revisions()
    assert hook_repository in revisions, (
        f"{hook_repository} is no longer in .pre-commit-config.yaml. If the hook was removed on "
        f"purpose, drop it from _PINNED_TOOLCHAIN in the same change; leaving it here would make "
        f"this guard fail for a reason that no longer exists."
    )

    enforced = _requirements_pin(distribution)
    assert revisions[hook_repository] == enforced, (
        f"pre-commit runs {distribution} {revisions[hook_repository]} while CI enforces "
        f"{enforced}. For a formatter the output is the contract, so two versions gating one "
        f"repository will disagree about what 'formatted' means and each will call the other's "
        f"result a failure. Bump both pins together."
    )
