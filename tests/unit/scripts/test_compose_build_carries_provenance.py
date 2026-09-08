"""#511: the Compose build path states the same commit the Make path does.

`make docker-up` is the documented local bring-up and it is the Compose path. Compose
declared `context` and `target` and no `args:`, so it produced an image reporting the
Dockerfile's `ARG` defaults while `make docker-build` reported the real commit. Two
build paths, one tree, two different answers -- and the failure hides, because
`/version` returns a well-formed object with a plausible value in every field.

Five services build from this file, all `context: .` with `target: runtime`. They are
tested together: five unsynchronised copies of the argument list would be the same
defect as the one being closed, with more places to introduce it.
"""

from __future__ import annotations

import os
import re
import subprocess
from fnmatch import fnmatch
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]

# The build argument as it appears in a `make -n` expansion, up to the line
# continuation. Defined once: written inline it needs a doubled backslash, and a
# single one silently becomes an escaped paren that fails to compile.
_BRANCH_ARGUMENT = "--build-arg APP_GIT_BRANCH=(\\S.*?)(?= \\\\)"

PROVENANCE_ARGS = (
    "APP_VERSION",
    "APP_GIT_COMMIT_SHA",
    "APP_GIT_BRANCH",
    "APP_BUILD_TIMESTAMP",
    "APP_REPOSITORY_URL",
    "APP_IMAGE_DIGEST",
    "APP_CI_PIPELINE_RUN_ID",
)


# Ignored paths that the image is *meant* to contain. Empty today, and deliberately
# present: packaging something git ignores is a decision, and this is where it has to
# be written down rather than left as a gap in `.dockerignore`.
_DELIBERATELY_PACKAGED: frozenset[str] = frozenset()


def _ignore_entries(relative: str) -> set[str]:
    """Pattern lines from a gitignore-style file, normalised for comparison.

    Trailing slashes are dropped because `.gitignore` writes `venv/` where
    `.dockerignore` writes `venv`, and negations are skipped because `!x` is a
    re-inclusion rather than an exclusion.
    """

    lines = (REPO_ROOT / relative).read_text(encoding="utf-8").splitlines()
    return {
        line.strip().rstrip("/")
        for line in lines
        if line.strip() and not line.startswith("#") and not line.startswith("!")
    }


def _compose() -> dict:
    return yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def _make_expansion(target: str, *overrides: str) -> str:
    """What `make` would run, without running it."""

    return subprocess.run(
        ["make", "-n", target, *overrides],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _services_that_build() -> dict[str, dict]:
    return {name: service for name, service in _compose()["services"].items() if isinstance(service.get("build"), dict)}


def test_every_service_built_from_this_file_receives_every_provenance_argument() -> None:
    """Asserted per service, because one service missing them is the whole defect back.

    Resolved through the parsed YAML rather than by grepping for the anchor name, so
    this keeps holding if the anchor is renamed, inlined, or replaced with something
    else that achieves the same thing.
    """

    building = _services_that_build()
    assert len(building) >= 5, f"expected the app services to build; found {sorted(building)}"

    for name, service in building.items():
        args = service["build"].get("args")
        assert args, f"{name} builds without provenance arguments"
        assert set(PROVENANCE_ARGS) <= set(args), f"{name} is missing {set(PROVENANCE_ARGS) - set(args)}"


def test_a_build_outside_a_checkout_still_works_and_still_says_so() -> None:
    """Every argument carries a default, and the default is not a plausible commit.

    A Compose build with nothing exported must not fail; it must produce an image that
    reports it does not know. `local` is the Dockerfile's own default, so the two
    cannot disagree about what an unsupplied build looks like.
    """

    args = next(iter(_services_that_build().values()))["build"]["args"]

    for name in PROVENANCE_ARGS:
        assert re.fullmatch(
            rf"\$\{{{name}:-.+\}}", str(args[name])
        ), f"{name} has no default, so a build outside a checkout would fail or be blank"


def test_both_build_paths_are_driven_from_the_same_values() -> None:
    """`docker-up` must export what `docker-build` passes.

    Two paths that compute provenance independently can state different things about
    one commit, which is exactly what this issue found.
    """

    build = _make_expansion("docker-build")
    up = _make_expansion("docker-up")

    for name in PROVENANCE_ARGS:
        assert f"--build-arg {name}=" in build, f"docker-build omits {name}"
        assert f"{name}=" in up, f"docker-up does not export {name}"


def test_a_supplied_commit_wins_over_the_locally_derived_one() -> None:
    """CI passes `github.sha` in the environment and must keep winning.

    The variables are now derived from git so a local build says something true, and
    that derivation must not displace the value CI supplies -- `?=` leaves an
    already-defined variable alone, but `=` or `:=` would silently overwrite it and
    every released image would then carry the builder's local state instead of the
    commit under release. Driven through the environment rather than a command-line
    override, because the environment is how `main-releasability.yml` actually
    supplies it.
    """

    supplied = subprocess.run(
        ["make", "-n", "docker-build"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "CONTAINER_GIT_SHA": "deadbeefcafe"},
    ).stdout

    assert "--build-arg APP_GIT_COMMIT_SHA='deadbeefcafe'" in supplied
    assert "-dirty" not in supplied, "a supplied commit was decorated with local tree state"


def test_a_modified_tree_is_marked_and_a_clean_one_is_not() -> None:
    """Both directions driven, because a marker that is always on says nothing.

    A dirty build stamped with a clean `HEAD` attributes a runtime to source that never
    produced it. The marker keeps local iteration working while letting acceptance
    reject a dirty value -- it cannot reject what it cannot see.
    """

    dirty = _make_expansion("docker-build", "CONTAINER_GIT_TREE_STATE=dirty", "CONTAINER_GIT_HEAD=abc123")
    clean = _make_expansion("docker-build", "CONTAINER_GIT_TREE_STATE=clean", "CONTAINER_GIT_HEAD=abc123")

    assert "APP_GIT_COMMIT_SHA='abc123-dirty'" in dirty
    assert "APP_GIT_COMMIT_SHA='abc123'" in clean
    assert "-dirty" not in clean


def test_the_commit_is_the_real_head_not_merely_a_non_empty_string() -> None:
    """Asserted against `git rev-parse HEAD`.

    A non-emptiness check is satisfied by `local`, which is the exact state this issue
    exists to end -- a well-formed field that never described anything.
    """

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    stamped = re.search(r"--build-arg APP_GIT_COMMIT_SHA='([^']*)'", _make_expansion("docker-build"))
    assert stamped is not None
    assert stamped.group(1).removesuffix("-dirty") == head


def test_a_branch_name_is_recorded_as_data_and_never_executed(tmp_path: Path) -> None:
    """git accepts `;`, `$`, backticks and quotes in a branch name.

    Unquoted, `feature/foo;echo-PWN` would end the docker command and start another.

    Driven from a real branch in an isolated worktree rather than through
    `make CONTAINER_GIT_BRANCH=...`: a value given on Make's command line is a Make
    expression, so Make consumes `$(id)` itself before any quoting happens. That
    measures Make's expansion of an override, not the production path, where the value
    comes from `$(shell git rev-parse --abbrev-ref HEAD)` and is not re-expanded.
    """

    hostile = "feature/foo;echo-PWN$(id)`whoami`"
    worktree = tmp_path / "hostile-branch"

    # `--no-checkout` because the only file this needs is the Makefile it writes below,
    # and a materialised worktree puts a second copy of every module under a temporary
    # path. Coverage traces those copies and then fails the combined report with
    # `No source for code: /tmp/.../hostile-branch/adapters/__init__.py` once the
    # worktree is removed -- a test polluting a gate that has nothing to do with it.
    # The branch still resolves: HEAD is set even with no working files.
    subprocess.run(
        ["git", "worktree", "add", "--no-checkout", "-b", hostile, str(worktree), "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    try:
        # The Makefile under test, not the committed one: a checked-out worktree carries
        # HEAD's copy, so without this the test would pass only once the change is
        # already committed and silently measure the previous revision until then.
        (worktree / "Makefile").write_text(
            (REPO_ROOT / "Makefile").read_text(encoding="utf-8"), encoding="utf-8", newline=""
        )
        expansion = subprocess.run(
            ["make", "-n", "docker-build"],
            cwd=worktree,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    finally:
        for cleanup in (
            ["git", "worktree", "remove", "--force", str(worktree)],
            ["git", "branch", "-D", hostile],
        ):
            subprocess.run(cleanup, cwd=REPO_ROOT, capture_output=True, text=True, check=False)

    quoted = re.search(_BRANCH_ARGUMENT, expansion)
    assert quoted is not None

    # Round-trip through the shell's own parser: what a shell hands to docker has to be
    # the original string, not an approximation of it.
    delivered = subprocess.run(
        ["sh", "-c", f"printf '%s' {quoted.group(1)}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert delivered == hostile


def test_no_ignored_path_can_enter_the_build_context() -> None:
    """A clean-looking tree must not be able to ship anything git is ignoring.

    `git status --porcelain` does not list ignored files, so a checkout carrying one
    measures clean, the commit is stamped without `-dirty`, `COPY . .` copies it in,
    and the image ships uncommitted content under a claim of an exact commit.

    Raised twice in review of #511, and the second time is the instructive one. The
    first fix excluded `.env` -- the file named in the report -- and left `venv/`,
    `ENV/`, `artifacts/`, `.idea/` and `.vscode/` ignored and still copied. `artifacts/`
    is the sharpest of those, since it can hold support or audit evidence. Fixing the
    reported instance is not the same as fixing the defect.

    So this asserts the relationship rather than a list: every ignored path is either
    excluded from the context or named in `_DELIBERATELY_PACKAGED`. A future
    `.gitignore` entry then cannot silently reopen the hole, and packaging something
    ignored becomes a decision someone has to write down.

    Excluded from the context rather than taught to the dirty check, because the image
    should not carry ignored content whatever the provenance says -- and once it
    cannot, the provenance claim is true for the same reason.
    """

    ignored = _ignore_entries(".gitignore")
    excluded = _ignore_entries(".dockerignore")

    uncovered = sorted(
        entry
        for entry in ignored
        if entry not in excluded
        and not any(fnmatch(entry, pattern) for pattern in excluded)
        and entry not in _DELIBERATELY_PACKAGED
    )
    assert not uncovered, (
        f"git ignores {uncovered} but the build context does not, so a checkout carrying "
        "any of them measures clean while the image ships it"
    )


def test_volatile_metadata_is_applied_after_the_expensive_layers() -> None:
    """A timestamp that changes every second must not be in the dependency cache key.

    `APP_BUILD_TIMESTAMP` changes on every invocation. An `ENV` referencing it before
    the pip install changes that layer's config, so every local build reinstalls every
    dependency for metadata that has no bearing on them.

    Asserted by relative position rather than by line number, so this keeps holding as
    the file grows.
    """

    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")

    dependency_install = dockerfile.index("RUN pip install")
    provenance_env = dockerfile.index('ENV APP_VERSION="${APP_VERSION}"')
    provenance_label = dockerfile.index('LABEL org.opencontainers.image.title="lotus-performance"')

    assert provenance_env > dependency_install, "provenance ENV precedes the dependency layer"
    assert provenance_label > dependency_install, "provenance LABEL precedes the dependency layer"

    # The static interpreter settings should stay early: they never change, so keeping
    # them before the install costs nothing and keeps that layer shared.
    assert dockerfile.index("ENV PYTHONDONTWRITEBYTECODE=1") < dependency_install


@pytest.mark.parametrize(
    ("label", "hostile"),
    [
        ("a make function reference", "feature/foo$(id)"),
        ("a make variable reference", "feature/foo$(HOME)"),
        ("shell metacharacters too", "feature/foo$(id)`whoami`;echo-PWN"),
    ],
)
def test_an_environment_supplied_branch_survives_makes_own_expansion(label: str, hostile: str) -> None:
    """The environment is a second door, and it is the one CI uses.

    GNU Make imports environment variables as *recursively expanded*, so an env-supplied
    branch named `feature/foo$(id)` is interpreted by Make before `shellquote` sees it
    and reaches the build argument as `feature/foo` -- the image then records a branch
    that does not exist, silently, with no error anywhere.

    The existing hostile-branch test cannot catch this: it drives the value through
    `$(shell git rev-parse ...)`, whose output Make does not re-expand. That path was
    already safe, so the test entered through the one door that could not fail. This is
    the same lesson from the other side -- a hostile-input test has to enter the way the
    real value does, and there is more than one real way in.

    `main-releasability.yml` supplies CONTAINER_GIT_SHA, CONTAINER_GIT_BRANCH,
    CONTAINER_REPOSITORY_URL and CONTAINER_CI_PIPELINE_RUN_ID through the environment,
    so this is the supported production path rather than an exotic one.

    Raised in review of #511.
    """

    expansion = subprocess.run(
        ["make", "-n", "docker-build"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "CONTAINER_GIT_BRANCH": hostile},
    ).stdout

    quoted = re.search(_BRANCH_ARGUMENT, expansion)
    assert quoted is not None

    delivered = subprocess.run(
        ["sh", "-c", f"printf '%s' {quoted.group(1)}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert delivered == hostile, f"{label} did not survive Make's own expansion"


def test_every_provenance_variable_is_captured_raw_from_the_environment() -> None:
    """Uniform, because deciding per variable which can contain a `$` goes stale.

    A repository URL or a pipeline run id is unlikely to contain a Make reference today.
    That is a property of current values, not of the mechanism, and the exclusion would
    have to be re-justified every time one of them changes shape. The rule costs nothing
    and removes the judgement.
    """

    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    container_variables = (
        "CONTAINER_SERVICE_VERSION",
        "CONTAINER_GIT_SHA",
        "CONTAINER_GIT_BRANCH",
        "CONTAINER_BUILD_TIMESTAMP",
        "CONTAINER_REPOSITORY_URL",
        "CONTAINER_IMAGE_DIGEST",
        "CONTAINER_CI_PIPELINE_RUN_ID",
    )

    for name in container_variables:
        assert (
            f"{name} := $(call raw_environment_value,{name}," in makefile
        ), f"{name} is not re-captured raw, so an env-supplied `$(...)` would be expanded away"
