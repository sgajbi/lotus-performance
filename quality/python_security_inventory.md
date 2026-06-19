# Lotus Performance Python Security Inventory

Report date: 2026-06-04
Branch: `lp-cr-1388-source-economics-raw-sampling`
Mode: enforced Bandit inventory; zero high, medium, and low findings are blocked by CI.

## Purpose

This report captures Python static security findings using `bandit` across the production runtime
paths. It complements dependency vulnerability auditing by measuring insecure-code-pattern findings
directly in first-party application, engine, core, and adapter code.

## Command

```powershell
python scripts/python_security_inventory.py --limit 30 --max-high 0 --max-medium 0 --max-low 0
```

## Summary

| Metric | Value |
| --- | ---: |
| Total Bandit findings | 0 |
| High severity findings | 0 |
| Medium severity findings | 0 |
| Low severity findings | 0 |
| Distinct test IDs | 0 |
| Lines scanned | 50038 |
| `nosec` markers | 0 |
| Targeted skipped tests | 2 |

## Findings By Severity

| Severity | Count |
| --- | ---: |

## Findings By Confidence

| Confidence | Count |
| --- | ---: |

## Findings By Test

| Test ID | Count |
| --- | ---: |

## Findings By Area

| Area | Count |
| --- | ---: |

## Findings

| Rank | Severity | Confidence | Test | Location | Issue |
| ---: | --- | --- | --- | --- | --- |

## Interpretation

Bandit reports zero findings in the scanned first-party runtime paths. The current scan covers
50038 lines and reports two targeted skipped tests from reviewed `# nosec B105` markers. Earlier
low-severity string-heuristic findings were classified and remediated with neutral named constants
or targeted reviewed markers. The latest gate-promotion slice also removed five production
`assert` statements so Bandit `B101` findings are not hidden behind an allowlist.

## Gate Posture

`make python-security-gate` enforces zero high, medium, and low Bandit findings in local checks,
Feature Lane, PR Merge Gate, and Main Releasability. Future exceptions must be documented,
targeted, and covered by tests before this threshold is relaxed.
