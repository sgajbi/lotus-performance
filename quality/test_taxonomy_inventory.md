# Lotus Performance Test Taxonomy Inventory

Report date: 2026-10-04
Branch: `fix/retention-operator-entrypoint`
Mode: regression-blocking test taxonomy inventory; `make quality-test-taxonomy-gate` enforces
minimum API/runtime and contract/governance breadth plus the current uncategorized-test ceiling.

## Purpose

This report captures the shape of the repository test suite using a standard-library AST inventory.
It complements `pytest --collect-only` by measuring test-module and test-function breadth by suite
and quality family without executing tests or requiring coverage data.

## Command

```powershell
python scripts/python_test_taxonomy_inventory.py --limit 30
python scripts/python_test_taxonomy_inventory.py --limit 30 --min-api-runtime-tests 656 --min-contract-governance-tests 136 --max-uncategorized-tests 558
```

## Summary

| Metric | Value |
| --- | ---: |
| Test modules inventoried | 368 |
| Test functions inventoried | 4465 |
| Integration/API/runtime test functions | 946 |
| Contract/governance test functions | 224 |

## Test Functions By Suite

| Suite | Modules | Test functions |
| --- | ---: | ---: |
| benchmarks | 11 | 68 |
| e2e | 1 | 21 |
| integration | 37 | 494 |
| unit | 319 | 3882 |

## Test Functions By Family

A module can belong to more than one family - `_families_for_path` returns every family a path
matches - so these counts **overlap by design and do not sum to the total**. The suite table
above does sum to it, because a module belongs to exactly one suite.

| Family | Test functions |
| --- | ---: |
| analytics_domain | 2275 |
| api_or_runtime | 946 |
| contract_or_governance | 224 |
| observability_or_readiness | 752 |
| quality_or_security | 326 |
| uncategorized | 558 |

The #619 source-refusal slice classifies the exact existing stateful upstream error adapter
module as API/runtime and readiness evidence. Ten actual source functions move from
uncategorized; unrelated stateful/error paths remain unclassified. The observed count is 558;
the separately declared Make policy ceiling is tightened from 563 to 558, consistent with the
existing banked-ratchet guard. Breadth floors remain unchanged. This inventory is not live Core
acceptance or calculation/source readiness certification.

## Largest Test Modules

| Rank | Module | Suite | Test functions | Families |
| ---: | --- | --- | ---: | --- |
| 1 | `tests/unit/services/test_returns_series_service.py` | unit | 96 | analytics_domain |
| 2 | `tests/unit/app/test_enterprise_readiness_additional.py` | unit | 88 | observability_or_readiness |
| 3 | `tests/integration/test_contribution_api.py` | integration | 78 | analytics_domain, api_or_runtime |
| 4 | `tests/unit/docs/test_public_docs_contract.py` | unit | 71 | contract_or_governance |
| 5 | `tests/unit/services/test_stateful_attribution_input_service.py` | unit | 71 | analytics_domain |
| 6 | `tests/unit/services/test_compute_job_store.py` | unit | 70 | observability_or_readiness |
| 7 | `tests/integration/test_performance_api.py` | integration | 67 | api_or_runtime |
| 8 | `tests/unit/engine/test_attribution.py` | unit | 62 | analytics_domain |
| 9 | `tests/unit/services/test_lineage_metadata_store.py` | unit | 62 | observability_or_readiness |
| 10 | `tests/unit/services/test_workspace_summary_service.py` | unit | 62 | analytics_domain |
| 11 | `tests/unit/app/test_openapi_enrichment.py` | unit | 61 | api_or_runtime |
| 12 | `tests/unit/services/test_twr_inspection_source_economics.py` | unit | 58 | analytics_domain |
| 13 | `tests/unit/services/test_compute_executor_worker.py` | unit | 56 | observability_or_readiness |
| 14 | `tests/unit/app/test_contribution_endpoint_helpers.py` | unit | 55 | analytics_domain, api_or_runtime |
| 15 | `tests/unit/services/test_stateful_input_service.py` | unit | 55 | analytics_domain |
| 16 | `tests/unit/engine/test_mwr.py` | unit | 54 | analytics_domain |
| 17 | `tests/unit/services/test_twr_inspection_calculation_consistency.py` | unit | 53 | analytics_domain |
| 18 | `tests/unit/services/test_twr_mode_service.py` | unit | 49 | analytics_domain |
| 19 | `tests/unit/services/test_composite_metadata_store.py` | unit | 44 | analytics_domain |
| 20 | `tests/unit/services/test_stateful_benchmark_input_service.py` | unit | 44 | analytics_domain |
| 21 | `tests/unit/engine/test_contribution.py` | unit | 43 | analytics_domain |
| 22 | `tests/unit/services/test_benchmark_exposure_context_service.py` | unit | 41 | analytics_domain |
| 23 | `tests/unit/services/test_stateful_contribution_input_service.py` | unit | 41 | analytics_domain |
| 24 | `tests/unit/services/test_operator_action_lease_service.py` | unit | 40 | uncategorized |
| 25 | `tests/integration/test_attribution_api.py` | integration | 39 | analytics_domain, api_or_runtime |
| 26 | `tests/unit/models/test_twr_requests.py` | unit | 38 | analytics_domain |
| 27 | `tests/unit/engine/test_ror.py` | unit | 37 | analytics_domain |
| 28 | `tests/unit/test_observability.py` | unit | 37 | observability_or_readiness |
| 29 | `tests/unit/models/test_workspace_summary_models.py` | unit | 36 | analytics_domain |
| 30 | `tests/unit/services/test_twr_inspection_reconciliation.py` | unit | 32 | analytics_domain |

The #502 request-path proof added a module driving the real application over HTTP for tenant admission - admitted, absent, blank and concurrent two-tenant requests, each asserting the outbound Core call - raising inventoried modules to `317`, source test functions to `3634`, and API/runtime tests to `699`. Later review fixes in the same PR added the padded-tenant refusals and the returns-series authority regression, which are counted in those figures. Uncategorized tests are unchanged at `876`: every added module classifies as api_or_runtime, so the ceiling this gate governs was neither approached nor raised.

The container-scan composition proof added one module and two documentation invariants. The module asserts that a workflow job reaches the image scan exactly once and that the judged report is the one produced and uploaded, which is a property of how the lane composes Make targets rather than of any single target. The invariant requires every documented `make` invocation to name a target that exists in the Makefile, so a reference to a target that does not exist fails without anyone having to remember which target was renamed. Inventoried modules rise to `322`, source test functions to `3664`, quality/security tests to `226`, and contract/governance tests to `178`. Uncategorized tests are unchanged at `876`, exactly the ceiling this gate governs: neither addition classifies as uncategorized, so the ceiling was neither approached nor raised.

The #504 durable-tenant-authority slice added the worker authority restore and its admission proof, and closed a classifier gap that had been hiding the surface it touches. `compute_executor_worker` was absent from the `observability_or_readiness` token list while its own `compute_job_store` and its sibling `lineage_worker` were both present, so every test of the worker fell to `uncategorized`. That is the same shape as the `workspace` omission recorded above and the dead `logging`/`correlation` tokens beside it: a classification rule that never matched the module it was meant to cover. Closing it moves 54 existing tests out of `uncategorized` and the four added here into `observability_or_readiness`, so source test functions rise to `3669`, API/runtime tests to `701`, and uncategorized tests **fall** from `876` to `825`. The ceiling is re-banked down to `825` rather than raised, and it is banked at exact equality: the gate passes at `825` and fails at `824`, verified both ways. A ceiling that moves down because a surface became classifiable is the outcome this gate exists to produce; one that moves up to accommodate the tests being added is the outcome it exists to prevent.

The #511 Compose-provenance slice added one module proving both build paths carry the same arguments, that all five services built from `docker-compose.yml` receive them, and that a hostile branch name survives as data. Inventoried modules rise to `323`, source test functions to `3,678`, and quality/security tests to `235`. Uncategorized tests are unchanged at `825`, exactly the ceiling this gate governs: the module lives under `tests/unit/scripts/`, which the classifier already maps, so the ceiling was neither approached nor raised.

Review of the same slice added two more: local configuration cannot enter the build context (`.env` is gitignored, so a tree carrying one measures clean and the image would ship it under a claim of an exact commit), and volatile metadata is applied after the expensive layers so a per-second build timestamp does not evict the dependency cache. Source test functions rise to `3,680` and quality/security tests to `237`; uncategorized is unchanged at `825`.

A later review round added the environment-supplied path, which the first hostile-branch test could not reach: GNU Make imports environment variables as recursively expanded, so a branch named `feature/foo$(id)` supplied the way CI supplies it loses `$(id)` before any quoting runs. The original test drove the value through `$(shell git ...)`, whose output Make does not re-expand -- the one door that was already safe. Source test functions rise to `3,680` and quality/security tests to `237`; uncategorized is unchanged at `825`.

Review of #489 added a module driving the concurrency-contracts gate itself: a completed run accepted, and a skip, a nonzero pytest exit over a green report, and an empty collection each refused. Inventoried modules rise to `324`, source test functions to `3,685`, and quality/security tests to `241`; uncategorized is unchanged at `825`.

A later review round replaced five non-emptiness assertions on `/version` with the exact ARG defaults plus a supplied-value case: the old form passed against a response carrying no build identity at all, so it could not catch CI ceasing to supply the values. Source test functions rise to `3,687` and API/runtime tests to `703`.

The #532 cancellation-race review added four focused lifecycle regressions, two one-row PostgreSQL
interleaving contracts, and corrected a taxonomy
gap: execution registry/lifecycle and lineage metadata/service tests prove durable polling,
cancellation, evidence materialization, and recovery behavior, so they belong with their already
classified worker and compute-store peers. Final review added one API/runtime proof that synchronous
preparation is off the application loop and one analytics proof that insufficient portfolio truth
precedes benchmark degradation. Exact-head review then added five API/runtime proofs that durable
cancellation and ordinary failure persistence run off the application loop, drain before exit, and
restore request cancellation after slow preparation or calculation failure transitions, including
when the durable cancellation fence itself fails.
The final stage-start mutation proves a failed durable transition terminally fences the execution
before calculation begins. Real-PostgreSQL expiry and both completion-first and reclaim-first
interleavings prove a stale lineage worker cannot publish after its lease expires and completion,
single reclaim, or batch reclaim cannot both win. Source test functions now measure `3,843`,
API/runtime functions measure `770`, observability/readiness functions rise from `432` to `551`, and uncategorized functions fall from
`772` to `671`. The blocking ceiling is re-banked to the measured `671`; it was not raised to admit
new tests.

The #538 final-review regressions add five source test functions and correct the classification of
the executable durable-recovery drill. Its restore-schema and representative-read checks are
observability/readiness evidence, not uncategorized utility tests. Source test functions therefore
measure `3,863`, analytics-domain functions `1,848`, observability/readiness functions `564`, and
uncategorized functions fall from `646` to `635`. The blocking ceiling is tightened to the measured
`635`; no test was admitted by raising a threshold.

The exact-head review adds two analytics-domain source test functions: one refuses a blank legacy
restatement version during schema upgrade, and one parametrized contract refuses both missing and
extra durable families for a pinned completed publication. Source test functions therefore measure
`3,865`, analytics-domain functions `1,850`, and the governed uncategorized ceiling remains `635`.

The following exact-head review adds one analytics-domain source function for a pinned request that
extends outside its completed manifest and a second collected case for an overlong legacy version
label. Source test functions then measure `3,871`, analytics-domain functions `1,856`, and the
unchanged uncategorized ceiling remains `635`.

The latest exact-head review adds two analytics-domain source functions: a fast parametrized SQLite
upgrade regression for both null publication-period boundaries and a real-PostgreSQL nullable-row
upgrade contract. Source test functions now measure `3,873`, analytics-domain functions `1,858`, and the
unchanged uncategorized ceiling remains `635`.

The subsequent whitespace-version and malformed-date review adds three collected cases to existing
analytics-domain test functions, so the source-function taxonomy and its `635` ceiling are unchanged.

The fresh-SQLite version-label review adds one analytics-domain source test, and the subsequent
sequence/calendar review adds two more for direct insert/update rejection. The completed-fact
immutability review adds one source test covering payload update/delete refusal and supported
transactional cleanup. The additive-SQLite-guard review adds one source test for upgraded-table
future writes. Source test functions now measure `3,879`, analytics-domain functions `1,864`, and
the unchanged uncategorized ceiling remains `635`.

The final review regressions add two analytics-domain source functions for fail-closed publication
lineage bootstrap and stale SQLite trigger replacement, plus one contract/governance gate function
proving every selected PostgreSQL target collects independently. Source test functions now measure
`3,886`, analytics-domain functions `1,870`, contract/governance functions `194`,
observability/readiness functions `565`, quality/security functions `268`, and the unchanged
uncategorized ceiling remains `635`.

The durable publication-boundary review adds three analytics-domain source functions: a cheap
SQLite direct-insert contract, a real-PostgreSQL direct-insert contract, and the previously
unrecorded exact-head regression. Source test functions now measure `3,890`, analytics-domain
functions `1,874`, and the unchanged uncategorized ceiling remains `635`.

The final constraint-repair review adds five analytics-domain source functions covering stale
same-named PostgreSQL checks, nullable fact-currency hardening, invalid retained rows, and a
DDL-free canonical second bootstrap. Source test functions now measure `3,895`, analytics-domain
functions `1,879`, and the unchanged uncategorized ceiling remains `635`.

The XIRR qualification slice adds seven analytics-domain source functions, including three
registered HTTP contracts, for close/tangent root isolation, explicit termination evidence,
invalid solver controls, telemetry, and durable response replay. Source test functions now measure
`3,902`, API/runtime functions `778`, analytics-domain functions `1,886`, and the unchanged
uncategorized ceiling remains `635`.

The final XIRR qualification review adds four source test functions for truthful non-simple-root
classification and deterministic combined-work rejection. Source test functions now measure
`3,906`, API/runtime functions `779`, analytics-domain functions `1,890`, and the unchanged
uncategorized ceiling remains `635`.

The BHB decomposition correction adds three analytics-domain source test functions: exact
positive/negative/zero interaction controls, linked-period reconciliation, and public API plus BF
control evidence. Source test functions now measure `3,909`, API/runtime functions `780`,
analytics-domain functions `1,893`, and the unchanged uncategorized ceiling remains `635`.

The final acceptance-proof review adds one supported by-instrument HTTP regression using exact
position valuations and independently derived sector effects. Source test functions now measure
`3,910`, API/runtime functions `781`, analytics-domain functions `1,894`, and the unchanged
uncategorized ceiling remains `635`.

The tenant-scoped composite persistence slice adds one analytics-domain unit module, three
PostgreSQL migration/isolation contracts, one HTTP tenant-isolation regression, and focused
migration rollback coverage. Final review adds definition-key integrity plus supported HTTP
inspection isolation and foreign-only refusal. Source test functions now measure `3,938`,
API/runtime functions `783`, analytics-domain functions `1,919`, and the unchanged uncategorized
ceiling remains `635`.

The component-economics source-scope admission slice adds four analytics-domain unit functions and
one registered contribution API function for initial-page, later-page, multi-chunk durable retry,
optional degradation, and valid-control proof. Source test functions now measure `3,943`,
API/runtime functions `784`, analytics-domain functions `1,924`, and the unchanged uncategorized
ceiling remains `635`.

The valuation-observation admission slice adds twenty-one analytics-domain functions and ten
registered HTTP functions for finite-value, non-empty-history, identical-deduplication, same-date
conflict, date normalization, and required-boundary proof across stateless, stateful, workspace,
and direct-engine boundaries. Source test functions now measure `3,974`, API/runtime functions
`794`, analytics-domain functions `1,945`, and the unchanged uncategorized ceiling remains `635`.

The TWR strict-FX and daily currency-evidence slice plus final-review regressions add twelve
analytics-domain source functions, five registered API/runtime functions, one
observability/readiness inspection function, and one contract/governance documentation function.
At that recorded final-review baseline, source test functions measured `3,992`, API/runtime
functions `799`, contract/governance functions `196`, observability/readiness functions `568`,
analytics-domain functions `1,957`, and the unchanged uncategorized ceiling remained `635`.

The benchmark-exposure source-qualification slice added eight analytics-domain and API/runtime
regression functions covering malformed source facts, empty component history, stable per-page
qualification, finite weight refusal, canonical date admission, bounded omission evidence, and
the response contract.

The group-return evidence slice adds service, durable-workflow, and registered API proof for
heterogeneous and signed-hedge economics, zero exposure, income, source-cut replay, currency,
classification, and stale/foreign lineage refusal. The taxonomy now classifies both that producer
suite and the existing analytics-workflow-type suite as analytics-domain behavior. At that merge,
source test functions measured `4,031`, API/runtime functions `805`, contract/governance functions `197`,
observability/readiness functions `568`, analytics-domain functions `2,005`, and uncategorized
functions `626`. The blocking ceiling tightens from `635` to the measured `626`; no test was
admitted by weakening a threshold. The final provider regressions add durable failure, source-counter,
malformed-fact, negative-capital, reconciliation, source-fingerprint source-cut, and API window-refusal
proof without growing the uncategorized backlog.

The #559 continuation follow-up adds two registered API regressions and one quality-baseline
failure regression. Current source test functions measure `4,034`, API/runtime functions `807`,
analytics-domain functions `2,007`, quality/security functions `269`, and uncategorized functions
remain `626`. The blocking floors and ceiling are unchanged.

The #573 position-identity admission slice adds direct-model, registered-API and safe-error
envelope and bounded 4xx-metric regressions. Current measured source functions are `4,041`,
API/runtime functions `812`, analytics-domain functions `2,013`; the enforced uncategorized ceiling
stays `626`.

The #549 contribution availability slice adds five parameterized registered-HTTP economics tests,
one OpenAPI contract test, and one residual-allocation service regression. Current source test
functions measure `4,048`, API/runtime functions `819`, analytics-domain functions `2,020`, and
uncategorized functions remain `626`. Existing floors and ceilings are unchanged.

The #551 benchmark weight-basis slice adds independent registered price-derived and stateful
five-shape exposure proofs. Current source test functions measure `4,052`, API/runtime functions
`822`, analytics-domain functions `2,024`, and uncategorized functions remain `626`. Existing
floors and ceilings are unchanged.

The #548 attribution-linking conditioning slice adds positive and negative near-zero denominator,
well-conditioned small-return, and registered resampling regressions. Current source test functions
measure `4,055`, API/runtime functions `823`, analytics-domain functions `2,027`, and uncategorized
functions remain `626`. Existing floors and ceilings are unchanged.

The #543 since-inception history-coverage slice adds direct calendar/baseline qualification,
registered stateless and Core-sourced stateful API, workspace/benchmark-relative propagation,
OpenAPI, documentation, and reproducibility-identity regressions. Current source test functions
measure `4,065`, API/runtime functions `826`, analytics-domain functions `2,034`, and
uncategorized functions remain `626`. The `performance_history` classifier token maps this focused
financial-evidence suite to its actual analytics domain instead of spending uncategorized slack;
the blocking floors and ceiling are unchanged.

The final #543 review adds eight source functions and nine collected cases for repeated short-gap
classification, truthful no-observation reasons, bounded extreme windows, maximum-date safety,
pre-calculation HTTP refusal on both supported APIs, and untrimmed workspace covered bounds.
Current source test functions measure `4,073`, API/runtime functions `828`, analytics-domain
functions `2,040`, and uncategorized functions remain `626`; no floor or ceiling changed.

The final resolved-window review fix adds one source function and two endpoint cases proving that
raw inception does not enlarge a requested `1Y` master window. Current source test functions
measure `4,074`, API/runtime functions `829`, analytics-domain functions `2,040`, and
uncategorized functions remain `626`; no floor or ceiling changed.

The source-derived-window review fix adds four service regressions proving both TWR and workspace
refuse excessive SI before time-series retrieval and bound old-inception `1Y` retrieval to the
resolved master window. Current source test functions measure `4,078`, API/runtime functions
`829`, analytics-domain functions `2,044`, and uncategorized functions remain `626`; no floor or
ceiling changed.

The final authoritative-inception review fix adds four source-path regressions proving both TWR
and workspace refuse an extreme Core inception after a caller supplied a recent start, while an
older source inception remains valid for a bounded `1Y` horizon. Current source test functions
measure `4,082`, API/runtime functions remain `829`, analytics-domain functions measure `2,048`,
and uncategorized functions remain `626`; no floor or ceiling changed.

The #542 source-correction slice adds durable tenant-scoped admission, replay/conflict, cancellation,
retention, PostgreSQL contention/restart, HTTP, observability, and registered 10%→8% TWR proofs.
The `source_correction` and previously omitted `runtime_retention` classifier tokens map those
runtime-readiness suites to their actual family. Current source test functions measure `4,100`,
API/runtime functions `833`, contract/governance functions `201`, analytics-domain functions
`2,051`, observability/readiness functions `683`, and uncategorized functions fall to `565`.
The blocking ceiling tightens to the measured `565`; no floor is reduced.

The #507 applied-FX admission slice adds registered legacy/nested, flat/hierarchy, sync/async,
same-currency, foreign-currency, and strict-decimal regressions. Source test functions measure
`4,130`, API/runtime functions `844`, analytics-domain functions `2,071`, and uncategorized
functions remain `565`; no floor or ceiling changed.

The #530 Decimal-boundary slice adds exact model, service, inspection, adapter, contribution API,
and benchmark API regressions. Source test functions measure `4,138`, API/runtime functions `847`,
analytics-domain functions `2,078`, and uncategorized functions remain `565`; no floor or ceiling
changed.

The #336 durable async-failure slice adds eight source functions covering versioned classification,
legacy-safe fallback, additive schema upgrade, restart recovery, repeated polling, retention
fallback, tenant isolation, legacy polling sanitization, bounded fields, and malformed stored
contracts. Current source test functions measure `4,198`, API/runtime functions `887`, and
uncategorized functions remain `565`; no floor or ceiling changed.

The #473 monetary-request slice adds exact admission, independent Dietz/XIRR and FX figures,
bounded numerical refusals, stateful Decimal retention, registered API and lineage controls.
That historical tree had 4,288 source functions, 905 API/runtime and 206 contract/governance functions.
The unchanged uncategorized ceiling is 565; collection is not execution or consumer acceptance.

The historical #600 valuation slice measured 351 modules and 4,324 source functions: 909 API/runtime,
206 contract/governance, 691 observability/readiness, 313 quality/security and 2,194 analytics-domain.
The uncategorized ceiling remains 565. Financial controls cover exact source precision, signed
cash-flow cancellation, conversion and restoration; this inventory does not establish acceptance.

The #601 attribution precision-policy candidate measures 352 modules and 4,331 source functions:
913 API/runtime, 207 contract/governance, 691 observability/readiness, 313 quality/security and
2,201 analytics-domain. The uncategorized ceiling remains565; refusal/replay controls do not
establish independent acceptance or strict attribution support.
