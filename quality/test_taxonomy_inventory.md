# Lotus Performance Test Taxonomy Inventory

Report date: 2026-07-04
Branch: `fix/issue-397-inspection-artifact-authz`
Mode: regression-blocking test taxonomy inventory; `make quality-test-taxonomy-gate` enforces
minimum API/runtime and contract/governance breadth plus the current uncategorized-test ceiling.

## Purpose

This report captures the shape of the repository test suite using a standard-library AST inventory.
It complements `pytest --collect-only` by measuring test-module and test-function breadth by suite
and quality family without executing tests or requiring coverage data.

## Command

```powershell
python scripts/python_test_taxonomy_inventory.py --limit 30
python scripts/python_test_taxonomy_inventory.py --limit 30 --min-api-runtime-tests 607 --min-contract-governance-tests 111 --max-uncategorized-tests 1148
python scripts/python_test_taxonomy_inventory.py --limit 30 --min-api-runtime-tests 643 --min-contract-governance-tests 126 --max-uncategorized-tests 1019
```

## Summary

| Metric | Value |
| --- | ---: |
| Test modules inventoried | 289 |
| Test functions inventoried | 3413 |
| Integration/API/runtime test functions | 644 |
| Contract/governance test functions | 126 |

## Test Functions By Suite

| Suite | Modules | Test functions |
| --- | ---: | ---: |
| benchmarks | 9 | 18 |
| e2e | 1 | 21 |
| integration | 26 | 325 |
| unit | 253 | 3049 |

## Test Functions By Family

| Family | Test functions |
| --- | ---: |
| analytics_domain | 1539 |
| api_or_runtime | 644 |
| contract_or_governance | 126 |
| observability_or_readiness | 284 |
| quality_or_security | 137 |
| uncategorized | 1019 |

## Largest Test Modules

| Rank | Module | Suite | Test functions | Families |
| ---: | --- | --- | ---: | --- |
| 1 | `tests/unit/services/test_returns_series_service.py` | unit | 88 | analytics_domain |
| 2 | `tests/unit/app/test_enterprise_readiness_additional.py` | unit | 85 | observability_or_readiness |
| 3 | `tests/unit/services/test_stateful_attribution_input_service.py` | unit | 70 | analytics_domain |
| 4 | `tests/unit/app/test_openapi_enrichment.py` | unit | 61 | api_or_runtime |
| 5 | `tests/unit/services/test_compute_job_store.py` | unit | 61 | observability_or_readiness |
| 6 | `tests/unit/docs/test_public_docs_contract.py` | unit | 58 | contract_or_governance |
| 7 | `tests/unit/engine/test_attribution.py` | unit | 57 | analytics_domain |
| 8 | `tests/unit/services/test_twr_inspection_source_economics.py` | unit | 57 | analytics_domain |
| 9 | `tests/unit/services/test_lineage_metadata_store.py` | unit | 56 | uncategorized |
| 10 | `tests/unit/app/test_contribution_endpoint_helpers.py` | unit | 52 | analytics_domain, api_or_runtime |
| 11 | `tests/unit/services/test_twr_inspection_calculation_consistency.py` | unit | 51 | analytics_domain |
| 12 | `tests/unit/services/test_workspace_summary_service.py` | unit | 50 | uncategorized |
| 13 | `tests/unit/services/test_compute_executor_worker.py` | unit | 46 | uncategorized |
| 14 | `tests/unit/services/test_stateful_input_service.py` | unit | 45 | analytics_domain |
| 15 | `tests/unit/services/test_twr_mode_service.py` | unit | 45 | analytics_domain |
| 16 | `tests/unit/services/test_stateful_benchmark_input_service.py` | unit | 44 | analytics_domain |
| 17 | `tests/unit/engine/test_mwr.py` | unit | 42 | analytics_domain |
| 18 | `tests/integration/test_contribution_api.py` | integration | 41 | analytics_domain, api_or_runtime |
| 19 | `tests/unit/services/test_operator_action_lease_service.py` | unit | 40 | uncategorized |
| 20 | `tests/integration/test_performance_api.py` | integration | 39 | api_or_runtime |
| 21 | `tests/unit/services/test_benchmark_exposure_context_service.py` | unit | 34 | analytics_domain |
| 22 | `tests/unit/test_observability.py` | unit | 34 | uncategorized |
| 23 | `tests/unit/engine/test_contribution.py` | unit | 33 | analytics_domain |
| 24 | `tests/unit/models/test_twr_requests.py` | unit | 32 | analytics_domain |
| 25 | `tests/unit/services/test_twr_inspection_reconciliation.py` | unit | 32 | analytics_domain |
| 26 | `tests/unit/models/test_workspace_summary_models.py` | unit | 31 | uncategorized |
| 27 | `tests/unit/services/test_twr_inspection_service.py` | unit | 31 | analytics_domain |
| 28 | `tests/unit/app/test_enterprise_readiness.py` | unit | 30 | observability_or_readiness |
| 29 | `tests/unit/engine/test_composites.py` | unit | 29 | analytics_domain |
| 30 | `tests/unit/services/test_operator_action_replay_service.py` | unit | 29 | uncategorized |

## Interpretation

The AST inventory counts test function definitions, while `pytest --collect-only` counts expanded
pytest items including parametrized cases. The two values are intentionally different and
complementary: collected tests show execution breadth, while this report shows source test-module
and test-function distribution. The current suite has meaningful API/runtime and
contract/governance coverage, but 1019 test functions remain uncategorized by the first-wave
taxonomy and should be reduced through normal refactor slices rather than allowed to grow.

The runtime recovery queue-result boundary slice kept the promoted gate stable by classifying
`tests/unit/services/test_runtime_recovery_service.py` as observability/readiness coverage. The
stateful benchmark market-series boundary slice now classifies
`tests/unit/services/test_stateful_input_service.py` as analytics-domain coverage because that suite
protects stateful performance input sourcing, benchmark market-series retrieval, FX/index inputs,
and source-lineage snapshots.
The issue #387 evidence refresh keeps the blocking gate threshold posture unchanged while bringing
the curated report back to measured source truth. Current measured breadth is `644` API/runtime test
functions, `126` contract/governance test functions, `284` observability/readiness test functions,
`1539` analytics-domain test functions, and `1019` uncategorized test functions. The enforced
command remains at the accepted regression floor of `607` API/runtime tests and ceiling `1148`;
this slice also passed a tighter local preservation command requiring at least `643` API/runtime tests, `126`
contract/governance tests, and `1019` uncategorized tests. Intentional threshold changes should
remain separate, rationale-backed gate-governance work.

This slice promotes the stable part of the taxonomy from report-only measurement to a
regression-blocking evaluation gate. `make quality-test-taxonomy-gate` fails if API/runtime tests
drop below `607`, contract/governance tests drop below `111`, or uncategorized tests rise above
`1148`. `make quality-evaluation-gate` now runs both deterministic demo API certification and this
taxonomy gate, so existing Feature Lane, PR Merge Gate, Main Releasability, local `make check`,
local `make ci`, and Quality Baseline workflow enforcement pick it up without duplicating workflow
logic.

## Gate Posture

This is a Phase 2 regression-blocking quality gate for stable taxonomy breadth. It is intentionally
not a strict maturity score: branch coverage, uncategorized-test remediation, and finer taxonomy
labels remain planned improvements. Exceptions should not be soft-failed in CI; if a supported API
or governance test category is intentionally removed, update the gate threshold, scorecard, and
review ledger in the same PR with explicit rationale.
