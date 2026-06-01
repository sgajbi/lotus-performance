# Lotus Performance Dead-Code Inventory

Report date: 2026-06-02
Branch: `feat/performance-hardening-wave-9`
Mode: report-only dead-code inventory; no blocking CI gate is introduced by this artifact.

## Purpose

This report captures current `vulture` unused-code candidates for production Python paths. It is
intended to make stale-code cleanup reviewable without treating framework callbacks, FastAPI route
handlers, Pydantic model fields, validators, and reflected schema fields as confirmed dead code.

## Commands

```powershell
python scripts/python_dead_code_inventory.py --limit 30 --min-confidence 60
python scripts/python_dead_code_inventory.py --limit 30 --min-confidence 80
```

## Summary

At `--min-confidence 60`:

| Metric | Value |
| --- | ---: |
| Minimum confidence | 60% |
| Total findings | 438 |
| Distinct files with findings | 69 |

At `--min-confidence 80`:

| Metric | Value |
| --- | ---: |
| Minimum confidence | 80% |
| Total findings | 0 |
| Distinct files with findings | 0 |

## Findings By Kind

| Kind | Count |
| --- | ---: |
| attribute | 3 |
| class | 7 |
| function | 48 |
| method | 49 |
| variable | 331 |

## Findings By Area

| Area | Count |
| --- | ---: |
| API endpoints | 46 |
| Adapters | 1 |
| Core | 18 |
| Engine | 3 |
| Other | 17 |
| Pydantic models | 314 |
| Services | 39 |

## Top Findings

| Rank | File | Symbol | Kind | Confidence |
| ---: | --- | --- | --- | ---: |
| 1 | `adapters/api_adapter.py:67` | `format_breakdowns_for_response` | function | 60% |
| 2 | `app/api/endpoints/benchmark.py:57` | `calculate_benchmark_endpoint` | function | 60% |
| 3 | `app/api/endpoints/benchmark.py:213` | `get_benchmark_result` | function | 60% |
| 4 | `app/api/endpoints/benchmark_exposure_context.py:18` | `get_benchmark_exposure_context` | function | 60% |
| 5 | `app/api/endpoints/composites.py:112` | `calculate_composite_twr` | function | 60% |
| 6 | `app/api/endpoints/composites.py:162` | `inspect_composite_twr` | function | 60% |
| 7 | `app/api/endpoints/contribution.py:115` | `calculate_contribution_endpoint` | function | 60% |
| 8 | `app/api/endpoints/contribution.py:258` | `get_contribution_result` | function | 60% |
| 9 | `app/api/endpoints/health.py:10` | `health` | function | 60% |
| 10 | `app/api/endpoints/health.py:20` | `health_live` | function | 60% |
| 11 | `app/api/endpoints/health.py:30` | `health_ready` | function | 60% |
| 12 | `app/api/endpoints/inspections.py:37` | `submit_twr_inspection` | function | 60% |
| 13 | `app/api/endpoints/inspections.py:76` | `get_twr_inspection` | function | 60% |
| 14 | `app/api/endpoints/inspections.py:104` | `get_twr_inspection_artifact` | function | 60% |
| 15 | `app/api/endpoints/integration_capabilities.py:344` | `owner_service` | variable | 60% |
| 16 | `app/api/endpoints/integration_capabilities.py:349` | `workflow_key` | variable | 60% |
| 17 | `app/api/endpoints/integration_capabilities.py:354` | `required_features` | variable | 60% |
| 18 | `app/api/endpoints/integration_capabilities.py:374` | `supported_values` | variable | 60% |
| 19 | `app/api/endpoints/integration_capabilities.py:380` | `required_when` | variable | 60% |
| 20 | `app/api/endpoints/integration_capabilities.py:401` | `supports_async` | variable | 60% |
| 21 | `app/api/endpoints/integration_capabilities.py:405` | `poll_path_template` | variable | 60% |
| 22 | `app/api/endpoints/integration_capabilities.py:410` | `result_path_template` | variable | 60% |
| 23 | `app/api/endpoints/integration_capabilities.py:415` | `stateful_restrictions` | variable | 60% |
| 24 | `app/api/endpoints/integration_capabilities.py:421` | `contract_notes` | variable | 60% |
| 25 | `app/api/endpoints/integration_capabilities.py:429` | `options` | variable | 60% |
| 26 | `app/api/endpoints/integration_capabilities.py:436` | `contract_version` | variable | 60% |
| 27 | `app/api/endpoints/integration_capabilities.py:437` | `source_service` | variable | 60% |
| 28 | `app/api/endpoints/integration_capabilities.py:442` | `policy_version` | variable | 60% |
| 29 | `app/api/endpoints/integration_capabilities.py:453` | `model_config` | variable | 60% |
| 30 | `app/api/endpoints/integration_capabilities.py:475` | `get_integration_capabilities` | function | 60% |

## Interpretation

The 60% findings are dominated by Pydantic fields, validators, model configuration, and FastAPI
route handlers that static analysis cannot see as runtime-referenced. The zero-finding 80% scan
means there are no high-confidence production dead-code candidates under the current tool settings.

Future dead-code cleanup should start with a reviewed allowlist for known framework surfaces and
then inspect residual service, adapter, core, and engine candidates in small behavior-preserving
slices. This report is not evidence that API endpoints, model fields, or validators are unused.

## Gate Posture

This is a Phase 1 report-only quality measurement. It does not introduce a CI threshold, branch
failure, or exception policy. Promotion to a blocking gate should wait until a reviewed allowlist is
checked in and false positives have been separated from actionable stale code.
