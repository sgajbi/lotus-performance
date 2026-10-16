# Lotus Performance Refactor Quality Scorecard

Report date: 2026-07-10
Branch: `feat/performance-architecture-boundary-refactor`
Baseline source: `quality/baseline_report.md`
Current source: `quality/refactor_health_report.md`
Testing inventory refresh: 2026-10-10, result authority (#610), PR proof controls (#641) and main coverage parity (#645).
Other phase-zero measurements below remain historical, not current acceptance evidence.
Historical CI acquisition refresh (2026-10-14, #664): native generation measures 1,026 Python files,
300,029 Python LOC, 460 test modules and 9,219 collected tests on the isolated current-main-based
adopter tree. AST taxonomy measures 5,419 functions, including 416 quality/security functions;
API/runtime and contract/governance breadth and the uncategorized ceiling are unchanged.
The added 99 collected cases and 31 source test functions are source/mock controls, not hosted
pull/build/security/PostgreSQL/recovery acceptance. No unmerged #662 feature truth is included.
PostgreSQL regression authoring refresh (2026-10-12): file, LOC, collection and
taxonomy rows include the precision capture target and focused gate controls.
The new PostgreSQL cases are collected only; no database execution is claimed.
S1 measured refresh (2026-10-12, source `d5b08d6f`): code-health counts, taxonomy,
maintainability, function size and architecture current values were recomputed from native source.
From the repository root in PowerShell or Bash, use `python scripts/generate_quality_baseline.py --check --skip-inventories`,
`python scripts/python_test_taxonomy_inventory.py --limit 30`,
`python scripts/python_complexity_inventory.py --limit 1`,
`python scripts/python_function_size_inventory.py --limit 1`, and
`python scripts/python_architecture_boundary_inventory.py --limit 1`.
These measurements supersede older scanner snapshots for the refreshed rows; historical columns,
coverage results and execution failures remain unchanged. Collection is not a test pass or release acceptance.
Historical integration measurement (2026-10-14, #662 integration of qualified #666 base 8a0ee425): the native commands
above measure 1,043 Python files, 36 package markers, 304,832 Python lines, 9,504 collected
tests and average maintainability 55.22, including the three peer-review variants and unchanged #664 acquisition controls. Current taxonomy is measured by the native AST inventory.
Historical fixture correction measurement (2026-10-15, #662 after signed source `ef540916`):
native baseline generation measures 304,843 Python lines and 3,013 lines in the worker test module.
The test-owned lineage store adds 11 Python lines; 1,043 Python files, 36 package markers,
466 test modules and 9,504 collected cases are unchanged. Full affected-module proof passed
61 tests locally; the original hosted unit failure remains evidence until fresh head checks pass.
Historical integrated PG16 wiring measurement (2026-10-15, #662/#945): native healthy collection
records 9,572 cases and 305,122 Python lines, with 1,043 files, 36 markers and 466 test modules.
AST taxonomy records 5,510 test functions, including 420 quality/security functions; all other
families and policy floors remain unchanged. The 68 collected cases are offline workflow guards;
they provide no original-registry, native PostgreSQL, workload or hosted/live acceptance.
Historical local #633/#669 integration measurement (2026-10-15, signed source e3208f9d plus reviewed worker integration):
native baseline generation records 1,056 Python files, 36 package markers, 307,518 Python lines,
471 test modules and 9,647 collected cases. AST taxonomy records 5,545 functions, including
1,117 API/runtime, 258 contract/governance, 787 observability/readiness, 436 quality/security,
3,229 analytics-domain and 558 uncategorized functions. Family counts overlap. Native complexity
records maximum8, zero high-complexity functions and average maintainability55.15.
These are local source/collection measurements, not native candidate, PostgreSQL or container proof.
Historical columns and coverage evidence remain unchanged; these figures do not establish live acceptance.
Native architecture inventory records 93 report-only import occurrences and zero enforced findings.
At signed `68c99853` it recorded 90; three additional occurrences reference the same existing
execution-registry dependency in the typed owning-store publication read. No new concrete-store dependency edge
or blocking-policy exception is introduced. The current native command supersedes the older snapshot.
Mode: phase-zero scorecard; static-quality and evaluation enforcement includes complexity,
architecture, router-thinness, duplicate-code, repository hygiene, observability-readiness,
domain-product validation, deterministic API evaluation, test taxonomy breadth gates, license
compliance, and container supply-chain evidence.

## Purpose

Historical bounded acquisition-failure evidence measurement (2026-10-15, #669, frozen base `cf44e05b`):
native AST inventory measures 467 modules and 5,526 source test functions, including 431
quality/security functions, eleven more than the frozen base. Other families and policy bounds
are unchanged. Native production complexity remains max 8, zero D-F findings and average
maintainability 55.31 (`python scripts/python_complexity_inventory.py --limit 25`); this helper change is outside that default
production scope. At signed `74889776`, the native generated baseline recorded
9,613 collected cases and 305,718 Python lines. Collection is not test execution.
Only bounded offline evidence is claimed: fixed failure diagnostics, confidential data exclusion,
untouched existing paths and atomic successful-proof publication. Hosted capture and actual worker
Docker acceptance remain Root-owned gates; no selection, retry or budget policy changes.

Historical original-selection/PG17 proof measurement (2026-10-15, #669/#945, base `74889776`):
native generation records 306,522 Python lines and 9,693 collected cases. AST inventory records
5,547 functions, including 452 quality/security functions across the same 467 modules. The
21 added functions cover explicit admission and binding, policy/build custody, DB-first content
verification and refusal/cleanup behavior. Other family counts and policy floors remain unchanged.
Python and PG17 select their separately approved exact originals through qualified central
`cd7563c52008fffee8a37b1b6c3235480823a5cd`; the df4 Python helper is unchanged. Offline controls
and collection do not qualify hosted build/security, database readiness, recovery or live workers.

Historical protected-main integration measurement (2026-10-15, #633, exact base `9dcba09a`):
native baseline generation records 1,056 Python files, 36 package markers, 308,702 Python lines,
471 test modules and 9,755 collected cases. AST inventory records 5,577 source functions,
including 1,117 API/runtime, 258 contract/governance, 787 observability/readiness, 468 quality/security,
3,229 analytics-domain and 558 uncategorized functions. Family counts overlap; policy bounds remain
unchanged. Native complexity remains max8/zero D-F with average maintainability55.15.
These combined source/collection measurements preserve final #669 truth and the reviewed #633
synthetic deployment; they do not establish native candidate, PostgreSQL, container or financial acceptance.

Historical Docker delivery measurement (2026-10-15, #633, exact base `3cf37781`): native baseline
generation records 1,056 Python files, 36 package markers, 308,818 Python lines, 471 test modules
and 9,773 collected cases. AST inventory records 5,581 source functions, including 1,117 API/runtime,
260 contract/governance, 787 observability/readiness, 469 quality/security, 3,231 analytics-domain
and 558 uncategorized functions. Family counts overlap; policy bounds and production code are
unchanged. The opt-in overlay, model and loader/credential controls do not establish Docker
mount/startup, upstream source, READY candidate or financial acceptance.

Historical controlled scenario consumer measurement (2026-10-15, #633, exact base `6b70e75e`):
native baseline generation records 1,062 Python files, 36 package markers, 309,933 Python lines,
474 test modules and 9,838 collected cases. AST inventory records 5,605 functions, including
1,117 API/runtime, 272 contract/governance, 787 observability/readiness, 469 quality/security,
3,255 analytics-domain and 558 uncategorized functions. Native complexity remains max8/zero D-F
with average maintainability55.08; shared validators remove five duplicate groups without changing
legacy schemas. Family counts overlap and policy bounds remain unchanged. These are source and
offline collection measurements; the actual adapter/ledger refusal and replay proof supplies no
missing provider observations, COMPLETE financial candidate or live source qualification.

Historical annual reporting-review measurement (2026-10-16, #608 candidate, exact base `53a50182`):
native generation records 1,062 Python files, 36 package markers, 310,135 Python lines,
474 test modules and 9,855 collected cases. AST inventory records 5,615 source functions,
including 1,121 API/runtime, 273 contract/governance, 787 observability/readiness, 469 quality/security,
3,265 analytics-domain and 558 uncategorized functions. Family counts overlap; policy bounds remain
unchanged. Native production complexity remains max8/zero D-F with average maintainability55.07,
93 report-only architecture findings/zero enforced findings and zero duplicate groups. These
measurements do not establish approved reporting profiles, PostgreSQL or live acceptance.

Current #624 single-analysis AST measurement (2026-10-16, exact base `b7de3b30`):
475 modules and 5,627 source functions, including 1,121 API/runtime, 273 contract/governance,
787 observability/readiness, 481 quality/security, 3,265 analytics-domain and 558 uncategorized
functions. `python scripts/python_test_taxonomy_inventory.py --limit 30` supplies these counts;
family counts overlap and policy bounds are unchanged. Only taxonomy measurements are refreshed
by this slice; other scorecard measurements retain their cited prior evidence and are not new
measurements for this candidate. AST inventory does not establish executed tests or live proof.

This document is the first before/after quality scorecard for the performance hardening stream.
It is intended to track measurable quality posture change over refactor phases, where the same
metrics in each section are updated with each meaningful slice.

## Scorecard

### Code Health

| Metric | Baseline | Current | Delta | Status | Evidence |
| --- | ---: | ---: | ---: | --- | --- |
| Python files | 480 | 1062 | 582 | measured | `quality/baseline_report.md`; `quality/refactor_health_report.md` |
| Python package markers | 18 | 36 | 18 | measured | `quality/baseline_report.md`; `quality/refactor_health_report.md` |
| Python LOC | 104,454 | 310,135 | 205,681 | measured | `quality/baseline_report.md`; `quality/refactor_health_report.md` |
| Largest Python file LOC | 2,399 | 4,447 | 2,048 | measured | `quality/baseline_report.md`; `quality/refactor_health_report.md` |
| Largest production file LOC | 1,156 | 3,271 | 2,115 | measured | `quality/refactor_health_report.md`; `quality/architecture_boundary_inventory.md` |
| Python test modules | 228 | 475 | 247 | measured | `quality/test_taxonomy_inventory.md`; `quality/refactor_health_report.md` |
| Collected tests | 2,035 | 9,855 | 7,820 | measured | `quality/baseline_report.md`; `quality/refactor_health_report.md` |
| Duplicate code hotspots | 0 | 0 | 0 | enforced | `quality/duplicate_code_inventory.md`; `quality/refactor_health_report.md`; `make quality-duplicate-code-gate` |
| Tracked local byproduct findings | unknown | 0 | n/a | enforced | `scripts/repository_hygiene_gate.py`; `make repository-hygiene-gate`; `quality/refactor_health_report.md` |

### Complexity And Maintainability

| Metric | Baseline | Current | Delta | Status | Evidence |
| --- | ---: | ---: | ---: | --- | --- |
| Max cyclomatic complexity | unknown | 8 | n/a | enforced | `quality/complexity_inventory.md`; `quality/refactor_health_report.md`; `make quality-complexity-gate` |
| High-complexity functions (D-F) | unknown | 0 | n/a | enforced | `quality/complexity_inventory.md`; `quality/refactor_health_report.md`; `make quality-complexity-gate` |
| Average maintainability index | unknown | 55.07 | n/a | measured | `python scripts/python_complexity_inventory.py --limit 25`; `quality/refactor_health_report.md` |
| Largest functions by LOC | unknown | 169 | n/a | measured | `quality/function_size_inventory.md`; `quality/refactor_health_report.md`; `_create_sqlite_composite_fact_validation_guards(...)` remains the largest production function at `169` lines |

### Architecture

| Metric | Baseline | Current | Delta | Status | Evidence |
| --- | ---: | ---: | ---: | --- | --- |
| Enforced import-boundary findings | unknown | 0 | n/a | enforced | `quality/architecture_boundary_inventory.md`; `quality/refactor_health_report.md`; `make quality-architecture-gate` |
| Routers with infrastructure imports | unknown | 0 | n/a | enforced | `quality/architecture_boundary_inventory.md`; `quality/refactor_health_report.md`; `make quality-architecture-gate` |
| Engine/core infra/framework imports | unknown | 0 | n/a | enforced | `quality/architecture_boundary_inventory.md`; `quality/refactor_health_report.md`; `make quality-architecture-gate` |
| Route workflow direct DTO calls | unknown | 0 | n/a | enforced | `quality/architecture_boundary_inventory.md`; `scripts/python_architecture_boundary_inventory.py`; `make quality-architecture-gate` |
| Application-service concrete-store imports | unknown | 93 | n/a | measured | `python scripts/python_architecture_boundary_inventory.py --limit 1`; execution polling pilot moved behind `ExecutionPollingStore` |
| Large production service hotspots (LOC > 1000) | 3 | 14 | 11 | measured | `quality/refactor_health_report.md`; `quality/architecture_boundary_inventory.md` |
| Router/middleware oversized function findings (`--threshold 80`) | unknown | 0 | n/a | enforced | `quality/router_middleware_thinness_inventory.md`; `quality/refactor_health_report.md`; `make quality-router-thinness-gate` |

### API Quality

| Metric | Baseline | Current | Delta | Status | Evidence |
| --- | ---: | ---: | ---: | --- | --- |
| OpenAPI operations | unknown | 37 | n/a | measured | `quality/api_completeness_inventory.md`; `quality/refactor_health_report.md` |
| OpenAPI findings | unknown | 0 | n/a | measured | `quality/api_completeness_inventory.md`; `quality/refactor_health_report.md` |
| JSON error examples present | unknown | 0 | n/a | measured | `quality/api_completeness_inventory.md`; `quality/refactor_health_report.md` |
| Error responses with schema | unknown | 0 | n/a | measured | `quality/api_completeness_inventory.md`; `quality/refactor_health_report.md` |
| Error responses missing RFC 7807 pattern | unknown | 0 | n/a | measured | `quality/api_completeness_inventory.md`; `quality/refactor_health_report.md` |

### Testing

| Metric | Baseline | Current | Delta | Status | Evidence |
| --- | ---: | ---: | ---: | --- | --- |
| Line coverage | unknown | 99.58% | n/a | measured | `quality/coverage_inventory.md`; `quality/refactor_health_report.md` |
| Branch coverage | unknown | 98.00% | n/a | measured | `quality/coverage_inventory.md`; `quality/refactor_health_report.md`; `make branch-coverage-baseline` |
| Integration/API/runtime test functions | unknown | 1121 | n/a | enforced | `quality/test_taxonomy_inventory.md`; `quality/refactor_health_report.md`; `make quality-test-taxonomy-gate` |
| Contract/governance test functions | unknown | 273 | n/a | enforced | `quality/test_taxonomy_inventory.md`; `quality/refactor_health_report.md`; `make quality-test-taxonomy-gate` |
| Uncategorized test functions | unknown | 558 | n/a | enforced ceiling | `quality/test_taxonomy_inventory.md`; `make quality-test-taxonomy-gate`; #619 exact adapter classification measures 558 and separately banks policy 558. |

### Security and Dependencies

| Metric | Baseline | Current | Delta | Status | Evidence |
| --- | ---: | ---: | ---: | --- | --- |
| Bandit high findings | unknown | 0 | n/a | enforced | `quality/python_security_inventory.md`; `quality/refactor_health_report.md`; `make python-security-gate` |
| Bandit medium findings | unknown | 0 | n/a | enforced | `quality/python_security_inventory.md`; `quality/refactor_health_report.md`; `make python-security-gate` |
| Bandit low findings | unknown | 0 | n/a | enforced | `quality/python_security_inventory.md`; `quality/refactor_health_report.md`; `make python-security-gate` |
| Dependency vulnerability findings | unknown | 0 | n/a | measured | `quality/dependency_security_report.md`; `quality/refactor_health_report.md` |
| Dependency hygiene findings | unknown | 0 | n/a | measured | `quality/dependency_hygiene_report.md`; `quality/refactor_health_report.md` |
| Third-party packages inventoried | unknown | 51 | n/a | enforced | `quality/license_compliance_inventory.md`; `make license-compliance-gate` |
| Review-required license exceptions | unknown | 2 | n/a | enforced | `contracts/license-compliance-policy.v1.json`; `quality/license_compliance_inventory.md` |
| Blocked or missing-exception license findings | unknown | 0 | n/a | enforced | `make license-compliance-gate` |
| Container SBOM artifact | unknown | 1 | n/a | measured | `quality/container_supply_chain_report.md`; `make container-supply-chain-evidence`; PR/Main artifact upload |
| Container vulnerability report artifact | unknown | 1 | n/a | measured | `quality/container_supply_chain_report.md`; `make container-supply-chain-evidence`; PR/Main artifact upload |
| Container vulnerability gate | unknown | 0 | n/a | enforced | `make container-vulnerability-gate` blocks in PR Merge Gate and Main Releasability. Zero unaccepted high/critical findings; 8 base-image advisories with no upstream fix are accepted in `quality/container_vulnerability_acceptances.v1.json` with package identity, affected version, owner, expiry and remediation path, and validated against the same scan by `scripts/container_acceptance_gate.py`, which `make container-vulnerability-gate` runs |
| SBOM provenance attestation | unknown | 1 | n/a | measured | `quality/container_supply_chain_report.md`; Main Releasability `actions/attest-build-provenance@v3` |

### Operational Readiness

| Metric | Baseline | Current | Delta | Status | Evidence |
| --- | ---: | ---: | ---: | --- | --- |
| Operational readiness markers | unknown | 28 | n/a | enforced | `quality/observability_readiness_inventory.md`; `quality/refactor_health_report.md`; `make quality-observability-readiness-gate` |
| Missing readiness markers | unknown | 0 | n/a | enforced | `quality/observability_readiness_inventory.md`; `quality/refactor_health_report.md`; `make quality-observability-readiness-gate` |
| Deployable monitoring alert rules | unknown | 14 | n/a | enforced | `monitoring/prometheus/lotus-performance-alerts.prometheusrule.json`; `quality/observability_readiness_inventory.md`; `make quality-observability-readiness-gate` |
| Deployable monitoring dashboard panels | unknown | 12 | n/a | enforced | `monitoring/grafana/lotus-performance-operability-dashboard.json`; `quality/observability_readiness_inventory.md`; `make quality-observability-readiness-gate`; issue #427 adds returns-series supportability panels and alert-dashboard coverage enforcement |
| Correlation propagation markers | unknown | 6 | n/a | measured | `quality/observability_readiness_inventory.md`; `quality/refactor_health_report.md` |
| Structured logging markers | unknown | 6 | n/a | measured | `quality/observability_readiness_inventory.md`; `quality/refactor_health_report.md` |
| Metrics markers | unknown | 6 | n/a | measured | `quality/observability_readiness_inventory.md`; `quality/refactor_health_report.md` |
| Health/readiness markers | unknown | 6 | n/a | measured | `quality/observability_readiness_inventory.md`; `quality/refactor_health_report.md` |
| Demo API certification command | unknown | 1 | n/a | enforced | `make quality-evaluation-gate`; `make demo-api-certification`; `quality/refactor_health_report.md` |
| Test taxonomy gate | unknown | 1 | n/a | enforced | `make quality-evaluation-gate`; `make quality-test-taxonomy-gate`; `quality/test_taxonomy_inventory.md` |
| Performance characterization artifact lane | unknown | 1 | n/a | measured | `make performance-characterization`; `.github/workflows/performance-characterization.yml`; `output/performance-characterization/*.summary.json`; issue #426 |

### Documentation

| Metric | Baseline | Current | Delta | Status | Evidence |
| --- | ---: | ---: | ---: | --- | --- |
| README markers required | unknown | 8 | n/a | measured | `quality/documentation_inventory.md`; `quality/refactor_health_report.md` |
| Missing README markers | unknown | 0 | n/a | measured | `quality/documentation_inventory.md`; `quality/refactor_health_report.md` |
| Wiki pages | unknown | 21 | n/a | measured | `quality/documentation_inventory.md`; `quality/refactor_health_report.md` |
| Major pack README files | unknown | 12 | n/a | measured | `quality/documentation_inventory.md`; `quality/refactor_health_report.md`; enforced by `tests/unit/scripts/test_python_documentation_inventory.py` |
| Missing major pack README files | unknown | 0 | n/a | measured | `quality/documentation_inventory.md`; `quality/refactor_health_report.md`; enforced by `tests/unit/scripts/test_python_documentation_inventory.py` |
| Public definition docstring coverage | unknown | 12.01 | n/a | measured | `quality/documentation_inventory.md`; `quality/refactor_health_report.md` |

## Current Improvement Signal

| Signal | Value | Note |
| --- | ---: | --- |
| Total metrics tracked | 55 | All metrics in this file are now measured or explicitly staged, with selected zero-finding, breadth, and release-evidence signals enforced or produced separately. |
| Measured metrics | 54 | Selected measured metrics are now also enforced or produced through blocking static-quality, security, deterministic API evaluation, test-taxonomy, container evidence, or performance-characterization evidence lanes. Branch coverage output is measured report-only and is not promoted to a strict gate yet. Container vulnerability output is now enforced. |
| Not-yet-measured metrics | 0 | The scorecard no longer carries an unmeasured branch-coverage entry. OpenAPI Spectral and public-docstring gate decisions remain outside this scorecard until scoped separately. |
| Planned gates | 0 | `make container-vulnerability-gate` is promoted and blocking. The reviewed baseline is zero unaccepted high/critical findings, with 8 unfixable base-image advisories accepted under a policy that binds each to package identity and affected version, expires them, and refuses any advisory that has an upstream fix. |
| Latest observability signal | 1 | Returns-series supportability alerts now have deployable Grafana coverage for stale/degraded rate and supportability volume. `make quality-observability-readiness-gate` enforces alert-dashboard coverage for expected product supportability alerts instead of relying only on dashboard panel count. |

## Method Note

- Values are intentionally conservative and map to artifacts already generated from
  repository-native scripts; selected zero-finding, deterministic API evaluation, and
  test-taxonomy breadth signals are now blocking gates.
- `n/a` indicates that a comparable historical pre-baseline value is not yet available in-repo.
- The next slice should review the branch-coverage gap profile before proposing any threshold,
  exception policy, or CI lane placement.

## Durable Schema Ownership Development Inventory (#488)

Historical #488 AST inventory: 357 modules, 4,388 source test functions, 915 integration/API/runtime test functions, 215 contract/governance test functions, 735 observability/readiness test functions, 324 quality/security test functions, 2,212 analytics-domain test functions, and 563 uncategorized test functions.
Schema-verification and owner-upgrade tests are readiness evidence; the uncategorized ceiling
tightens from 565 to 563. Pinned Docker typecheck passed342 source files. The initial full Docker
lane historically retained three inventory failures with4796 unit passes/three governed skips.
Final #488 main75f8edbd passed all ten jobs in37185500985; independent QA remains separate.
Historical failures above are unchanged.

## Operator Retention Entrypoint Development Inventory (#604)

Historical #604 AST inventory: 381 modules, 4,661 source test functions, 973 integration/API/runtime,
227 contract/governance, 755 observability/readiness, 349 quality/security, 2,442 analytics-domain
and 558 uncategorized functions. Fresh subprocess contracts cover help, dry-run, scheduled Make
execution and positive policy boundaries. No gate or financial formula changed. Release acceptance
requires pinned delivery gates and immutable image proof; native tests alone are not acceptance.
