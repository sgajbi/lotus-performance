# Lotus Performance Refactor Health Report

Report date: 2026-06-28
Branch: `feature/policies-branch-hardening`
Baseline source: `quality/baseline_report.md`
Report mode: phase-zero scorecard; complexity, architecture, duplicate-code, repository hygiene,
router-thinness, observability-readiness, and Python security posture are enforced separately by CI.

## Purpose

This report turns the report-only baseline into the durable before/current scorecard for the
hardening stream. At phase zero, the baseline and current values are intentionally the same unless a
metric has already been remeasured. Future refactor phases should update the `Current` column and
link the commit, command, or CI artifact that proves the change.

## Scorecard Status Model

| Status | Meaning |
| --- | --- |
| `measured` | The value is backed by a command run on this branch. |
| `enforced` | The value is backed by a command run on this branch and by a blocking CI gate. |
| `not-yet-measured` | The quality dimension is required by the goal but tooling or collection has not been added yet. |
| `planned-gate` | The quality dimension should become a progressive CI gate after report-only measurement exists. |

## Code Health

| Metric | Baseline | Current | Status | Evidence |
| --- | ---: | ---: | --- | --- |
| Python files | 480 | 567 | measured | `rg --files -g '*.py'` |
| Python package markers | 18 | 18 | measured | recursive `__init__.py` count |
| Python LOC | 104,454 | 143,274 | measured | `rg --files -g '*.py'` plus Python line count on this branch |
| Largest Python file LOC | 2,399 | 2,503 | measured | largest-file inventory on this branch |
| Largest production file LOC | 1,156 | 1,503 | measured | `app/services/returns_series_service.py` |
| Duplicate code hotspots | 0 | 0 | enforced | `quality/duplicate_code_inventory.md`; `make quality-duplicate-code-gate` with `--min-lines 12 --max-groups 0`; duplicated LOC reduced from `24` to `0` in LP-CR-1407 |
| Tracked local byproduct findings | unknown | 0 | enforced | `scripts/repository_hygiene_gate.py`; `make repository-hygiene-gate`; blocking through `make lint` |
| Dead-code candidates at 60% confidence | unknown | 438 | measured | `quality/dead_code_inventory.md` via `scripts/python_dead_code_inventory.py` |
| Dead-code candidates at 80% confidence | unknown | 0 | measured | `quality/dead_code_inventory.md` via `scripts/python_dead_code_inventory.py` |

## Complexity And Maintainability

| Metric | Baseline | Current | Status | Evidence |
| --- | ---: | ---: | --- | --- |
| Max cyclomatic complexity | unknown | 5 | enforced | `quality/complexity_inventory.md` via `scripts/python_complexity_inventory.py`; `make quality-complexity-gate` |
| High-complexity functions | unknown | 0 | enforced | rank D-F functions in `quality/complexity_inventory.md`; `make quality-complexity-gate` |
| Average maintainability index | unknown | 54.91 | measured | `quality/complexity_inventory.md` via `scripts/python_complexity_inventory.py` |
| Largest functions by LOC | unknown | 59 | measured | `quality/function_size_inventory.md` via `scripts/python_function_size_inventory.py`; LP-CR-1502 moved `_build_workspace_summary_response(...)` out of the top-25 table, and the largest production functions now measure `59` lines |

## Architecture

| Metric | Baseline | Current | Status | Evidence |
| --- | ---: | ---: | --- | --- |
| Import boundary violations | unknown | 0 | enforced | `quality/architecture_boundary_inventory.md`; `make quality-architecture-gate` |
| Routers importing infrastructure directly | unknown | 0 | enforced | `ROUTER_DIRECT_BOUNDARY_IMPORT` absent from `quality/architecture_boundary_inventory.md`; `make quality-architecture-gate` |
| Domain/application importing framework or infra code | unknown | 0 | enforced | `DOMAIN_INFRA_OR_FRAMEWORK_IMPORT` absent from `quality/architecture_boundary_inventory.md`; `make quality-architecture-gate` |
| Large production service hotspots | 3 | 8 | measured | `returns_series_service.py`, `stateful_input_service.py`, `compute_job_store.py`, `twr_service.py`, `stateful_attribution_input_service.py`, `lineage_metadata_store.py`, `workspace_summary_service.py`, and `calculation_consistency.py` exceed 1,000 LOC |
| Router/middleware oversized function findings (`--threshold 80`) | unknown | 0 | enforced | `quality/router_middleware_thinness_inventory.md`; `make quality-router-thinness-gate` |

## API Quality

| Metric | Baseline | Current | Status | Evidence |
| --- | ---: | ---: | --- | --- |
| OpenAPI lint findings | unknown | unknown | not-yet-measured | Spectral not configured |
| OpenAPI operations | unknown | 36 | measured | `quality/api_completeness_inventory.md` via `scripts/openapi_completeness_inventory.py` |
| API completeness findings | unknown | 0 | measured | `quality/api_completeness_inventory.md` via `scripts/openapi_completeness_inventory.py` |
| Operations missing descriptions | unknown | 0 | measured | `MISSING_DESCRIPTION` absent from `quality/api_completeness_inventory.md` |
| JSON error responses missing examples | unknown | 0 | measured | `ERROR_JSON_MISSING_EXAMPLE` absent from `quality/api_completeness_inventory.md` |
| JSON error responses missing explicit schema | unknown | 0 | measured | `ERROR_JSON_MISSING_SCHEMA` absent from `quality/api_completeness_inventory.md` |
| Error responses not expressed as problem-detail contracts | unknown | 0 | measured | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` absent from `quality/api_completeness_inventory.md` |

## Testing

| Metric | Baseline | Current | Status | Evidence |
| --- | ---: | ---: | --- | --- |
| Test modules | 228 | 275 | measured | `rg --files tests -g 'test_*.py'` |
| Collected tests | 2,035 | 3,330 | measured | `python -m pytest --collect-only -q` |
| Line coverage | unknown | 99.49% | measured | `quality/coverage_inventory.md` via `make branch-coverage-baseline` (`2,984` unit, `308` integration, and `21` e2e tests under branch coverage; `21,136` covered lines of `21,244` statements) |
| Branch coverage | unknown | 97.35% | measured | `quality/coverage_inventory.md` via `make branch-coverage-baseline` (`2,984` unit, `308` integration, and `21` e2e tests under branch coverage; `4,291` covered branches of `4,408`, `117` missing branches, `117` partial branches) |
| Integration/API/runtime test functions | unknown | 600 | measured | `quality/test_taxonomy_inventory.md` via `scripts/python_test_taxonomy_inventory.py` |
| Contract/governance test functions | unknown | 108 | measured | `quality/test_taxonomy_inventory.md` via `scripts/python_test_taxonomy_inventory.py` |

## Security And Dependencies

| Metric | Baseline | Current | Status | Evidence |
| --- | ---: | ---: | --- | --- |
| Bandit high findings | unknown | 0 | enforced | `quality/python_security_inventory.md`; `make python-security-gate` |
| Bandit medium findings | unknown | 0 | enforced | `quality/python_security_inventory.md`; `make python-security-gate` |
| Bandit low findings | unknown | 0 | enforced | `quality/python_security_inventory.md`; `make python-security-gate` |
| Dependency vulnerabilities | unknown | 0 | measured | `quality/dependency_security_report.md` via repo-native dependency-health audit |
| Dependency hygiene findings | unknown | 0 | measured | `quality/dependency_hygiene_report.md` via `scripts/python_dependency_hygiene_inventory.py` |

## Operational Readiness

| Metric | Baseline | Current | Status | Evidence |
| --- | ---: | ---: | --- | --- |
| Operational readiness implementation markers | unknown | 28 | enforced | `quality/observability_readiness_inventory.md`; `make quality-observability-readiness-gate` enforces `--max-missing 0` |
| Missing operational readiness markers | unknown | 0 | enforced | `quality/observability_readiness_inventory.md`; `make quality-observability-readiness-gate` enforces `--max-missing 0` |
| Correlation propagation markers | unknown | 6 | measured | `correlation_propagation` family in `quality/observability_readiness_inventory.md` |
| Structured logging markers | unknown | 6 | measured | `structured_logging` family in `quality/observability_readiness_inventory.md` |
| Metrics markers | unknown | 6 | measured | `metrics` family in `quality/observability_readiness_inventory.md` |
| Health/readiness markers | unknown | 6 | measured | `health_readiness` family in `quality/observability_readiness_inventory.md` |
| Health/metrics endpoint markers | unknown | 4 | measured | `health_metrics_endpoints` family in `quality/observability_readiness_inventory.md` |
| Mapped observability/readiness test functions | unknown | 366 | measured | family-mapped test-function count in `quality/observability_readiness_inventory.md`; counts can overlap across families |
| Demo API certification command | unknown | 1 | measured | `make demo-api-certification` runs `scripts/demo_api_certification.py` and writes reviewed JSON evidence under `output/demo-api-certification/latest.json` |

## Documentation

| Metric | Baseline | Current | Status | Evidence |
| --- | ---: | ---: | --- | --- |
| README required markers | unknown | 8 | measured | `quality/documentation_inventory.md` via `scripts/python_documentation_inventory.py` |
| Missing README required markers | unknown | 0 | measured | `quality/documentation_inventory.md` via `scripts/python_documentation_inventory.py` |
| Wiki source pages | unknown | 20 | measured | `quality/documentation_inventory.md` via `scripts/python_documentation_inventory.py` |
| Markdown documentation files | unknown | 232 | measured | `quality/documentation_inventory.md` via `scripts/python_documentation_inventory.py` |
| Endpoint certification docs | unknown | 20 | measured | `quality/documentation_inventory.md` via `scripts/python_documentation_inventory.py` |
| API catalog files | unknown | 4 | measured | `quality/documentation_inventory.md` via `scripts/python_documentation_inventory.py` |
| Docs regression test functions | unknown | 57 | measured | `quality/documentation_inventory.md` via `scripts/python_documentation_inventory.py` |
| Public definitions missing docstrings | unknown | 1,086 | measured | `quality/documentation_inventory.md` via `scripts/python_documentation_inventory.py` |
| Public definition docstring coverage percent | unknown | 11.85 | measured | `quality/documentation_inventory.md` via `scripts/python_documentation_inventory.py` |

## Phase-Zero Interpretation

The measured baseline proves that the repository already has a substantial test surface and a large
production/runtime footprint. It does not yet prove enterprise-readiness completion. The immediate
quality-program gap is not lack of aspiration; it is that several requested dimensions are not yet
repeatably measured or expressed as progressive gates.

## Latest Local PR-Gate Evidence

Latest validation on `feature/enterprise-backend-refactor-baseline`:

1. `git fetch origin --prune`; `git branch -r --no-merged origin/main`
   produced no unmerged remote branches, so no durable governance truth was stranded on remote
   branches during this pre-merge pass.
2. `make check` passed, including ruff, format check, static quality gates, OpenAPI quality,
   API vocabulary, domain-product validation, first-party Python security inventory, mypy, and
   `2,912` unit tests.
3. `make ci` passed, including the same static and contract/security gates, migration smoke,
   durable recovery drill, dependency audit with `0` known vulnerabilities, `2,912` unit tests,
   `308` integration tests, `21` e2e tests, combined line coverage at `99%`, and Docker image
   build for `lotus-performance:ci`.
4. `git diff --check` passed.
5. `../lotus-platform/automation/Sync-RepoWikis.ps1 -CheckOnly -Repository lotus-performance`
   detected expected publication drift for `Validation-and-CI.md` because this branch changes the
   repo-authored wiki source. Publish the wiki after this branch is merged to `main`; do not
   publish unmerged branch truth.

Latest branch-coverage hardening evidence on `feature/lineage-branch-coverage-hardening`:

1. `make branch-coverage-baseline` passed with `2,929` unit tests, `308` integration tests, and
   `21` e2e tests under `pytest --cov-branch`.
2. The generated `quality/coverage_inventory.md` records combined line coverage at `99.23%`,
   branch coverage at `95.96%`, `4,408` total branches, `178` missing branches, and `164` partial
   branches.
3. `app/services/lineage_metadata_store.py` dropped out of the top branch-gap table after focused
   operator-supportability tests covered cleanup no-ops, invalid lineage-payload quarantine,
   recovery seek-cursor filtering, pending inspection projection, legacy schema no-op migration,
   PostgreSQL returned-row validation, and runtime-store cache resolution.
4. Branch coverage remains report-only; no fail-under threshold or GitHub blocking lane is added in
   this slice.

Latest observability branch-coverage hardening evidence on `feature/observability-branch-coverage-hardening`:

1. `python -m pytest tests\unit\test_observability.py --cov=app.observability --cov-branch --cov-report=term-missing --cov-report=json:output\observability-branch-coverage.json` passed with `31` focused tests and `100%` focused branch coverage for `app/observability.py`.
2. `make branch-coverage-baseline` passed with `2,942` unit tests, `308` integration tests, and
   `21` e2e tests under `pytest --cov-branch`.
3. The generated `quality/coverage_inventory.md` records combined line coverage at `99.31%`,
   branch coverage at `96.26%`, `4,408` total branches, `165` missing branches, and `161` partial
   branches.
4. `app/observability.py` dropped out of the top branch-gap table after focused tests covered
   logging setup, source-product correlation fallback, request middleware propagation and reset,
   supportability/freshness counters, durable queue collector idempotency, instrumentator route
   resolver patching, included-router fallback, effective-candidate matching, and non-route objects.
5. Branch coverage remains report-only; no fail-under threshold or GitHub blocking lane is added in
   this slice.

Latest support-brief workflow-pack branch-coverage hardening evidence on `feature/support-brief-branch-coverage-hardening`:

1. `python -m pytest tests\unit\services\test_support_brief_workflow_pack.py --cov=app.services.inspection.support_brief_workflow_pack --cov-branch --cov-report=term-missing --cov-report=json:output\support-brief-branch-coverage.json` passed with `13` focused tests and `100%` focused branch coverage for `app/services/inspection/support_brief_workflow_pack.py`.
2. `make branch-coverage-baseline` passed with `2,948` unit tests, `308` integration tests, and
   `21` e2e tests under `pytest --cov-branch`.
3. The generated `quality/coverage_inventory.md` records combined line coverage at `99.36%`,
   branch coverage at `96.53%`, `4,408` total branches, `153` missing branches, and `151` partial
   branches.
4. `app/services/inspection/support_brief_workflow_pack.py` dropped out of the top branch-gap table after focused tests covered non-200 Lotus AI responses, malformed execution payloads, unavailable fallback without a valid run, optional source-reference projection, invalid workflow-pack run payload rejection, non-list action/finding payloads, and ready/default summary-note posture.
5. Branch coverage remains report-only; no fail-under threshold or GitHub blocking lane is added in
   this slice.

Latest attribution branch-coverage hardening evidence on `feature/attribution-branch-coverage-hardening`:

1. `python -m pytest tests\unit\engine\test_attribution.py tests\unit\engine\test_attribution_supportability.py --cov=engine.attribution --cov-branch --cov-report=term-missing --cov-report=json:output\attribution-branch-coverage.json` passed with `64` focused tests and `100%` focused branch coverage for `engine/attribution.py`.
2. `make branch-coverage-baseline` passed with `2,956` unit tests, `308` integration tests, and
   `21` e2e tests under `pytest --cov-branch`.
3. The generated `quality/coverage_inventory.md` records combined line coverage at `99.38%`,
   branch coverage at `96.76%`, `4,408` total branches, `143` missing branches, and `141` partial
   branches.
4. `engine/attribution.py` dropped out of the top branch-gap table after focused tests covered
   empty linked-return handling, invalid base-weight metadata, same-currency local/FX preservation,
   sparse resampling without return-presence flags, partial effect-column linking, direct
   currency-attribution requirement fail-fast behavior, unsupported model no-op fallback, and
   by-instrument orchestration through `run_attribution_calculations`.
5. Branch coverage remains report-only; no fail-under threshold or GitHub blocking lane is added in
   this slice. README, wiki, repository context, platform context, skills, and agent context did not
   need updates because this slice changed test evidence only and did not change commands, API
   contracts, runtime topology, operator workflow, or cross-repo ownership.
6. PR-grade local validation passed: `make lint`, `make check`, `make ci`, `git diff --check`,
   stranded-truth reconciliation, and `Sync-RepoWikis.ps1 -CheckOnly -Repository lotus-performance`
   (`DiffCount 0`).
6. PR-grade local validation passed: `make lint`, `make check`, `make ci`, `git diff --check`,
   stranded-truth reconciliation, and `Sync-RepoWikis.ps1 -CheckOnly -Repository lotus-performance`
   (`DiffCount 0`).

Latest ROR branch-coverage hardening evidence on `feature/ror-branch-coverage-hardening`:

1. `python -m pytest tests\unit\engine\test_ror.py --cov=engine.ror --cov-branch --cov-report=term-missing --cov-report=json:output\ror-branch-coverage.json` passed with `25` focused tests and `100%` focused branch coverage for `engine/ror.py`.
2. `make branch-coverage-baseline` passed with `2,967` unit tests, `308` integration tests, and
   `21` e2e tests under `pytest --cov-branch`.
3. The generated `quality/coverage_inventory.md` records combined line coverage at `99.39%`,
   branch coverage at `96.91%`, `4,408` total branches, `136` missing branches, and `134` partial
   branches.
4. `engine/ror.py` dropped out of the top branch-gap table after focused tests covered decimal
   gross return no-op division, forced currency-decomposition guardrails, short-leg compounding,
   empty compounding blocks, FX configuration failure behavior, non-currency-dimensional FX rate
   series, empty hedge series, cumulative local/FX component projection, and NIP carry-forward.
5. Branch coverage remains report-only; no fail-under threshold or GitHub blocking lane is added in
   this slice. README, wiki, repository context, platform context, skills, and agent context did not
   need updates because this slice changed test evidence only and did not change commands, API
   contracts, runtime topology, operator workflow, or cross-repo ownership.

Latest compute job store branch-coverage hardening evidence on `feature/compute-job-store-branch-hardening`:

1. `python -m pytest tests\unit\services\test_compute_job_store.py --cov=app.services.compute_job_store --cov-branch --cov-report=term-missing --cov-report=json:output\compute-job-store-branch-coverage.json` passed with `62` focused tests and `100%` focused branch coverage for `app/services/compute_job_store.py`.
2. `make branch-coverage-baseline` passed with `2,974` unit tests, `308` integration tests, and
   `21` e2e tests under `pytest --cov-branch`.
3. The generated `quality/coverage_inventory.md` records combined line coverage at `99.45%`,
   branch coverage at `97.07%`, `4,408` total branches, `129` missing branches, and `129` partial
   branches.
4. `app/services/compute_job_store.py` dropped out of the top branch-gap table after focused tests
   covered stored request-identity fallback, filtered and unfiltered pending-job listing, missing
   active timestamp projection, defensive unresolved-payload failure behavior, and explicit
   database URL runtime-store resolution.
5. Branch coverage remains report-only; no fail-under threshold or GitHub blocking lane is added in
   this slice. README, wiki, repository context, platform context, skills, and agent context did not
   need updates because this slice changed test evidence only and did not change commands, API
   contracts, runtime topology, operator workflow, or cross-repo ownership.

Latest returns-series branch-coverage hardening evidence on `feature/returns-series-branch-hardening`:

1. `python -m pytest tests\unit\services\test_returns_series_service.py --cov=app.services.returns_series_service --cov-branch --cov-report=term-missing --cov-report=json:output\returns-series-branch-coverage.json` passed with `76` focused tests.
2. `make branch-coverage-baseline` passed with `2,980` unit tests, `308` integration tests, and
   `21` e2e tests under `pytest --cov-branch`.
3. The generated `quality/coverage_inventory.md` records combined line coverage at `99.47%`,
   branch coverage at `97.21%`, `4,408` total branches, `123` missing branches, and `123` partial
   branches.
4. `app/services/returns_series_service.py` reached `100%` combined branch coverage after focused
   tests covered empty and invalid portfolio daily-return normalization, empty and duplicate
   benchmark-series normalization, cumulative active-return alignment with an empty selected
   series, and strict-intersection behavior when benchmark returns are not selected.
5. `make lint`, `make check`, and `make ci` passed locally; `make ci` included migration smoke,
   dependency audit with `0` known vulnerabilities, Python security inventory with `0` findings,
   `2,980` unit tests, `308` integration tests, `21` e2e tests, 99% line coverage, and Docker
   image build. `git diff --check` passed with only the regenerated coverage-inventory line-ending
   warning, stranded-truth reconciliation found no unmerged remote branches, and
   `Sync-RepoWikis.ps1 -CheckOnly -Repository lotus-performance` reported `DiffCount 0`.
6. Branch coverage remains report-only; no fail-under threshold or GitHub blocking lane is added in
   this slice. README, wiki, repository context, platform context, skills, and agent context did not
   need updates because this slice changed test evidence only and did not change commands, API
   contracts, runtime topology, operator workflow, or cross-repo ownership.

Latest data-policy branch-coverage hardening evidence on `feature/policies-branch-hardening`:

1. `python -m pytest tests\unit\engine\test_policies.py --cov=engine.policies --cov-branch --cov-report=term-missing --cov-report=json:output\policies-branch-coverage.json` passed with `25` focused tests and `100%` focused branch coverage for `engine/policies.py`.
2. `make branch-coverage-baseline` passed with `2,984` unit tests, `308` integration tests, and
   `21` e2e tests under `pytest --cov-branch`.
3. The generated `quality/coverage_inventory.md` records combined line coverage at `99.49%`,
   branch coverage at `97.35%`, `4,408` total branches, `117` missing branches, and `117` partial
   branches.
4. `engine/policies.py` reached `100%` combined branch coverage after focused tests covered
   no-op market-value and cash-flow overrides, ignored-day requests that match no valuation date,
   first-row ignored-day protection, empty outlier-sample handling, and outlier-only policy
   pass-through behavior.
5. `make check` passed with static quality, architecture-boundary, duplicate-code,
   observability-readiness, no-alias, OpenAPI, API vocabulary, domain-product, first-party security,
   mypy, and `2,984` unit tests.
6. `make ci` passed with migration and durable-schema gates, dependency health with `0` known
   vulnerabilities, first-party security with `0` Bandit findings, `2,984` unit tests, `308`
   integration tests, `21` e2e tests, 99% blocking line coverage, and Docker build.
7. Branch coverage remains report-only; no fail-under threshold or GitHub blocking lane is added in
   this slice. README, wiki, repository context, platform context, skills, and agent context did not
   need updates because this slice changed test evidence only and did not change commands, API
   contracts, runtime topology, operator workflow, or cross-repo ownership.

## Next Updates

Future commits should update this report when they:

1. add non-blocking quality tooling,
2. generate a new measured scorecard value,
3. split or reduce a hotspot module,
4. add a new CI quality gate,
5. convert a `not-yet-measured` dimension into `measured`,
6. convert a report-only measurement into a regression-blocking or strict gate.
