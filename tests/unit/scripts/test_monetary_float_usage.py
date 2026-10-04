import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_monetary_float_usage import _finding_key, load_allowlist, scan_repo, write_allowlist


def test_finding_key_is_stable_when_line_numbers_move():
    original = "app/services/example.py:42:return_value=float(row['return_value'])"
    moved = "app/services/example.py:108:return_value=float(row['return_value'])"

    assert _finding_key(original) == _finding_key(moved)


def test_finding_key_preserves_source_expression():
    approved = "app/services/example.py:42:return_value=float(row['return_value'])"
    changed = "app/services/example.py:42:market_value=float(row['market_value'])"

    assert _finding_key(approved) != _finding_key(changed)


def _approved_entry(finding: str) -> dict:
    return {
        "finding": finding,
        "justification": "Projected solver monetary residual; review https://github.com/sgajbi/lotus-performance/issues/472.",
        "owner": "lotus-performance",
        "review_by": "2099-12-31",
    }


def test_allowlist_refuses_generic_approval(tmp_path):
    entry = _approved_entry("solver.py:1:return float(amount)")
    entry["justification"] = "Temporary approved monetary floating-point usage; convert to Decimal."
    path = tmp_path / "allowlist.json"
    path.write_text(json.dumps({"allowlist": [entry]}), encoding="utf-8")

    _, errors, _ = load_allowlist(path)

    assert any("finding-specific" in error for error in errors)


@pytest.mark.parametrize(
    "field,value",
    [
        ("owner", " "),
        ("justification", 7),
        ("review_by", "bad-date"),
        ("finding", "solver.py:not-a-line:return float(amount)"),
    ],
)
def test_allowlist_refuses_malformed_evidence(tmp_path, field, value):
    entry = _approved_entry("solver.py:1:return float(amount)")
    entry[field] = value
    path = tmp_path / "allowlist.json"
    path.write_text(json.dumps({"allowlist": [entry]}), encoding="utf-8")

    _, errors, _ = load_allowlist(path)

    assert errors


@pytest.mark.parametrize("payload", [[], {}, {"allowlist": None}, {"allowlist": {}}])
def test_allowlist_refuses_invalid_container(tmp_path, payload):
    path = tmp_path / "allowlist.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    _, errors, _ = load_allowlist(path)
    assert errors


def test_allowlist_refuses_duplicate_approvals_after_line_shift(tmp_path):
    path = tmp_path / "allowlist.json"
    path.write_text(
        json.dumps(
            {
                "allowlist": [
                    _approved_entry("solver.py:1:return float(amount)"),
                    _approved_entry("solver.py:5:return float(amount)"),
                ]
            }
        ),
        encoding="utf-8",
    )

    _, errors, _ = load_allowlist(path)

    assert any("Duplicate" in error for error in errors)


def test_refresh_preserves_approval_and_deadline_after_line_shift(tmp_path):
    original = _approved_entry("solver.py:1:return float(amount)")
    path = tmp_path / "allowlist.json"

    write_allowlist(path, ["solver.py:5:return float(amount)"], {original["finding"]: original})

    refreshed = json.loads(path.read_text(encoding="utf-8"))["allowlist"]
    assert len(refreshed) == 1
    assert refreshed[0] == {**original, "finding": "solver.py:5:return float(amount)"}


def test_refresh_cannot_manufacture_new_approval_or_overwrite_evidence(tmp_path):
    path = tmp_path / "allowlist.json"
    original = b"retained approval evidence\n"
    path.write_bytes(original)

    with pytest.raises(ValueError, match="reviewed approval"):
        write_allowlist(path, ["solver.py:1:return float(amount)"], {})

    assert path.read_bytes() == original


def test_refresh_keeps_one_approval_for_repeated_source_expression(tmp_path):
    original = _approved_entry("solver.py:1:return float(amount)")
    path = tmp_path / "allowlist.json"

    write_allowlist(path, [original["finding"], "solver.py:5:return float(amount)"], {original["finding"]: original})

    entries, errors, stale = load_allowlist(path)
    assert errors == []
    assert stale == []
    assert list(entries.values()) == [original]


def test_cli_refuses_orphaned_allowance(tmp_path):
    (tmp_path / "solver.py").write_text("observation_count: int = 0\n", encoding="utf-8")
    allowance = tmp_path / "allowlist.json"
    allowance.write_text(
        json.dumps({"allowlist": [_approved_entry("solver.py:1:return float(amount)")]}), encoding="utf-8"
    )

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/check_monetary_float_usage.py"),
            "--repo-root",
            str(tmp_path),
            "--allowlist",
            str(allowance),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "no longer matched" in result.stdout


@pytest.mark.parametrize("approved", [False, True])
def test_cli_refresh_cannot_approve_new_or_renew_expired_evidence(tmp_path, approved):
    (tmp_path / "solver.py").write_text("return float(amount)\n", encoding="utf-8")
    allowance = tmp_path / "allowlist.json"
    entry = _approved_entry("solver.py:1:return float(amount)")
    entry["review_by"] = "2000-01-01"
    allowance.write_text(json.dumps({"allowlist": [entry] if approved else []}), encoding="utf-8")
    original = allowance.read_bytes()

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/check_monetary_float_usage.py"),
            "--repo-root",
            str(tmp_path),
            "--allowlist",
            str(allowance),
            "--update-allowlist",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert ("stale entries" if approved else "Unauthorized") in result.stdout
    assert allowance.read_bytes() == original


def test_source_exemption_does_not_hide_unmarked_monetary_float(tmp_path: Path):
    source = tmp_path / "app" / "example.py"
    source.parent.mkdir()
    source.write_text(
        "period_return: float = 0.1  # monetary-float-allow: dimensionless ratio\nend_market_value: float = 100.1\n",
        encoding="utf-8",
    )

    assert scan_repo(tmp_path) == ["app/example.py:2:end_market_value: float = 100.1"]


@pytest.mark.parametrize("field", ["begin_mv", "end_mv", "bod_cf", "eod_cf", "mgmt_fees", "ending_cash_flow", "fees"])
def test_scan_detects_short_valuation_names_and_cash_flow_evidence(tmp_path, field):
    source = tmp_path / "valuation.py"
    source.write_text(f"{field}: float = 100.1\n", encoding="utf-8")
    assert scan_repo(tmp_path) == [f"valuation.py:1:{field}: float = 100.1"]


def test_cli_refuses_unapproved_short_valuation_monetary_field(tmp_path):
    (tmp_path / "valuation.py").write_text("eod_cf: float = 0.0\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/check_monetary_float_usage.py"),
            "--repo-root",
            str(tmp_path),
            "--allowlist",
            str(tmp_path / "allowlist.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "Unauthorized monetary float usage" in result.stdout
    assert "eod_cf: float" in result.stdout


@pytest.mark.parametrize(("source", "exit_code"), [(None, 1), ("observation_count: int = 0\n", 0)])
def test_cli_distinguishes_empty_source_inventory_from_clean_source(tmp_path, source, exit_code):
    if source is not None:
        (tmp_path / "clean.py").write_text(source, encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/check_monetary_float_usage.py"),
            "--repo-root",
            str(tmp_path),
            "--allowlist",
            str(tmp_path / "allowlist.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == exit_code
    assert ("requires at least one" if source is None else "guard passed") in result.stdout


def test_xirr_scale_annotations_share_existing_numerical_boundary_deadline():
    payload = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    scale_entries = [entry for entry in payload["allowlist"] if "gross_cash_flow_scale" in entry["finding"]]
    assert len(scale_entries) == 4
    assert {entry["review_by"] for entry in scale_entries} == {"2026-11-06"}
    assert {entry["owner"] for entry in scale_entries} == {"lotus-performance"}
    assert all(
        "issues/473" in entry["justification"] and "issues/472" in entry["justification"] for entry in scale_entries
    )


REPO_ROOT = Path(__file__).resolve().parents[3]
ALLOWLIST_PATH = REPO_ROOT / "docs/standards/monetary-float-allowlist.json"

BOILERPLATE_JUSTIFICATION = "Temporary approved monetary floating-point usage; convert to Decimal."

DISPOSITIONED_FINDINGS = {
    "engine/numerical_boundary.py:13:def finite_float64_projection(value: Decimal) -> float:",
    "engine/numerical_boundary.py:15:projected = float(value)",
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
    assert not any(
        finding.startswith("app/models/contribution_requests.py:") and "end_mv: float" in finding
        for finding in finding_keys
    ), "Issue #530 retired the reviewed contribution end_mv float boundary."


def test_every_remaining_entry_names_its_reviewed_boundary_and_owner():
    """Ratio matches are retired; monetary numerical boundaries retain accountable review."""

    payload = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    reviewed = {entry["finding"]: entry for entry in payload["allowlist"]}

    assert DISPOSITIONED_FINDINGS.issubset(reviewed)
    for finding, entry in reviewed.items():
        assert entry["justification"].strip() != BOILERPLATE_JUSTIFICATION, finding
        assert MIGRATION_ISSUE in entry["justification"], finding
        assert "https://github.com/sgajbi/lotus-performance/issues/472" in entry["justification"], finding
        assert entry["owner"] == "lotus-performance", finding


def test_the_annualize_return_ratio_is_not_an_allowlist_entry():
    """A false positive is dispositioned at the code site, never as a dated allowance.

    annualize_return takes a dimensionless ratio and a day-count divisor. Recording it as a
    time-bounded allowance would assert deferred debt that does not exist, and would return
    in 180 days to be re-derived by somebody else.
    """

    payload = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))

    offenders = [entry["finding"] for entry in payload["allowlist"] if "annualize_return" in entry["finding"]]

    assert offenders == [], offenders


def test_migrated_request_fields_have_no_standing_float_allowance():
    payload = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    retired = {
        "app/models/mwr_requests.py:amount: float",
        "core/envelope.py:rate: float = Field(..., gt=0, allow_inf_nan=False)",
        "engine/mwr.py:def _net_same_day_flows(values: list[float], dates: list[date]) -> tuple[np.ndarray, np.ndarray]:",
        "engine/mwr.py:np.array([amount for _, amount in sorted_items], dtype=float),",
    }
    assert not retired.intersection(_finding_key(entry["finding"]) for entry in payload["allowlist"])
    numerical_boundary = [
        entry for entry in payload["allowlist"] if entry["finding"].startswith("engine/numerical_boundary.py:")
    ]
    assert len(numerical_boundary) == 2
    assert {entry["review_by"] for entry in numerical_boundary} == {"2026-11-06"}
    assert all(entry["owner"] == "lotus-performance" for entry in numerical_boundary)


def test_breakdown_percentage_returns_are_not_dated_monetary_allowlist_entries():
    """Quantized return percentages are ratios, so they are source-dispositioned.

    The exact two expressions previously carried stale generic entries even though the
    rounding standard already classifies percentage returns as dimensionless. Keep the
    source marker and the no-entry rule together so a future expiry cannot make the
    repository's release gate red again.
    """

    payload = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    offenders = [
        entry["finding"] for entry in payload["allowlist"] if entry["finding"].startswith("engine/breakdown.py:")
    ]

    source = (REPO_ROOT / "engine/breakdown.py").read_text(encoding="utf-8")
    assert offenders == [], offenders
    assert source.count("# monetary-float-allow: quantized percentage return is a dimensionless ratio, not money.") == 1
    assert (
        source.count("# monetary-float-allow: cumulative percentage return is a dimensionless ratio, not money.") == 1
    )
