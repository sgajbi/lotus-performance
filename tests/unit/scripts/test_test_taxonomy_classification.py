"""The uncategorized ceiling must reflect what is unclassified, not what the classifier ignores.

`make quality-test-taxonomy-gate` caps uncategorized test functions. A surface the classifier has
no token for contributes its entire test count to that cap, so adding a test there turns the gate
red and the only way to go green is to edit a governance threshold. The workspace analytics surface
was in exactly that state — 90 tests across 3 modules, zero families — see issue #475.

These tests hold the classifier accountable for the surfaces it claims to cover, so a rename or a
refactor cannot silently return one of them to `uncategorized`.
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts.python_test_taxonomy_inventory import (
    collect_test_modules,
    summarize_test_taxonomy,
)

ROOT = Path(__file__).resolve().parents[3]
MAKEFILE = ROOT / "Makefile"

# Surfaces whose tests must carry a family. Each entry is a path substring and the family it must
# resolve to. Adding a surface here is a claim that the classifier understands it.
CLASSIFIED_SURFACES = (
    ("workspace", "analytics_domain"),
    ("twr", "analytics_domain"),
    ("contribution", "analytics_domain"),
    ("attribution", "analytics_domain"),
)


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
