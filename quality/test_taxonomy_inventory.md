# Lotus Performance Test Taxonomy Inventory

Report date: 2026-08-26
Branch: `fix/480-serialize-durable-schema`
Mode: regression-blocking test taxonomy inventory; `make quality-test-taxonomy-gate` enforces
minimum API/runtime and contract/governance breadth plus the current uncategorized-test ceiling.

## Purpose

This report captures the shape of the repository test suite using a standard-library AST inventory.
It complements `pytest --collect-only` by measuring test-module and test-function breadth by suite
and quality family without executing tests or requiring coverage data.

## Command

```powershell
python scripts/python_test_taxonomy_inventory.py --limit 30
python scripts/python_test_taxonomy_inventory.py --limit 30 --min-api-runtime-tests 656 --min-contract-governance-tests 136 --max-uncategorized-tests 876
```

## Summary

| Metric | Value |
| --- | ---: |
| Test modules inventoried | 313 |
| Test functions inventoried | 3596 |
| Integration/API/runtime test functions | 690 |
| Contract/governance test functions | 159 |

## Test Functions By Suite

| Suite | Modules | Test functions |
| --- | ---: | ---: |
| benchmarks | 9 | 19 |
| e2e | 1 | 21 |
| integration | 28 | 341 |
| unit | 275 | 3215 |

## Test Functions By Family

A module can belong to more than one family - `_families_for_path` returns every family a path
matches - so these counts **overlap by design and do not sum to the total**. The suite table
above does sum to it, because a module belongs to exactly one suite.

| Family | Test functions |
| --- | ---: |
| analytics_domain | 1672 |
| api_or_runtime | 690 |
| contract_or_governance | 159 |
| observability_or_readiness | 375 |
| quality_or_security | 186 |
| uncategorized | 876 |

## Largest Test Modules

| Rank | Module | Suite | Test functions | Families |
| ---: | --- | --- | ---: | --- |
| 1 | `tests/unit/services/test_returns_series_service.py` | unit | 96 | analytics_domain |
| 2 | `tests/unit/app/test_enterprise_readiness_additional.py` | unit | 87 | observability_or_readiness |
| 3 | `tests/unit/services/test_stateful_attribution_input_service.py` | unit | 70 | analytics_domain |
| 4 | `tests/unit/docs/test_public_docs_contract.py` | unit | 67 | contract_or_governance |
| 5 | `tests/unit/services/test_compute_job_store.py` | unit | 67 | observability_or_readiness |
| 6 | `tests/unit/app/test_openapi_enrichment.py` | unit | 61 | api_or_runtime |
| 7 | `tests/unit/services/test_lineage_metadata_store.py` | unit | 60 | uncategorized |
| 8 | `tests/unit/engine/test_attribution.py` | unit | 57 | analytics_domain |
| 9 | `tests/unit/services/test_twr_inspection_source_economics.py` | unit | 57 | analytics_domain |
| 10 | `tests/unit/app/test_contribution_endpoint_helpers.py` | unit | 52 | analytics_domain, api_or_runtime |
| 11 | `tests/unit/services/test_compute_executor_worker.py` | unit | 51 | uncategorized |
| 12 | `tests/unit/services/test_twr_inspection_calculation_consistency.py` | unit | 51 | analytics_domain |
| 13 | `tests/unit/services/test_workspace_summary_service.py` | unit | 50 | analytics_domain |
| 14 | `tests/unit/services/test_stateful_input_service.py` | unit | 47 | analytics_domain |
| 15 | `tests/unit/services/test_twr_mode_service.py` | unit | 45 | analytics_domain |
| 16 | `tests/unit/engine/test_mwr.py` | unit | 44 | analytics_domain |
| 17 | `tests/unit/services/test_stateful_benchmark_input_service.py` | unit | 44 | analytics_domain |
| 18 | `tests/integration/test_contribution_api.py` | integration | 41 | analytics_domain, api_or_runtime |
| 19 | `tests/integration/test_performance_api.py` | integration | 40 | api_or_runtime |
| 20 | `tests/unit/services/test_operator_action_lease_service.py` | unit | 40 | uncategorized |
| 21 | `tests/unit/services/test_benchmark_exposure_context_service.py` | unit | 35 | analytics_domain |
| 22 | `tests/unit/test_observability.py` | unit | 34 | observability_or_readiness |
| 23 | `tests/unit/engine/test_contribution.py` | unit | 33 | analytics_domain |
| 24 | `tests/unit/models/test_twr_requests.py` | unit | 32 | analytics_domain |
| 25 | `tests/unit/services/test_twr_inspection_reconciliation.py` | unit | 32 | analytics_domain |
| 26 | `tests/integration/test_returns_series_api.py` | integration | 31 | analytics_domain, api_or_runtime |
| 27 | `tests/unit/app/test_enterprise_readiness.py` | unit | 31 | observability_or_readiness |
| 28 | `tests/unit/models/test_workspace_summary_models.py` | unit | 31 | analytics_domain |
| 29 | `tests/unit/services/test_twr_inspection_service.py` | unit | 31 | analytics_domain |
| 30 | `tests/unit/services/test_operator_action_replay_service.py` | unit | 30 | uncategorized |

## Interpretation

The AST inventory counts test function definitions, while `pytest --collect-only` counts expanded
pytest items including parametrized cases. The two values are intentionally different and
complementary: collected tests show execution breadth, while this report shows source test-module
and test-function distribution. The current suite has meaningful API/runtime and
contract/governance coverage, but 876 test functions remain uncategorized by the first-wave
taxonomy and should be reduced through normal refactor slices rather than allowed to grow. The
largest remaining groups are `runtime` (190) and `operator` (145), which have no family mapping
yet - see issue #478 for why one was not invented to move the number.

The durable-schema correction classifies executable `durable_schema_apply` tests as
observability/readiness evidence and the `durable_schema_inventory_check` Markdown validation tests
as contract/governance evidence. The three inventory checks therefore leave `uncategorized`
without being presented as runtime proof; the two executable apply tests carry both their existing
quality/security role and the readiness role they exercise.

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
Issue #430 added ordered-array reproducibility hash-contract API and public-doc governance coverage,
raising source test functions to `3509`, API/runtime tests to `685`, contract/governance tests to
`148`, and uncategorized tests to `951` while preserving the existing ceiling. Issue #429 added
operator-navigation mapping and endpoint regression coverage for workspace-summary runtime
work-item and recovery result links, raising source test functions to `3513` and API/runtime tests
to `689` without growing the uncategorized backlog. Issue #428 added settings-validation and
production runtime-threshold fail-closed coverage, raising source test functions to `3518`,
observability/readiness tests to `353`, and quality/security tests to `163` without growing the
uncategorized backlog. Issue #426 added performance-characterization CI wiring, public-doc
governance, durable PostgreSQL option preservation, and lineage inspection hot-path query/index
coverage, raising source test functions to `3523`, contract/governance tests to `149`,
quality/security tests to `164`, analytics-domain tests to `1571`, and uncategorized tests to
`953` while preserving the existing `969` uncategorized ceiling. Issue #427 added alert-dashboard
coverage regression proof for returns-series supportability monitoring, raising source test
functions to `3524`, observability/readiness tests to `354`, and quality/security tests to `165`
while preserving the existing uncategorized ceiling. The PR review fix for legacy lineage manifests
and non-finite retrieval metadata added two regression tests, raising source test functions to
`3526`, API/runtime tests to `690`, and uncategorized tests to `954` while preserving the existing
uncategorized ceiling. The RFC-0002 Idea opportunity source-proof slice added four source-safe
runtime evidence tests, raising inventoried modules to `309`, source test functions to `3538`, and
uncategorized tests to `958` while preserving the existing `969` uncategorized ceiling.
The PR review fix added execution-registry identity preservation regression coverage, raising source
test functions to `3539` and uncategorized tests to `959` while staying below the same ceiling.
The blocker-contract review fix added exact Idea blocker preservation regression coverage, raising
source test functions to `3540` and uncategorized tests to `960` while staying below the same ceiling.
The canonical identity and missing-benchmark readiness review fixes added two regression tests,
raising source test functions to `3542` and uncategorized tests to `962` while staying below the same
ceiling.
Issue #467 workspace-summary lineage terminality coverage added initial same-calculation
materialization and result-publication tests. The review fix added six more lease-renewal,
active-lineage-lease wait, and execution-stage terminality regressions, raising source test
functions to `3554`, observability/readiness tests to `361`, and uncategorized tests to `967` while
preserving the existing `969` uncategorized ceiling.
The compute lease-acquisition review fix added per-acquisition owner and in-progress stage polling
regressions, raising source test functions to `3558`, observability/readiness tests to `364`, and
uncategorized tests to `968` while preserving the existing `969` uncategorized ceiling.
The follow-up lease-fence preservation fix added schema-upgrade proof for the internal
`lease_owner_id` acquisition fence, raising source test functions to `3559` and
observability/readiness tests to `365` while preserving the existing uncategorized count and ceiling.
The final PR review fix added queued-batch lease-expiry, PostgreSQL idempotent schema-upgrade, and
Docker stderr diagnostic regressions, raising source test functions to `3562`,
observability/readiness tests to `366`, quality/security tests to `170`, and uncategorized tests to
`969` while preserving the existing uncategorized ceiling.
Issue #472 added monetary-float allowlist governance tests - an orphan-retirement check, a check
that the two reviewed entries name their specific finding and migration issue, and a check that the
`annualize_return` ratio is not re-added as a dated allowance - raising source test functions from
`3562` to `3565` and quality/security tests from `170` to `173` without growing the uncategorized
backlog or moving the API/runtime and contract/governance floors.
The same issue then added a docs-contract check that the present-tense governed-inventory paragraph
in `quality/ci_quality_gates.md` states no superseded total, and that this report's own family and
suite tables match the measurement - the earlier check asserted the measured summary appeared
somewhere in that document, which a regenerated table row satisfied while hand-written prose below
it stayed stale - raising source test functions from `3565` to `3566` and contract/governance tests
from `154` to `155`, again without moving any enforced floor or ceiling.
Issue #475 then found the ceiling was measuring the classifier rather than the tree. The workspace
analytics surface had no token in `_families_for_path`, so all of its tests fell to
`uncategorized` - 90 across three modules, the third-largest contributor behind `runtime` and
`operator`. Because the gate caps uncategorized tests, adding any test to that surface turned it
red, and the only way to go green was to edit a governance threshold. Adding `workspace` to the
`analytics_domain` tokens moves those 90 tests to the family they always belonged to, taking
uncategorized from `969` to `879` and analytics-domain tests from `1571` to `1662`. The ceiling is
re-banked to `879` in the same change: leaving it at `969` would have converted a classification
fix into 90 tests of unearned slack. Note the token matches four modules, not the three that were
uncategorized; `tests/unit/app/test_workspace_summary_openapi_contract.py` was already classified
and now carries `analytics_domain` as well, which is why analytics-domain rose `+91` while
uncategorized fell `-90`.

Review then found the guard covered four tokens by hand against thirty-nine in the classifier, so
thirty-five could rot into vacuous truth unchecked. The token list is now derived from
`_families_for_path` by AST, and deriving it immediately found two tokens - `logging` and
`correlation` - that matched no module at all and were removed; family counts were unchanged by
their removal, confirming they classified nothing. Review also found the documented ceiling still
stated `969` in this report's `Command` block and in `REPOSITORY-ENGINEERING-CONTEXT.md` - looser
than the enforced `879`, so anyone running the documented command got exactly the slack the change
removed, and no gate could see it. The context file no longer restates the thresholds at all, and a
new check asserts no document states a threshold the gate does not enforce, excluding only
`docs/architecture/CODEBASE-REVIEW-LEDGER.md`, whose dated rows are historical evidence that would
be falsified by rewriting. Guard tests under `tests/unit/scripts/` raised inventoried modules from
`309` to `311`, source test functions from `3566` to `3578`, and quality/security tests from `173`
to `185`.

`runtime` (190) and `operator` (145) are deliberately left unclassified: neither maps to one family
without a judgement that deserves its own evidence. Together they are 38% of the remaining ceiling,
so the defect fixed here is still live for both surfaces - recorded as issue #478 rather than left
as an unexplained gap.

This slice promotes the stable part of the taxonomy from report-only measurement to a
regression-blocking evaluation gate. `make quality-test-taxonomy-gate` fails if API/runtime tests
drop below `656`, contract/governance tests drop below `136`, or uncategorized tests rise above
`879`. `make quality-evaluation-gate` now runs both deterministic demo API certification and this
taxonomy gate, so existing Feature Lane, PR Merge Gate, Main Releasability, local `make check`,
local `make ci`, and Quality Baseline workflow enforcement pick it up without duplicating workflow
logic.

## Gate Posture

This is a Phase 2 regression-blocking quality gate for stable taxonomy breadth. It is intentionally
not a strict maturity score: branch coverage, uncategorized-test remediation, and finer taxonomy
labels remain planned improvements. The uncategorized ceiling is banked at the measured value with
no headroom and is asserted as such by
`tests/unit/scripts/test_test_taxonomy_classification.py`, so it cannot be raised to absorb new
unclassified tests; a surface that genuinely belongs to a family is classified instead, and the
ceiling is re-banked downward in the same change.

**Wiki disposition for the #475 change: no wiki update required, recorded explicitly rather than
omitted.** The repo-local wiki carries no statement of the taxonomy gate, its thresholds, or the
uncategorized count - `grep -n "taxonomy\|uncategoriz\|969\|879" wiki/*.md` returns nothing across
all 21 pages, including `Validation-and-CI.md` and `Development-Workflow.md`. The gate is a
contributor-facing CI threshold, not operator-facing runtime behaviour: no command an operator runs,
no API response, and no runbook step changes. Wiki truth would need updating if the wiki began
publishing gate thresholds, which is a separate decision from this change. Exceptions should not be soft-failed in CI; if a supported API
or governance test category is intentionally removed, update the gate threshold, scorecard, and
review ledger in the same PR with explicit rationale.
