# Lotus Performance Test Taxonomy Inventory

Report date: 2026-07-10
Branch: `feat/performance-architecture-boundary-refactor`
Mode: regression-blocking test taxonomy inventory; `make quality-test-taxonomy-gate` enforces
minimum API/runtime and contract/governance breadth plus the current uncategorized-test ceiling.

## Purpose

This report captures the shape of the repository test suite using a standard-library AST inventory.
It complements `pytest --collect-only` by measuring test-module and test-function breadth by suite
and quality family without executing tests or requiring coverage data.

## Command

```powershell
python scripts/python_test_taxonomy_inventory.py --limit 30
python scripts/python_test_taxonomy_inventory.py --limit 30 --min-api-runtime-tests 656 --min-contract-governance-tests 131 --max-uncategorized-tests 969
```

## Summary

| Metric | Value |
| --- | ---: |
| Test modules inventoried | 296 |
| Test functions inventoried | 3442 |
| Integration/API/runtime test functions | 656 |
| Contract/governance test functions | 131 |

## Test Functions By Suite

| Suite | Modules | Test functions |
| --- | ---: | ---: |
| benchmarks | 9 | 18 |
| e2e | 1 | 21 |
| integration | 28 | 329 |
| unit | 258 | 3074 |

## Test Functions By Family

| Family | Test functions |
| --- | ---: |
| analytics_domain | 1549 |
| api_or_runtime | 656 |
| contract_or_governance | 131 |
| observability_or_readiness | 338 |
| quality_or_security | 142 |
| uncategorized | 969 |

## Largest Test Modules

| Rank | Module | Suite | Test functions | Families |
| ---: | --- | --- | ---: | --- |
| 1 | `tests/unit/services/test_returns_series_service.py` | unit | 93 | analytics_domain |
| 2 | `tests/unit/app/test_enterprise_readiness_additional.py` | unit | 85 | observability_or_readiness |
| 3 | `tests/unit/services/test_stateful_attribution_input_service.py` | unit | 70 | analytics_domain |
| 4 | `tests/unit/app/test_openapi_enrichment.py` | unit | 61 | api_or_runtime |
| 5 | `tests/unit/services/test_compute_job_store.py` | unit | 61 | observability_or_readiness |
| 6 | `tests/unit/docs/test_public_docs_contract.py` | unit | 59 | contract_or_governance |
| 7 | `tests/unit/engine/test_attribution.py` | unit | 57 | analytics_domain |
| 8 | `tests/unit/services/test_twr_inspection_source_economics.py` | unit | 57 | analytics_domain |
| 9 | `tests/unit/services/test_lineage_metadata_store.py` | unit | 56 | uncategorized |
| 10 | `tests/unit/app/test_contribution_endpoint_helpers.py` | unit | 52 | analytics_domain, api_or_runtime |
| 11 | `tests/unit/services/test_twr_inspection_calculation_consistency.py` | unit | 51 | analytics_domain |
| 12 | `tests/unit/services/test_workspace_summary_service.py` | unit | 50 | uncategorized |
| 13 | `tests/unit/services/test_compute_executor_worker.py` | unit | 46 | uncategorized |
| 14 | `tests/unit/services/test_stateful_input_service.py` | unit | 45 | analytics_domain |
| 15 | `tests/unit/services/test_twr_mode_service.py` | unit | 45 | analytics_domain |
| 16 | `tests/unit/engine/test_mwr.py` | unit | 44 | analytics_domain |
| 17 | `tests/unit/services/test_stateful_benchmark_input_service.py` | unit | 44 | analytics_domain |
| 18 | `tests/integration/test_contribution_api.py` | integration | 41 | analytics_domain, api_or_runtime |
| 19 | `tests/unit/services/test_operator_action_lease_service.py` | unit | 40 | uncategorized |
| 20 | `tests/integration/test_performance_api.py` | integration | 39 | api_or_runtime |
| 21 | `tests/unit/services/test_benchmark_exposure_context_service.py` | unit | 34 | analytics_domain |
| 22 | `tests/unit/test_observability.py` | unit | 34 | observability_or_readiness |
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
contract/governance coverage, but 969 test functions remain uncategorized by the first-wave
taxonomy and should be reduced through normal refactor slices rather than allowed to grow.

The runtime recovery queue-result boundary slice kept the promoted gate stable by classifying
`tests/unit/services/test_runtime_recovery_service.py` as observability/readiness coverage. The
stateful benchmark market-series boundary slice now classifies
`tests/unit/services/test_stateful_input_service.py` as analytics-domain coverage because that suite
protects stateful performance input sourcing, benchmark market-series retrieval, FX/index inputs,
and source-lineage snapshots.
The issue #387 evidence refresh brought the curated report back to measured source truth. Issue
#419 then added runtime build-identity coverage without growing the uncategorized backlog; #420
ratcheted the blocking gate to the current measured preservation baseline: `651`
API/runtime test functions, `128` contract/governance test functions, and an uncategorized-test
ceiling of `982`. Issue #423 then classified configuration-validation tests as quality/security
evidence and HTTP resilience tests as observability/readiness evidence, reducing the current
uncategorized ceiling to `969`. The measured taxonomy also records `338`
observability/readiness test functions, `142` quality/security test functions, and `1549`
analytics-domain test functions. Intentional threshold changes should remain separate,
rationale-backed gate-governance work.
Issue #442 added async polling and application-response header tests, classified them as
API/runtime evidence, and ratcheted the API/runtime floor to `654` while keeping the
uncategorized ceiling at `969`. Issue #454 added cross-endpoint footer parity coverage for TWR,
MWR, Contribution, and Attribution, classifying it as both API/runtime and contract/governance
evidence and ratcheting the floors to `655` API/runtime and `129` contract/governance. Issue #453
added strict fail-fast parity coverage across the same four completed core analytics endpoints,
ratcheting the floors to `656` API/runtime and `130` contract/governance without growing the
uncategorized backlog. Issue #417 added runtime/static trust-telemetry classification coverage,
ratcheting the contract/governance floor to `131` without growing the uncategorized backlog.

This slice promotes the stable part of the taxonomy from report-only measurement to a
regression-blocking evaluation gate. `make quality-test-taxonomy-gate` fails if API/runtime tests
drop below `656`, contract/governance tests drop below `131`, or uncategorized tests rise above
`969`. `make quality-evaluation-gate` now runs both deterministic demo API certification and this
taxonomy gate, so existing Feature Lane, PR Merge Gate, Main Releasability, local `make check`,
local `make ci`, and Quality Baseline workflow enforcement pick it up without duplicating workflow
logic.

## Gate Posture

This is a Phase 2 regression-blocking quality gate for stable taxonomy breadth. It is intentionally
not a strict maturity score: branch coverage, uncategorized-test remediation, and finer taxonomy
labels remain planned improvements. Exceptions should not be soft-failed in CI; if a supported API
or governance test category is intentionally removed, update the gate threshold, scorecard, and
review ledger in the same PR with explicit rationale.
