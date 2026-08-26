import json
from pathlib import Path

from scripts.check_monetary_float_usage import _finding_key, load_allowlist, scan_repo


def test_finding_key_is_stable_when_line_numbers_move():
    original = "app/services/example.py:42:return_value=float(row['return_value'])"
    moved = "app/services/example.py:108:return_value=float(row['return_value'])"

    assert _finding_key(original) == _finding_key(moved)


def test_finding_key_preserves_source_expression():
    approved = "app/services/example.py:42:return_value=float(row['return_value'])"
    changed = "app/services/example.py:42:market_value=float(row['market_value'])"

    assert _finding_key(approved) != _finding_key(changed)


REPO_ROOT = Path(__file__).resolve().parents[3]
ALLOWLIST_PATH = REPO_ROOT / "docs/standards/monetary-float-allowlist.json"

BOILERPLATE_JUSTIFICATION = "Temporary approved monetary floating-point usage; convert to Decimal."

DISPOSITIONED_FINDINGS = {
    "app/models/mwr_requests.py:14:amount: float",
    "core/envelope.py:13:rate: float",
}
MIGRATION_ISSUE = "https://github.com/sgajbi/lotus-performance/issues/473"


def test_every_allowlisted_finding_is_still_produced_by_the_scan():
    """An entry the scan no longer produces is a standing approval for nothing.

    The guard only ever computes findings-minus-allowlist, so a fixed finding keeps its
    approval forever and the allowlist stops describing the code. This is the retirement
    path it lacks; see lotus-platform#728.
    """

    finding_keys = {_finding_key(finding) for finding in scan_repo(REPO_ROOT)}
    entries, errors, stale = load_allowlist(ALLOWLIST_PATH)

    assert errors == []
    assert stale == []
    orphaned = sorted(entry for entry in entries if _finding_key(entry) not in finding_keys)
    assert orphaned == [], (
        "Allowlist entries no longer matched by the scan. Remove them: an approval that "
        f"describes nothing is not coverage. {orphaned}"
    )


def test_dispositioned_entries_name_their_specific_finding_and_migration():
    """The two entries this repository has actually reviewed must not regress to boilerplate.

    The other entries still carry the generic text. That is a larger clean-up than an
    unblock and is recorded on #472 rather than pretended away here; this test holds the
    ground that has been taken.
    """

    payload = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    reviewed = {entry["finding"]: entry for entry in payload["allowlist"] if entry["finding"] in DISPOSITIONED_FINDINGS}

    assert set(reviewed) == DISPOSITIONED_FINDINGS
    for finding, entry in reviewed.items():
        assert entry["justification"].strip() != BOILERPLATE_JUSTIFICATION, finding
        assert MIGRATION_ISSUE in entry["justification"], finding


def test_the_annualize_return_ratio_is_not_an_allowlist_entry():
    """A false positive is dispositioned at the code site, never as a dated allowance.

    annualize_return takes a dimensionless ratio and a day-count divisor. Recording it as a
    time-bounded allowance would assert deferred debt that does not exist, and would return
    in 180 days to be re-derived by somebody else.
    """

    payload = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))

    offenders = [entry["finding"] for entry in payload["allowlist"] if "annualize_return" in entry["finding"]]

    assert offenders == [], offenders
