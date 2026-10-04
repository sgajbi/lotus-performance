import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path

KEYWORDS = (
    "amount",
    "price",
    "rate",
    "value",
    "market_value",
    "cost",
    "pnl",
    "return",
    "risk",
    "notional",
    "weight",
    "begin_mv",
    "end_mv",
    "bod_cf",
    "eod_cf",
    "mgmt_fees",
    "cash_flow",
    "cashflow",
    "fees",
)
IGNORE_DIRS = {"tests", ".venv", "venv", "docs", "rfcs", "output", "build", "dist", "__pycache__"}

FLOAT_ANNOTATION = re.compile(r"\bfloat\b")
FINDING_PATTERN = re.compile(r"^(?P<path>.+?):(?P<line_no>\d+):(?P<source>.*)$")
ISSUE_REFERENCE = re.compile(r"https://github\.com/sgajbi/lotus-performance/issues/[1-9]\d*\b")


def is_candidate(path: Path) -> bool:
    parts = set(path.parts)
    if any(p in parts for p in IGNORE_DIRS):
        return False
    return path.suffix == ".py"


def scan_repo(repo_root: Path) -> list[str]:
    findings: list[str] = []
    for file_path in repo_root.rglob("*.py"):
        if not is_candidate(file_path.relative_to(repo_root)):
            continue
        rel = file_path.relative_to(repo_root).as_posix()
        for line_no, line in enumerate(file_path.read_text(encoding="utf-8").splitlines(), start=1):
            lowered = line.lower()
            if not any(k in lowered for k in KEYWORDS):
                continue
            if not FLOAT_ANNOTATION.search(lowered):
                continue
            if "# monetary-float-allow" in lowered:
                continue
            finding = f"{rel}:{line_no}:{line.strip()}"
            findings.append(finding)
    return sorted(set(findings))


def _finding_key(finding: str) -> str:
    match = FINDING_PATTERN.match(finding)
    if match is None:
        return finding
    return f"{match.group('path')}:{match.group('source').strip()}"


def _parse_review_date(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError as exc:
        raise ValueError(f"Invalid review_by date format: {value!r}, expected YYYY-MM-DD") from exc


def load_allowlist(path: Path) -> tuple[dict[str, dict], list[str], list[str]]:
    if not path.exists():
        return {}, [], []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("allowlist"), list):
        return {}, ["Allowlist must be an object containing an allowlist array."], []
    raw_entries = data["allowlist"]
    entries: dict[str, dict] = {}
    errors: list[str] = []
    stale: list[str] = []
    today = datetime.now(tz=UTC).date()
    seen_keys: set[str] = set()
    for item in raw_entries:
        if isinstance(item, str):
            errors.append(f"Legacy allowlist string entry must be migrated: {item}")
            continue
        if not isinstance(item, dict):
            errors.append(f"Allowlist entry must be object, found: {type(item).__name__}")
            continue
        finding = item.get("finding")
        justification = item.get("justification")
        owner = item.get("owner")
        review_by = item.get("review_by")
        if not all(isinstance(value, str) and value.strip() for value in (finding, justification, owner, review_by)):
            errors.append(
                "Allowlist entry missing required fields (finding/justification/owner/review_by): "
                + json.dumps(item, sort_keys=True)
            )
            continue
        if FINDING_PATTERN.fullmatch(finding) is None:
            errors.append(f"Invalid finding identity: {finding}")
            continue
        key = _finding_key(finding)
        if key in seen_keys:
            errors.append(f"Duplicate allowance for source expression: {finding}")
            continue
        seen_keys.add(key)
        if "temporary approved monetary" in justification.lower() or not ISSUE_REFERENCE.search(justification):
            errors.append(f"Allowance requires a finding-specific justification and owning issue: {finding}")
            continue
        try:
            review_dt = _parse_review_date(str(review_by))
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if review_dt.date() < today:
            stale.append(str(finding))
        entries[str(finding)] = {
            "finding": str(finding),
            "justification": str(justification),
            "owner": str(owner),
            "review_by": review_dt.strftime("%Y-%m-%d"),
        }
    return entries, errors, stale


def write_allowlist(path: Path, findings: list[str], existing_entries: dict[str, dict]) -> None:
    """Refresh source locations only; new approvals require explicit reviewed evidence."""
    approved_by_key = {_finding_key(finding): entry for finding, entry in existing_entries.items()}
    unexpected = [finding for finding in findings if _finding_key(finding) not in approved_by_key]
    if unexpected:
        raise ValueError("Cannot create a reviewed approval automatically: " + "; ".join(unexpected))
    generated_at = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    refreshed_by_key: dict[str, dict] = {}
    for finding in sorted(set(findings)):
        key = _finding_key(finding)
        refreshed_by_key.setdefault(key, {**approved_by_key[key], "finding": finding})
    allowlist_entries = list(refreshed_by_key.values())
    payload = {
        "description": "Approved baseline monetary-float findings. New findings fail CI.",
        "policy_version": "1.1.0",
        "generated_at": generated_at,
        "allowlist": allowlist_entries,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Guard against unauthorized monetary float usage")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--allowlist",
        default="docs/standards/monetary-float-allowlist.json",
    )
    parser.add_argument(
        "--update-allowlist", action="store_true", help="Refresh reviewed locations; never create approvals."
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    allowlist_path = (repo_root / args.allowlist).resolve()
    if not any(is_candidate(path.relative_to(repo_root)) for path in repo_root.rglob("*.py")):
        print("Monetary float guard requires at least one first-party Python source file.")
        return 1
    findings = scan_repo(repo_root)
    try:
        allowlist_entries, allowlist_errors, stale_entries = load_allowlist(allowlist_path)
    except (OSError, ValueError) as exc:
        print(f"Cannot read allowance evidence: {exc}")
        return 1

    if allowlist_errors:
        print("Allowlist schema validation failed:")
        for item in allowlist_errors:
            print(f" - {item}")
        return 1

    if stale_entries:
        print("Allowlist contains stale entries (review_by in the past):")
        for item in stale_entries:
            print(f" - {item}")
        print(f"\nReview {allowlist_path}; remediate or publish a finding-specific decision. Do not renew blindly.")
        return 1

    allowlist_keys = {_finding_key(finding) for finding in allowlist_entries}
    unexpected = sorted(finding for finding in findings if _finding_key(finding) not in allowlist_keys)

    if unexpected:
        print("Unauthorized monetary float usage detected:")
        for item in unexpected:
            print(f" - {item}")
        print(f"\nBaseline allowlist file: {allowlist_path}")
        print(
            "Publish a finding-specific approval and owning issue in a reviewed PR; automatic approval is unavailable."
        )
        return 1

    if args.update_allowlist:
        write_allowlist(allowlist_path, findings, allowlist_entries)
        print(f"Refreshed reviewed allowlist with {len(findings)} finding(s): {allowlist_path}")
        return 0

    finding_keys = {_finding_key(finding) for finding in findings}
    orphaned = sorted(finding for finding in allowlist_entries if _finding_key(finding) not in finding_keys)
    if orphaned:
        print("Allowlist entries no longer matched by the scan; remove obsolete approvals:")
        for finding in orphaned:
            print(f" - {finding}")
        return 1

    print(f"Monetary float guard passed. Findings={len(findings)}, allowlisted={len(allowlist_entries)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
