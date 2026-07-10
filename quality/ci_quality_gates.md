# Lotus Performance Progressive CI Quality Gates

Report date: 2026-07-06
Branch: `feat/performance-architecture-boundary-refactor`
Baseline sources: `quality/baseline_report.md`, `quality/refactor_health_report.md`, `quality/quality_scorecard.md`
Mode: progressive gate map; remediated complexity, architecture-boundary, router-thinness,
duplicate-code, repository hygiene, observability-readiness, domain-product validation,
deterministic API evaluation, test taxonomy breadth, Python security posture, license compliance,
and container supply-chain evidence are now enforced or produced in CI.

## Purpose

This document maps the performance hardening quality program to the repository's actual CI lanes.
It is intentionally progressive: new enterprise-grade gates should first produce repeatable
measurements, then block regressions against an agreed baseline, and only then enforce strict
thresholds. The goal is real quality convergence, not a cosmetic checklist that cannot be run by
developers or GitHub Actions.

## Current Blocking CI Lanes

| Lane | Trigger | Current blocking checks |
| --- | --- | --- |
| Remote Feature Lane | Pushes to non-`main` branches and manual dispatch | workflow lint, static quality gates, contract/security gates, domain-product validation, deterministic API evaluation, test taxonomy breadth, unit tests |
| Pull Request Merge Gate | Pull requests targeting `main` and manual dispatch | workflow lint, static quality gates, contract/security gates, domain-product validation, deterministic API evaluation, test taxonomy breadth, compatibility `Lint Typecheck Security` aggregate, migration smoke, unit, integration, and e2e tests, combined coverage floor at 99 percent, Docker build, container SBOM and vulnerability-report artifact publication |
| Main Releasability Gate | Pushes to `main` and manual dispatch | workflow lint, static quality gates, contract/security gates, domain-product validation, deterministic API evaluation, test taxonomy breadth, migration smoke, unit, integration, and e2e tests, combined coverage floor at 99 percent, coverage artifact publication, Docker build, container SBOM/vulnerability artifact publication, SBOM provenance attestation |
| PR Auto Merge | Pull request lifecycle events | queues rebase auto-merge and branch deletion after required checks pass using `LOTUS_AUTOMERGE_TOKEN`; when the governed token is absent the helper skips with a warning so a human or release actor can merge without suppressing Main Releasability evidence |

`Static Quality Gates` verifies installed dependencies, Ruff lint/format, monetary-float safety,
repository hygiene, complexity regression, architecture-boundary regression, router/middleware
thinness, duplicate-code regression, no-alias governance, observability-readiness marker
regression, and mypy type safety. `Contract Security Gates` verifies OpenAPI quality, API
vocabulary governance, domain-product contract validation, deterministic demo-critical API
evaluation, test taxonomy breadth, migration smoke where the lane requires it, and dependency
security plus first-party Python static security. These jobs run in parallel before test execution
to reduce CI wall-clock time without dropping any gate.

The PR lane also publishes `PR Merge Gate / Lint Typecheck Security` as a lightweight aggregate over
the split static-quality and contract-security jobs. It exists to satisfy the current GitHub
required-check contract while preserving the faster parallel lane structure.

GitHub Actions jobs use `make install-ci` so CI installs runtime and development dependencies without
performing developer-workstation pre-commit hook setup. Local contributors should continue using
`make install` when they need the hook installation side effect.

## Gate Promotion Model

| Phase | CI posture | Promotion standard |
| --- | --- | --- |
| Phase 0 - Inventory | Report-only artifacts track current facts and gaps | Measurement source is documented and reproducible locally. |
| Phase 1 - Report-only tooling | CI may generate artifacts without failing the lane | Tool output is stable enough to review and false positives are understood. |
| Phase 2 - Regression blocking | CI fails only when the branch worsens against the accepted baseline | Baseline file, local command, ownership, and remediation guidance exist. |
| Phase 3 - Strict enterprise gate | CI fails when the repository misses the agreed target | Threshold is justified by repeated green runs and aligned with PR Merge Gate expectations. |

No gate should move from one phase to the next until it has:

1. a repository-native command or script,
2. a documented local developer command,
3. an explicit CI lane placement,
4. a baseline artifact or threshold,
5. a false-positive and exception policy,
6. remediation guidance,
7. evidence that the gate is not duplicating another stronger check.

## Current Gate Family Status

| Gate family | Current status | Next target |
| --- | --- | --- |
| Ruff lint and format | Blocking in all quality lanes through `make lint` | Keep blocking; use as the style and simple-correctness baseline. |
| Monetary float guard | Blocking through `make lint` | Keep blocking for finance-domain numeric safety. |
| Repository hygiene | Blocking through `make lint` via `make repository-hygiene-gate`; current baseline has 0 tracked local byproduct findings across Git-tracked paths | Keep blocking. Exceptions should be avoided; if a generated artifact must become durable source truth, move it under a governed docs/contracts/evidence path and document why it is source-owned. |
| GitHub Actions runtime guard | Blocking through `make lint` via `make github-action-runtime-guard`; every workflow job must declare a role-sized `timeout-minutes` value, and artifact upload/download actions must remain on Node 24-compatible major versions | Keep blocking. New workflow jobs must carry bounded execution budgets sized to their lane role instead of relying on GitHub's broad platform default timeout. |
| Calculation engine version guard | Blocking through `make lint` via `make calculation-engine-version-gate`; production calculation paths must use `CALCULATION_ENGINE_VERSION` for hash identity instead of `APP_VERSION` or legacy per-family literals | Keep blocking. Change the governed token only when methodology, calculation logic, canonicalization, compatibility semantics, or reproducibility behavior changes. |
| mypy typecheck | Blocking in feature, PR, and main lanes | Keep blocking; expand typed boundary cleanup through normal refactor slices. |
| Unit tests | Blocking in feature, PR, and main lanes | Keep blocking; add focused tests when refactoring hotspots. |
| Integration and e2e tests | Blocking in PR and main lanes | Keep blocking at merge/release lanes; use targeted local subsets during slices. |
| Test taxonomy | Blocking through `make quality-test-taxonomy-gate`, which runs `scripts/python_test_taxonomy_inventory.py --limit 30 --min-api-runtime-tests 656 --min-contract-governance-tests 136 --max-uncategorized-tests 969`; current AST inventory shows 304 modules, 3,506 source test functions, 684 integration/API/runtime test functions, 147 contract/governance test functions, 350 observability/readiness test functions, 161 quality/security test functions, 1,570 analytics-domain test functions, and 950 uncategorized test functions | Keep the current measured preservation baseline blocking. Classify domain tests through stable taxonomy rules instead of allowing uncategorized growth. |
| License compliance | Blocking through `make license-compliance-gate`, which validates `contracts/license-compliance-policy.v1.json` against `quality/license_compliance_inventory.md`; current inventory covers 45 runtime/development packages, with 43 allowed packages, 2 review-required packages covered by active exceptions, 0 blocked packages, and 0 missing-exception findings | Keep blocking. Regenerate with `python scripts/license_compliance_inventory.py --write` after dependency changes, and keep exceptions owner-bound and time-bound before release. |
| Combined line coverage | Blocking at 99 percent in PR and main lanes; local full coverage runs use `make test-coverage`, split CI test jobs use `make test-coverage-shard`, and artifact aggregation uses `make coverage-combine-gate`; branch coverage is preserved separately by `make branch-coverage-baseline` evidence | Keep blocking and preserve the local coverage inventory as scorecard evidence. Do not embed raw pytest or coverage commands in workflow YAML for governed test lanes. |
| Branch coverage | Measured report-only in `quality/coverage_inventory.md` through `make branch-coverage-baseline`; current baseline is 98.00 percent across 4,406 branches, with 88 missing and 88 partial branches | Keep report-only until repeated runs, exception policy, remediation guidance, and CI lane placement are agreed. Review the top branch gaps before proposing any threshold. |
| Dependency verification | Blocking through `python -m pip check` and dependency-health scripts | Keep blocking; preserve project-scoped dependency-health evidence. |
| Dependency vulnerabilities | `pip-audit` is available, security audit is already blocking through repo script, and report-only output is captured in `quality/dependency_security_report.md` | Keep the report current when dependency pins, audit tooling, or exception policy changes. |
| OpenAPI quality | Blocking through `scripts/openapi_quality_gate.py`; measured further through `quality/api_completeness_inventory.md`; clean API completeness inventory is guarded by `tests/unit/scripts/test_openapi_completeness_inventory.py` | Keep the blocking gate and unit-level clean-inventory guard; only add a separate workflow gate if the report remains stable and adds value beyond existing OpenAPI checks. |
| API vocabulary and no-alias governance | Blocking in feature, PR, and main lanes | Keep blocking and preserve RFC-0067 vocabulary discipline. |
| Quality baseline snapshot workflow | Report run in `.github/workflows/quality-baseline.yml`; calls `make quality-baseline` to generate ignored raw inventory snapshots under `output/quality-baseline/`, uploads those snapshots with curated `quality/*.md` source reports, and runs `make quality-evaluation-gate` without `continue-on-error` | Keep as a reporting aid for baseline artifacts while preserving hard failure for deterministic API evaluation and test taxonomy regression. |
| Migration smoke | Blocking in PR and main lanes | Keep blocking outside feature lane unless a migration-heavy slice needs earlier proof. |
| Docker build | Blocking in PR and main lanes through `make container-supply-chain-evidence`, which delegates to `make docker-build` before evidence generation and targets the production `runtime` Dockerfile stage | Keep blocking and keep generated runtime/demo state out of the build context. Do not reinstall development/test dependencies in the production runtime image. |
| Container supply-chain evidence | Report-only artifact production in PR and main lanes through `make container-supply-chain-evidence`; builds the non-root production runtime image with non-secret Git/build metadata, writes a CycloneDX SBOM and high/critical Trivy vulnerability JSON under ignored `output/container-security/`, exposes the matching runtime identity shape at `/version`, and Main Releasability attests SBOM provenance with `actions/attest-build-provenance@v3` | Keep artifact publication mandatory. Promote `make container-vulnerability-gate` to blocking only after the first PR/main artifacts are reviewed and any accepted high/critical exceptions are owner-bound, time-bound, and documented in `quality/container_supply_chain_report.md`. |
| Domain data product validation | Blocking locally through `make check` and `make ci`; blocking in Feature, PR Merge, and Main Releasability contract/security jobs through `make domain-product-validate`; CI checks out `sgajbi/lotus-platform` under `.lotus-platform` so governed platform contract truth is available without relying on a local sibling checkout | Keep blocking wherever API contract and runtime supportability claims are evaluated. |
| Complexity and maintainability | Max cyclomatic complexity and D-F function count are blocking through `make quality-complexity-gate`; current measured max CC is `7` against the enforced ceiling of `8`, and maintainability index remains measured in `quality/complexity_inventory.md` through `scripts/python_complexity_inventory.py` and `radon` | Keep the configured max-CC ceiling at `8` until a separate gate-ratcheting slice establishes repeated green evidence, and keep D-F count at `0`; keep MI report-only until a stable remediation threshold and exception policy exist. |
| Function-size hotspots | Measured in `quality/function_size_inventory.md` through a repo-native standard-library scanner; largest production functions now measure `81` lines | Use as refactor-planning evidence; do not block CI until stable thresholds and exclusions are agreed. |
| Duplicate code hotspots | Blocking through `make quality-duplicate-code-gate`; current report shows 0 duplicate hotspot groups at `--min-lines 12` with `--max-groups 0` | Keep blocking at zero accepted first-party duplicate function-body hotspot groups; future increases require a documented reason and a better reusable abstraction decision. |
| Dead-code detection | Measured in `quality/dead_code_inventory.md` through `scripts/python_dead_code_inventory.py` and `vulture`; 60% findings are dominated by framework/model false positives, while 80% findings are zero | Add reviewed allowlist before considering any regression-blocking gate. |
| Dependency hygiene | Measured in `quality/dependency_hygiene_report.md` through `scripts/python_dependency_hygiene_inventory.py` and `deptry`; direct imported transitive dependencies are closed, and reviewed runtime-only DEP002 declarations are explicitly allowlisted in the repo scanner | Keep report-only until the allowlist policy and CI placement are stable. |
| Python security scanning | Blocking through `make python-security-gate`; current Bandit scan has zero high, medium, and low findings, with two targeted skipped tests for reviewed environment-name false positives | Keep blocking for first-party runtime paths; future exceptions must be targeted, documented, and test-backed. |
| Documentation readiness | Measured in `quality/documentation_inventory.md` through `scripts/python_documentation_inventory.py`; current report shows 8/8 README markers, 21 wiki pages, 236 markdown files, 20 endpoint certification docs, 4/4 API catalog files, 68 docs regression test functions, and 12.01 percent public definition docstring coverage | Keep report-only until docstring scope, generated/model exclusions, and remediation thresholds are agreed. |
| OpenAPI Spectral linting | Not configured; no `.spectral.yaml` present | Decide whether Spectral adds value beyond the existing OpenAPI gate before adding it. |
| Architecture boundaries | Blocking through `make quality-architecture-gate`; latest report shows 0 enforced import-boundary and route-workflow command-boundary findings, plus 63 report-only application-service concrete-store findings | Keep blocking for the current router/core/domain and route-workflow command rules; promote additional boundary rules only after report-only inventory proves stability. |
| Public docstring coverage | Not configured; `interrogate` not present | Measure before deciding whether public docstrings are a useful gate for this service. |
| Router and middleware thinness | Blocking through `make quality-router-thinness-gate`; current snapshot shows 0 router findings and 0 middleware findings at `--threshold 80` with `--max-findings 0` | Keep blocking for the current router/middleware function-size threshold; revisit only with documented exceptions and tests. |
| RFC 7807 error consistency | Measured report-only through `scripts/openapi_completeness_inventory.py`; current inventory shows 0 error responses missing named problem/error schemas | Keep the report-only inventory clean while separately planning any runtime migration from legacy string-detail errors to full RFC 7807 payloads. |
| Observability and operational contracts | Blocking through `make quality-observability-readiness-gate`, which runs `scripts/python_observability_readiness_inventory.py --limit 30 --max-missing 0`; current report shows 28/28 expected implementation markers, 0 missing markers, 443 family-mapped readiness test functions, 14 deployable alert rules, 10 dashboard panels, and 0 monitoring artifact violations | Keep the zero-missing marker and zero monitoring-artifact-violation gate blocking in feature, PR, and main static quality lanes. Broader maturity scoring and overlap-aware test counting remain report-only planning evidence. |
| Deterministic API evaluation | Blocking through `make quality-evaluation-gate`, which delegates to `make demo-api-certification` and `make quality-test-taxonomy-gate`; Feature, PR Merge, Main Releasability, and Quality Baseline workflows run it without `continue-on-error`. It calls demo-critical health/readiness, capabilities, calculation, returns, workspace, mandate, and composite TWR APIs with deterministic data, writes ignored JSON evidence under `output/demo-api-certification/*.json`, and blocks test-taxonomy breadth regression; `.dockerignore` excludes generated `output`, `lineage_data`, and local SQLite database artifacts from Docker build contexts | Keep blocking while the seeded data remains deterministic and isolated. Any future exception must be explicit, time-boxed, and tracked as a product-readiness or quality-governance defect instead of soft-failing CI. |

## LP-CR-1603 Container Supply-Chain Intake

| Intake item | Decision |
| --- | --- |
| Baseline | GitHub Security settings show secret scanning and push protection enabled, but Dependabot alerts/security updates are disabled and CodeQL has no analysis. Repo scans showed Docker build gates without SBOM, image vulnerability, or attestation evidence. |
| Failure mode addressed | A release lane could prove only image buildability while leaving buyers and operators without package inventory, high/critical vulnerability evidence, or provenance for the container image. |
| Determinism | `make container-supply-chain-evidence` builds the pinned CI image name from Dockerfile target `runtime` and runs a pinned Trivy container image (`aquasec/trivy:0.71.2`) against Docker's local image store. Generated evidence is ignored source and uploaded as workflow artifacts. |
| Lane placement | PR Merge Gate and Main Releasability after coverage, replacing raw `make docker-build` with `make container-supply-chain-evidence`. Main Releasability also attests the SBOM artifact. |
| Exception policy | Vulnerability output is report-only until first PR/main artifacts are reviewed. Strict promotion uses `make container-vulnerability-gate`, no `continue-on-error`, and only narrow, owner-bound, time-bound high/critical exceptions. |
| Focused tests | `tests/unit/scripts/test_ci_quality_gate_wiring.py` and `tests/unit/scripts/test_container_runtime_contract.py` prove Make targets, production runtime Dockerfile posture, Compose API/worker healthchecks, workflow artifact publication, and Main Releasability attestation wiring. |
| Scorecard and ledger truth | `quality/container_supply_chain_report.md`, this gate map, `docs/operations/development-workflow-and-ci-strategy.md`, repo-local wiki source, and the codebase review ledger record the security posture. |

## LP-CR-1540 Gate Promotion Intake

| Intake item | Decision |
| --- | --- |
| Baseline | `quality/test_taxonomy_inventory.md` records 304 test modules, 3,506 source test functions, 684 API/runtime test functions, 147 contract/governance test functions, and 950 uncategorized test functions. The same inventory records 161 quality/security test functions. Issue #419 added runtime build-identity tests, issue #422 added analytics-domain XIRR boundary tests, #420 ratcheted the enforced thresholds to the current API/runtime, contract/governance, and uncategorized preservation baseline, #423 classified config/resilience tests so the uncategorized ceiling could tighten without losing coverage, #442 classified async polling cadence tests as API/runtime evidence, #454 classified core analytics footer parity as API/runtime plus contract/governance evidence, #453 classified strict fail-fast parity across completed core analytics endpoints, #417 classified runtime/static trust-telemetry evidence posture, #424 classified executable durable schema apply/verify coverage without growing uncategorized tests, #425 classified returns-series strict-intersection fill semantics coverage without growing uncategorized tests, #452 classified RFC-020 support-matrix docs governance without growing uncategorized tests, #451 classified RFC-021 gross/net support-baseline docs governance without growing uncategorized tests, #449 classified governed operator calculation-id prefix lookup coverage without growing uncategorized tests, #448 classified lineage-worker lifecycle tests as observability/readiness evidence while preserving the `969` uncategorized blocking ceiling, #447 classified stateful portfolio source port contract tests as analytics-domain evidence without growing uncategorized tests, #446 classified lineage artifact classification route tests as API/runtime evidence while staying below the uncategorized ceiling, #444 added runtime-retention restart-safety and failed-replay tests while staying below the uncategorized ceiling, #443 added async SLO/capacity contract docs coverage, #441 added upstream dependency inventory contract coverage while ratcheting the contract/governance floor to the measured count, #440 added license compliance gate tests while raising quality/security coverage, #439 added restore-validation drill coverage while staying below the uncategorized ceiling, #438 added durable database engine policy coverage while keeping the uncategorized backlog flat, #436 added runtime-retention legal-hold coverage while preserving the uncategorized ceiling, #435 added governed MARKET calendar coverage while preserving the uncategorized ceiling, #434 added retrieval metadata anti-corruption coverage while staying below the uncategorized ceiling, #433 classified stateful execution policy and submission fencing tests as API/runtime evidence while reducing uncategorized tests, #432 added container runtime contract tests without growing uncategorized tests, and #431 added calculation-engine-version policy/static-gate coverage plus public-doc guards while keeping API/runtime and uncategorized counts stable. |
| Failure mode blocked | Agents must not reduce API/runtime or contract/governance test breadth, or add unclassified tests that increase the uncategorized backlog, while still passing deterministic API certification and static checks. |
| Determinism | The scanner uses standard-library AST parsing over tracked test source and stable path/name taxonomy rules; it does not execute tests or depend on local services. |
| Lane placement | Blocking through `make quality-evaluation-gate`, and therefore local `make check`, local `make ci`, Feature Lane, PR Merge Gate, Main Releasability, and Quality Baseline workflow. |
| Exception policy | Do not soft-fail this gate. Intentional threshold changes require same-PR updates to the taxonomy inventory, CI gate map, scorecard, and review ledger with a clear reason. |
| Focused tests | `tests/unit/scripts/test_python_test_taxonomy_inventory.py` proves threshold pass/fail behavior; `tests/unit/scripts/test_ci_quality_gate_wiring.py` proves Makefile wiring and threshold arguments. |
| Scorecard and ledger truth | `quality/test_taxonomy_inventory.md`, `quality/refactor_health_report.md`, `quality/quality_scorecard.md`, and `docs/architecture/CODEBASE-REVIEW-LEDGER.md` record the promoted signal. |

## LP-CR-1536 Gate Promotion Intake

| Intake item | Decision |
| --- | --- |
| Baseline | `make demo-api-certification` has repeated green local and CI evidence in the ledger, with deterministic checks over 12 demo-critical API calls and generated JSON evidence under ignored `output/demo-api-certification/`. |
| Failure mode blocked | Agents must not ship plausible code that breaks health/readiness, capability publication, calculation outputs, workspace summary, mandate context, returns, or composite TWR demo-critical API behavior while still passing static checks. |
| Determinism | The command prepares its local runtime, seeds deterministic fixture data, validates fixed API outputs and capability enablement, and keeps generated evidence out of tracked source through repository hygiene rules. |
| Lane placement | Blocking through `make check`, `make ci`, Feature Lane, PR Merge Gate, Main Releasability, and the Quality Baseline workflow via `make quality-evaluation-gate`; contract/security jobs also checkout `sgajbi/lotus-platform` under `.lotus-platform` before `make domain-product-validate`. |
| Exception policy | Do not use `continue-on-error` for deterministic API evaluation. A broken certification is a product-readiness defect unless the failing surface is explicitly removed from supported-feature truth in the same PR. |
| Focused tests | `tests/unit/scripts/test_ci_quality_gate_wiring.py` proves Makefile aggregate wiring, GitHub workflow placement, platform-contract checkout wiring, and absence of quality-baseline soft-fail posture. Existing `tests/unit/scripts/test_demo_api_certification.py` and integration certification tests cover command behavior. |
| Scorecard and ledger truth | `quality/refactor_health_report.md`, `quality/quality_scorecard.md`, `quality/ci_quality_gates.md`, and `docs/architecture/CODEBASE-REVIEW-LEDGER.md` record the promoted signal. |

## LP-CR-1445 Gate Promotion Intake

| Intake item | Decision |
| --- | --- |
| Baseline | `git ls-files` scan has 0 tracked local byproduct findings on `lp-cr-1445-repository-hygiene-gate`. |
| Failure mode blocked | Agents and local runs must not commit Python caches, virtual environments, coverage files, build output, logs, or local database files as source truth. |
| Determinism | The scanner reads only `git ls-files` output and static path rules; it does not inspect untracked local residue or rewrite artifacts. |
| Lane placement | Blocking through `make lint`, and therefore through `make check`, `make ci`, Feature Lane, PR Merge Gate, and Main Releasability static quality jobs. |
| Exception policy | Do not allow local byproducts. If evidence must be durable, place it under governed docs/contracts/quality/wiki source and cite it explicitly. |
| Focused tests | `tests/unit/scripts/test_repository_hygiene_gate.py` covers pass behavior, cache artifacts, coverage/env artifacts, build/log/database artifacts, and Makefile wiring; `tests/unit/scripts/test_clean_generated_artifacts.py` covers cleanup planning, generated runtime/evidence roots, local SQLite/log sidecars, source-truth preservation, prune safety, and deletion scope. |
| Scorecard and ledger truth | `quality/refactor_health_report.md`, `quality/quality_scorecard.md`, and `docs/architecture/CODEBASE-REVIEW-LEDGER.md` record the new enforced signal. |

## Recommended Lane Placement For New Gates

| Gate class | First report-only lane | First blocking lane | Strict lane |
| --- | --- | --- | --- |
| Fast static checks | Remote Feature Lane | Remote Feature Lane | PR Merge Gate and Main Releasability Gate |
| Medium static analysis | Remote Feature Lane artifact | PR Merge Gate | Main Releasability Gate |
| Heavy test or coverage checks | PR Merge Gate artifact | PR Merge Gate | Main Releasability Gate |
| Docker or runtime parity checks | PR Merge Gate artifact | PR Merge Gate | Main Releasability Gate |
| Platform or cross-repo checks | Manual dispatch or platform automation | PR Merge Gate only when deterministic | Main Releasability Gate after repeated stability |

## Near-Term Quality Slices

The next hardening commits should stay small and add proof in this order:

1. reduce measured API error-contract gaps for error examples, explicit schemas, and problem-detail consistency,
2. reduce measured architecture-boundary findings through bounded router/domain extraction slices,
3. keep reducing measured complexity, function-size, and reviewed dead-code hotspots through bounded slices,
4. review runtime-only dependency declarations before removing or allowlisting them,
5. review branch-coverage gap posture before proposing a stricter branch gate.

## Non-Goals For This Slice

This slice does not:

1. change application behavior,
2. change API or Swagger contracts,
3. promote maintainability index, function-size, dead-code, documentation metrics, or broader
   observability maturity scoring to blocking gates,
4. claim enterprise-readiness completion.
