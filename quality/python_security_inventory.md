# Lotus Performance Python Security Inventory

Report date: 2026-06-04
Branch: `feat/performance-hardening-wave-9`
Mode: report-only Bandit inventory; no blocking CI gate is introduced by this artifact.

## Purpose

This report captures Python static security findings using `bandit` across the production runtime
paths. It complements dependency vulnerability auditing by measuring insecure-code-pattern findings
directly in first-party application, engine, core, and adapter code.

## Command

```powershell
python scripts/python_security_inventory.py --limit 30
```

## Summary

| Metric | Value |
| --- | ---: |
| Total Bandit findings | 5 |
| High severity findings | 0 |
| Medium severity findings | 0 |
| Low severity findings | 5 |
| Distinct test IDs | 2 |

## Findings By Severity

| Severity | Count |
| --- | ---: |
| LOW | 5 |

## Findings By Confidence

| Confidence | Count |
| --- | ---: |
| MEDIUM | 5 |

## Findings By Test

| Test ID | Count |
| --- | ---: |
| B105 | 4 |
| B106 | 1 |

## Findings By Area

| Area | Count |
| --- | ---: |
| Application | 2 |
| Application models | 2 |
| Services | 1 |

## Findings

| Rank | Severity | Confidence | Test | Location | Issue |
| ---: | --- | --- | --- | --- | --- |
| 1 | LOW | MEDIUM | `B105 hardcoded_password_string` | `app/enterprise_runtime_config.py:7` | Possible hardcoded password: 'secret_rotation_days_out_of_range' |
| 2 | LOW | MEDIUM | `B105 hardcoded_password_string` | `app/enterprise_runtime_config.py:17` | Possible hardcoded password: 'ENTERPRISE_SECRET_ROTATION_DAYS' |
| 3 | LOW | MEDIUM | `B105 hardcoded_password_string` | `app/models/benchmark_exposure_context.py:63` | Possible hardcoded password: 'None' |
| 4 | LOW | MEDIUM | `B105 hardcoded_password_string` | `app/models/benchmark_exposure_context.py:220` | Possible hardcoded password: 'None' |
| 5 | LOW | MEDIUM | `B106 hardcoded_password_funcarg` | `app/services/benchmark_exposure_context_service.py:273` | Possible hardcoded password: 'page.page_token must be a numeric offset token returned by lotus-performance.' |

## Interpretation

Bandit reports zero high-severity and zero medium-severity findings in the scanned first-party
runtime paths. The five current low-severity, medium-confidence findings are string-heuristic
matches in issue-code constants, environment variable names, OpenAPI example pagination tokens, and
pagination validation text. They are kept visible rather than suppressed so a future slice can
classify or suppress them with explicit proof if the current interpretation remains stable.

## Gate Posture

This is a Phase 1 report-only quality measurement. It does not introduce a CI threshold, branch
failure, or exception policy. Promotion to a blocking gate should wait until low-severity
classification, false-positive handling, and CI placement are documented.
