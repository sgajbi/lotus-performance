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
python scripts/python_test_taxonomy_inventory.py --limit 30 --min-api-runtime-tests 656 --min-contract-governance-tests 136 --max-uncategorized-tests 969
```

## Summary

| Metric | Value |
| --- | ---: |
| Test modules inventoried | 304 |
| Test functions inventoried | 3506 |
| Integration/API/runtime test functions | 684 |
| Contract/governance test functions | 147 |

## Test Functions By Suite

| Suite | Modules | Test functions |
| --- | ---: | ---: |
| benchmarks | 9 | 18 |
| e2e | 1 | 21 |
| integration | 28 | 338 |
| unit | 266 | 3129 |

## Test Functions By Family

| Family | Test functions |
| --- | ---: |
| analytics_domain | 1570 |
| api_or_runtime | 684 |
| contract_or_governance | 147 |
| observability_or_readiness | 350 |
| quality_or_security | 161 |
| uncategorized | 950 |

## Largest Test Modules

| Rank | Module | Suite | Test functions | Families |
| ---: | --- | --- | ---: | --- |
| 1 | `tests/unit/services/test_returns_series_service.py` | unit | 96 | analytics_domain |
| 2 | `tests/unit/app/test_enterprise_readiness_additional.py` | unit | 85 | observability_or_readiness |
| 3 | `tests/unit/services/test_stateful_attribution_input_service.py` | unit | 70 | analytics_domain |
| 4 | `tests/unit/docs/test_public_docs_contract.py` | unit | 63 | contract_or_governance |
| 5 | `tests/unit/app/test_openapi_enrichment.py` | unit | 61 | api_or_runtime |
| 6 | `tests/unit/services/test_compute_job_store.py` | unit | 61 | observability_or_readiness |
| 7 | `tests/unit/engine/test_attribution.py` | unit | 57 | analytics_domain |
| 8 | `tests/unit/services/test_twr_inspection_source_economics.py` | unit | 57 | analytics_domain |
| 9 | `tests/unit/services/test_lineage_metadata_store.py` | unit | 56 | uncategorized |
| 10 | `tests/unit/app/test_contribution_endpoint_helpers.py` | unit | 52 | analytics_domain, api_or_runtime |
| 11 | `tests/unit/services/test_twr_inspection_calculation_consistency.py` | unit | 51 | analytics_domain |
| 12 | `tests/unit/services/test_workspace_summary_service.py` | unit | 50 | uncategorized |
| 13 | `tests/unit/services/test_stateful_input_service.py` | unit | 47 | analytics_domain |
| 14 | `tests/unit/services/test_compute_executor_worker.py` | unit | 46 | uncategorized |
| 15 | `tests/unit/services/test_twr_mode_service.py` | unit | 45 | analytics_domain |
| 16 | `tests/unit/engine/test_mwr.py` | unit | 44 | analytics_domain |
| 17 | `tests/unit/services/test_stateful_benchmark_input_service.py` | unit | 44 | analytics_domain |
| 18 | `tests/integration/test_contribution_api.py` | integration | 41 | analytics_domain, api_or_runtime |
| 19 | `tests/unit/services/test_operator_action_lease_service.py` | unit | 40 | uncategorized |
| 20 | `tests/integration/test_performance_api.py` | integration | 39 | api_or_runtime |
| 21 | `tests/unit/services/test_benchmark_exposure_context_service.py` | unit | 35 | analytics_domain |
| 22 | `tests/unit/test_observability.py` | unit | 34 | observability_or_readiness |
| 23 | `tests/unit/engine/test_contribution.py` | unit | 33 | analytics_domain |
| 24 | `tests/unit/models/test_twr_requests.py` | unit | 32 | analytics_domain |
| 25 | `tests/unit/services/test_twr_inspection_reconciliation.py` | unit | 32 | analytics_domain |
| 26 | `tests/integration/test_returns_series_api.py` | integration | 31 | analytics_domain, api_or_runtime |
| 27 | `tests/unit/models/test_workspace_summary_models.py` | unit | 31 | uncategorized |
| 28 | `tests/unit/services/test_twr_inspection_service.py` | unit | 31 | analytics_domain |
| 29 | `tests/unit/app/test_enterprise_readiness.py` | unit | 30 | observability_or_readiness |
| 30 | `tests/unit/services/test_operator_action_replay_service.py` | unit | 30 | uncategorized |

## Interpretation

The AST inventory counts test function definitions, while `pytest --collect-only` counts expanded
pytest items including parametrized cases. The two values are intentionally different and
complementary: collected tests show execution breadth, while this report shows source test-module
and test-function distribution. The current suite has meaningful API/runtime and
contract/governance coverage, but 950 test functions remain uncategorized by the first-wave
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
observability/readiness test functions, `145` quality/security test functions, and `1549`
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
Issue #424 added executable durable schema apply/verify coverage and classified schema-apply
command tests as quality/security evidence while keeping the uncategorized ceiling at `969`.
Issue #425 added returns-series strict-intersection fill semantics coverage, raising the measured
API/runtime count to `658` and analytics-domain count to `1552` without growing uncategorized tests.
Issue #452 added docs-contract coverage for the RFC-020 endpoint-specific multi-currency support
matrix, raising the measured contract/governance count to `132` without changing enforced floors.
Issue #451 added docs-contract coverage for the RFC-021 gross/net support baseline, raising the
measured contract/governance count to `133` without changing enforced floors. Issue #449 added
operator calculation-id prefix validation, OpenAPI, integration, and adapter-guard coverage,
raising the measured API/runtime count to `661` and analytics-domain count to `1554` while keeping
the uncategorized backlog flat. Issue #448 added execution-lineage lifecycle tests and classified
lineage-worker tests as observability/readiness evidence, raising that family to `350` and reducing
the measured uncategorized backlog to `958` without weakening the enforced ceiling.
Issue #447 added stateful portfolio source port contract tests, raising source test functions to
`3458` and analytics-domain tests to `1556` while keeping API/runtime, contract/governance,
observability/readiness, quality/security, and uncategorized counts unchanged. Issue #446 added
lineage artifact classification/minimization route and service coverage, raising source test
functions to `3461`, API/runtime tests to `663`, and uncategorized tests to `959` while preserving
the existing `969` uncategorized ceiling.
Issue #444 added runtime-retention restart-safety, failure-resume, and failed-replay tests, raising
source test functions to `3465` and uncategorized tests to `963` while preserving the existing
`969` uncategorized ceiling. Issue #443 added docs-contract coverage for the async SLO/capacity
contract, raising source test functions to `3466` and contract/governance tests to `134` without
growing the uncategorized backlog. Issue #441 added upstream dependency inventory contract tests,
raising source test functions to `3468` and contract/governance tests to `136` without growing the
uncategorized backlog. Issue #440 added first-party and third-party license compliance gate tests,
raising source test functions to `3473` and quality/security tests to `150` without growing the
uncategorized backlog or contract/governance floor. Issue #439 added real restore-validation drill
coverage, raising source test functions to `3475` and uncategorized tests to `965` while preserving
the existing `969` uncategorized ceiling. The CI-observed LGPL classifier alias regression fix
added license-policy coverage, raising source test functions to `3476` and quality/security tests
to `151`. Issue #438 added durable database engine policy coverage for SQLite/PostgreSQL engine
options plus shared execution-registry commit/rollback behavior, raising source test functions to
`3480` and analytics-domain tests to `1560` without growing the uncategorized backlog.
Issue #436 added runtime-retention legal-hold source and exclusion coverage, raising source test
functions to `3485`, contract/governance tests to `140`, and uncategorized tests to `966` while
preserving the existing `969` ceiling.
Issue #435 added governed MARKET calendar source, future-holiday, diagnostics metadata, and
out-of-horizon rejection coverage, raising source test functions to `3488`, API/runtime tests to
`664`, and analytics-domain tests to `1563` while preserving the existing uncategorized ceiling.
Issue #434 added shared retrieval metadata anti-corruption coverage plus benchmark exposure API
degraded-telemetry evidence, raising source test functions to `3492`, API/runtime tests to `665`,
analytics-domain tests to `1565`, and uncategorized tests to `968` while preserving the existing
`969` uncategorized ceiling. Issue #433 added stateful async promotion conflict coverage and
classified stateful execution policy plus submission fencing tests as API/runtime evidence,
raising source test functions to `3493`, API/runtime tests to `684`, and reducing uncategorized
tests to `950` while preserving the existing `969` uncategorized ceiling.
Issue #432 added container runtime contract coverage for Dockerfile, Makefile, Compose, and worker
healthchecks plus production dependency-scope regression coverage, raising source test functions
to `3499`, contract/governance tests to `146`, and quality/security tests to `157` without growing
the uncategorized backlog. Issue #431 added calculation-engine-version manifest and static-gate
coverage plus public-doc reproducibility guards, raising source test functions to `3506`,
contract/governance tests to `147`, quality/security tests to `161`, and analytics-domain tests to
`1570` while preserving API/runtime and uncategorized counts.

This slice promotes the stable part of the taxonomy from report-only measurement to a
regression-blocking evaluation gate. `make quality-test-taxonomy-gate` fails if API/runtime tests
drop below `656`, contract/governance tests drop below `136`, or uncategorized tests rise above
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
