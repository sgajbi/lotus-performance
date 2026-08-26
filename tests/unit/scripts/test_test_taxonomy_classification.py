"""The uncategorized ceiling must reflect what is unclassified, not what the classifier ignores.

`make quality-test-taxonomy-gate` caps uncategorized test functions. A surface the classifier has
no token for contributes its entire test count to that cap, so adding a test there turns the gate
red and the only way to go green is to edit a governance threshold. The workspace analytics surface
was in exactly that state — 90 tests across 3 modules, zero families — see issue #475.

These tests hold the classifier accountable for the surfaces it claims to cover, so a rename or a
refactor cannot silently return one of them to `uncategorized`.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from scripts.python_test_taxonomy_inventory import (
    collect_test_modules,
    summarize_test_taxonomy,
)

ROOT = Path(__file__).resolve().parents[3]
MAKEFILE = ROOT / "Makefile"
CLASSIFIER = ROOT / "scripts" / "python_test_taxonomy_inventory.py"

# Surfaces this repository claims the classifier understands. The *existence* of every token is
# checked automatically below; this table exists only to assert the family a surface resolves to,
# which cannot be derived from the token list.
CLASSIFIED_SURFACES = (
    ("workspace", "analytics_domain"),
    ("twr", "analytics_domain"),
    ("contribution", "analytics_domain"),
    ("attribution", "analytics_domain"),
)


def _classifier_tokens() -> tuple[str, ...]:
    """Every path substring `_families_for_path` tests against, read from its own source.

    Reading the source rather than repeating the list is the point: a hand-copied table covers the
    tokens somebody remembered to add, which is the drift this guard exists to catch.
    """

    function = next(
        node
        for node in ast.walk(ast.parse(CLASSIFIER.read_text(encoding="utf-8")))
        if isinstance(node, ast.FunctionDef) and node.name == "_families_for_path"
    )
    tokens = {
        element.value
        for node in ast.walk(function)
        if isinstance(node, ast.Tuple)
        for element in node.elts
        if isinstance(element, ast.Constant) and isinstance(element.value, str)
    }
    # `startswith` prefixes are path anchors rather than substrings; they are covered by the
    # directory rules and would never appear as a bare token match.
    return tuple(sorted(token for token in tokens if not token.startswith("tests/")))


def test_every_classifier_token_matches_at_least_one_module() -> None:
    """A token that matches nothing is a rule that silently does nothing.

    The narrower version of this check covered the four tokens named in `CLASSIFIED_SURFACES`; the
    classifier carries many more, and each one that stops matching is a classification rule quietly
    reduced to decoration. Deriving the list from the classifier makes this self-maintaining: a
    token added there is covered here without anyone remembering to update a second table.
    """

    modules = collect_test_modules(("tests",))
    paths = [module.path.lower() for module in modules]

    dead = sorted(token for token in _classifier_tokens() if not any(token in path for path in paths))

    assert dead == [], (
        "These classifier tokens match no test module, so they classify nothing and their family "
        f"rules are inert: {dead}. Remove them or fix what they were meant to match."
    )


def test_the_token_set_is_large_enough_to_be_the_real_one() -> None:
    """Guards the extraction itself.

    If `_classifier_tokens` silently returned an empty or tiny set - a refactor to a module-level
    constant, a change of function name - the check above would pass while covering nothing. That
    is the failure mode the dead-token guard exists to prevent, applied to the guard.
    """

    tokens = _classifier_tokens()

    assert len(tokens) >= 30, f"Only {len(tokens)} classifier tokens extracted: {tokens}"
    for expected in ("workspace", "twr", "attribution", "observability", "security"):
        assert expected in tokens, f"{expected!r} missing from the extracted token set: {tokens}"


def test_named_analytics_surfaces_are_classified() -> None:
    modules = collect_test_modules(("tests",))

    unclassified = []
    for token, family in CLASSIFIED_SURFACES:
        matching = [module for module in modules if token in module.path.lower()]
        assert matching, f"No test module matches {token!r}; this claim has nothing to hold."
        unclassified.extend(
            f"{module.path} -> {module.families}" for module in matching if family not in module.families
        )

    assert unclassified == [], (
        "These modules belong to a named analytics surface but carry no matching family, so their "
        f"tests inflate the uncategorized ceiling: {unclassified}. See issue #475."
    )


def test_the_uncategorized_ceiling_is_banked_at_the_measured_value() -> None:
    """A ceiling above the measured value is unearned slack the next change can spend."""

    measured = summarize_test_taxonomy(collect_test_modules(("tests",))).uncategorized_tests

    match = re.search(r"--max-uncategorized-tests (\d+)", MAKEFILE.read_text(encoding="utf-8"))
    assert match is not None, "The taxonomy gate no longer declares an uncategorized ceiling."
    declared = int(match.group(1))

    assert declared == measured, (
        f"The uncategorized ceiling is {declared} but the tree measures {measured}. A ceiling above "
        "the measured value banks slack into the gate; one below it is already red. Re-bank it to "
        "the measured value in the same change that moves the number."
    )


# Append-only historical records. Every row states the command as it was run against a dated
# commit, so rewriting those thresholds to today's values would falsify the evidence the record
# exists to preserve. `test_excluded_records_are_actually_dated_histories` keeps this list from
# quietly becoming a place to hide live drift.
HISTORICAL_RECORDS = frozenset({"docs/architecture/CODEBASE-REVIEW-LEDGER.md"})


def test_excluded_records_are_actually_dated_histories() -> None:
    """An exclusion list is only safe while every entry earns its place."""

    for relative_path in sorted(HISTORICAL_RECORDS):
        document = ROOT / relative_path
        assert document.is_file(), f"{relative_path} is excluded from drift checking but is missing."
        text = document.read_text(encoding="utf-8", errors="ignore")
        dated_rows = re.findall(r"\| \d{4}-\d{2}-\d{2} \|", text)
        assert len(dated_rows) >= 10, (
            f"{relative_path} is excluded as an append-only dated history but contains "
            f"{len(dated_rows)} dated rows. If it is not a history, it must be drift-checked."
        )


def test_no_document_states_a_taxonomy_threshold_the_gate_does_not_enforce() -> None:
    """A documented threshold looser than the enforced one misleads toward doing the wrong thing.

    This PR removed 90 tests of slack from the gate and left the old ceiling standing in two
    durable references, where a developer copying the documented command would have run with
    exactly the slack the change existed to remove. Nothing in the lane could see it: no gate
    compared a documented threshold against the enforced one.

    Historical provenance prose is untouched by design - this reads only the *flag* form, which
    appears where a command is meant to be run, never in a narrative sentence.
    """

    makefile = MAKEFILE.read_text(encoding="utf-8")
    enforced = {flag: int(value) for flag, value in re.findall(r"--(m(?:in|ax)-[a-z-]+-tests) (\d+)", makefile)}
    assert enforced, "The taxonomy gate declares no thresholds in the Makefile."

    drift = []
    for document in sorted(ROOT.rglob("*.md")):
        if any(part in {".git", "node_modules", "output", ".venv"} for part in document.parts):
            continue
        if document.relative_to(ROOT).as_posix() in HISTORICAL_RECORDS:
            continue
        text = document.read_text(encoding="utf-8", errors="ignore")
        for flag, value in re.findall(r"--(m(?:in|ax)-[a-z-]+-tests) (\d+)", text):
            if flag in enforced and int(value) != enforced[flag]:
                drift.append(
                    f"{document.relative_to(ROOT).as_posix()}: --{flag} {value}, " f"enforced {enforced[flag]}"
                )

    assert drift == [], (
        "These documents state a taxonomy threshold the gate does not enforce. A documented value "
        "looser than the enforced one is worse than no documentation, because following it "
        f"produces the slack the gate exists to prevent: {drift}"
    )


def test_the_repository_context_does_not_restate_the_thresholds_as_a_second_copy() -> None:
    """The durable fix for the drift above is one source, not two that are checked against it.

    REPOSITORY-ENGINEERING-CONTEXT.md previously restated all three thresholds in prose, so every
    re-bank had to be mirrored by hand in a file no gate reads. It now points at the Makefile
    target instead.
    """

    context = (ROOT / "REPOSITORY-ENGINEERING-CONTEXT.md").read_text(encoding="utf-8")
    paragraph = re.search(r"`make quality-test-taxonomy-gate`[^.]*\.", context, re.S)
    assert paragraph is not None, "The taxonomy gate is no longer described in the repository context."

    assert not re.search(r"`\d{3}`", paragraph.group(0)), (
        "The repository context restates a taxonomy threshold. Cite the Makefile target instead - "
        f"a second hand-maintained copy is what drifted in the first place: {paragraph.group(0)!r}"
    )
