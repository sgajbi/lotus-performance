# Lotus Performance Refactor Quality Scorecard

Report date: 2026-07-10
Branch: `feat/performance-architecture-boundary-refactor`
Baseline source: `quality/baseline_report.md`
Current source: `quality/refactor_health_report.md`
Mode: phase-zero scorecard; static-quality and evaluation enforcement includes complexity,
architecture, router-thinness, duplicate-code, repository hygiene, observability-readiness,
domain-product validation, deterministic API evaluation, test taxonomy breadth gates, and
container supply-chain evidence.

## Purpose

This document is the first before/after quality scorecard for the performance hardening stream.
It is intended to track measurable quality posture change over refactor phases, where the same
metrics in each section are updated with each meaningful slice.

## Scorecard

### Code Health

| Metric | Baseline | Current | Delta | Status | Evidence |
| --- | ---: | ---: | ---: | --- | --- |
| Python files | 480 | 607 | 127 | measured | `quality/baseline_report.md`; `quality/refactor_health_report.md` |
| Python package markers | 18 | 18 | 0 | measured | `quality/baseline_report.md`; `quality/refactor_health_report.md` |
| Python LOC | 104,454 | 185,003 | 80,549 | measured | `quality/baseline_report.md`; `quality/refactor_health_report.md` |
| Largest Python file LOC | 2,399 | 2,503 | 104 | measured | `quality/baseline_report.md`; `quality/refactor_health_report.md` |
| Largest production file LOC | 1,156 | 1,991 | 835 | measured | `quality/refactor_health_report.md`; `quality/architecture_boundary_inventory.md` |
| Python test modules | 228 | 296 | 68 | measured | `quality/baseline_report.md`; `quality/refactor_health_report.md` |
| Collected tests | 2,035 | 3,676 | 1,641 | measured | `quality/baseline_report.md`; `quality/refactor_health_report.md` |
| Duplicate code hotspots | 0 | 0 | 0 | enforced | `quality/duplicate_code_inventory.md`; `quality/refactor_health_report.md`; `make quality-duplicate-code-gate` |
| Tracked local byproduct findings | unknown | 0 | n/a | enforced | `scripts/repository_hygiene_gate.py`; `make repository-hygiene-gate`; `quality/refactor_health_report.md` |

### Complexity And Maintainability

| Metric | Baseline | Current | Delta | Status | Evidence |
| --- | ---: | ---: | ---: | --- | --- |
| Max cyclomatic complexity | unknown | 7 | n/a | enforced | `quality/complexity_inventory.md`; `quality/refactor_health_report.md`; `make quality-complexity-gate` |
| High-complexity functions (D-F) | unknown | 0 | n/a | enforced | `quality/complexity_inventory.md`; `quality/refactor_health_report.md`; `make quality-complexity-gate` |
| Average maintainability index | unknown | 55.52 | n/a | measured | `quality/complexity_inventory.md`; `quality/refactor_health_report.md` |
| Largest functions by LOC | unknown | 81 | n/a | measured | `quality/function_size_inventory.md`; `quality/refactor_health_report.md`; `StatefulInputService._fetch_position_chunk(...)` remains the largest production function at `81` lines |

### Architecture

| Metric | Baseline | Current | Delta | Status | Evidence |
| --- | ---: | ---: | ---: | --- | --- |
| Enforced import-boundary findings | unknown | 0 | n/a | enforced | `quality/architecture_boundary_inventory.md`; `quality/refactor_health_report.md`; `make quality-architecture-gate` |
| Routers with infrastructure imports | unknown | 0 | n/a | enforced | `quality/architecture_boundary_inventory.md`; `quality/refactor_health_report.md`; `make quality-architecture-gate` |
| Engine/core infra/framework imports | unknown | 0 | n/a | enforced | `quality/architecture_boundary_inventory.md`; `quality/refactor_health_report.md`; `make quality-architecture-gate` |
| Route workflow direct DTO calls | unknown | 0 | n/a | enforced | `quality/architecture_boundary_inventory.md`; `scripts/python_architecture_boundary_inventory.py`; `make quality-architecture-gate` |
| Application-service concrete-store imports | unknown | 63 | n/a | measured | `quality/architecture_boundary_inventory.md`; `scripts/python_architecture_boundary_inventory.py`; execution polling pilot moved behind `ExecutionPollingStore` |
| Large production service hotspots (LOC > 1000) | 3 | 8 | 5 | measured | `quality/refactor_health_report.md`; `quality/architecture_boundary_inventory.md` |
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
| Integration/API/runtime test functions | unknown | 656 | n/a | enforced | `quality/test_taxonomy_inventory.md`; `quality/refactor_health_report.md`; `make quality-test-taxonomy-gate` |
| Contract/governance test functions | unknown | 131 | n/a | enforced | `quality/test_taxonomy_inventory.md`; `quality/refactor_health_report.md`; `make quality-test-taxonomy-gate` |
| Uncategorized test functions | unknown | 969 | n/a | enforced ceiling | `quality/test_taxonomy_inventory.md`; `make quality-test-taxonomy-gate`; issue #423 classified config/resilience tests and ratcheted the gate to the current measured preservation baseline |

### Security and Dependencies

| Metric | Baseline | Current | Delta | Status | Evidence |
| --- | ---: | ---: | ---: | --- | --- |
| Bandit high findings | unknown | 0 | n/a | enforced | `quality/python_security_inventory.md`; `quality/refactor_health_report.md`; `make python-security-gate` |
| Bandit medium findings | unknown | 0 | n/a | enforced | `quality/python_security_inventory.md`; `quality/refactor_health_report.md`; `make python-security-gate` |
| Bandit low findings | unknown | 0 | n/a | enforced | `quality/python_security_inventory.md`; `quality/refactor_health_report.md`; `make python-security-gate` |
| Dependency vulnerability findings | unknown | 0 | n/a | measured | `quality/dependency_security_report.md`; `quality/refactor_health_report.md` |
| Dependency hygiene findings | unknown | 0 | n/a | measured | `quality/dependency_hygiene_report.md`; `quality/refactor_health_report.md` |
| Container SBOM artifact | unknown | 1 | n/a | measured | `quality/container_supply_chain_report.md`; `make container-supply-chain-evidence`; PR/Main artifact upload |
| Container vulnerability report artifact | unknown | 1 | n/a | measured | `quality/container_supply_chain_report.md`; `make container-supply-chain-evidence`; PR/Main artifact upload |
| Container vulnerability gate | unknown | 0 | n/a | planned-gate | `make container-vulnerability-gate`; promote after first PR/main baseline review and documented exceptions |
| SBOM provenance attestation | unknown | 1 | n/a | measured | `quality/container_supply_chain_report.md`; Main Releasability `actions/attest-build-provenance@v3` |

### Operational Readiness

| Metric | Baseline | Current | Delta | Status | Evidence |
| --- | ---: | ---: | ---: | --- | --- |
| Operational readiness markers | unknown | 28 | n/a | enforced | `quality/observability_readiness_inventory.md`; `quality/refactor_health_report.md`; `make quality-observability-readiness-gate` |
| Missing readiness markers | unknown | 0 | n/a | enforced | `quality/observability_readiness_inventory.md`; `quality/refactor_health_report.md`; `make quality-observability-readiness-gate` |
| Deployable monitoring alert rules | unknown | 14 | n/a | enforced | `monitoring/prometheus/lotus-performance-alerts.prometheusrule.json`; `quality/observability_readiness_inventory.md`; `make quality-observability-readiness-gate` |
| Deployable monitoring dashboard panels | unknown | 10 | n/a | enforced | `monitoring/grafana/lotus-performance-operability-dashboard.json`; `quality/observability_readiness_inventory.md`; `make quality-observability-readiness-gate` |
| Correlation propagation markers | unknown | 6 | n/a | measured | `quality/observability_readiness_inventory.md`; `quality/refactor_health_report.md` |
| Structured logging markers | unknown | 6 | n/a | measured | `quality/observability_readiness_inventory.md`; `quality/refactor_health_report.md` |
| Metrics markers | unknown | 6 | n/a | measured | `quality/observability_readiness_inventory.md`; `quality/refactor_health_report.md` |
| Health/readiness markers | unknown | 6 | n/a | measured | `quality/observability_readiness_inventory.md`; `quality/refactor_health_report.md` |
| Demo API certification command | unknown | 1 | n/a | enforced | `make quality-evaluation-gate`; `make demo-api-certification`; `quality/refactor_health_report.md` |
| Test taxonomy gate | unknown | 1 | n/a | enforced | `make quality-evaluation-gate`; `make quality-test-taxonomy-gate`; `quality/test_taxonomy_inventory.md` |

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
| Total metrics tracked | 54 | All metrics in this file are now measured or explicitly staged, with selected zero-finding, breadth, and release-evidence signals enforced or produced separately. |
| Measured metrics | 53 | Selected measured metrics are now also enforced or produced through blocking static-quality, security, deterministic API evaluation, test-taxonomy, or container evidence lanes. Branch coverage and container vulnerability output are measured report-only and are not promoted to strict gates yet. |
| Not-yet-measured metrics | 0 | The scorecard no longer carries an unmeasured branch-coverage entry. OpenAPI Spectral and public-docstring gate decisions remain outside this scorecard until scoped separately. |
| Planned gates | 1 | `make container-vulnerability-gate` exists but remains unpromoted until first PR/main container artifacts establish a reviewed high/critical image vulnerability baseline and exception policy. |
| Latest architecture signal | 1 | API routes for TWR, workspace-summary, contribution, benchmark, and returns-series now map request DTOs into workflow command objects before application workflow entry points. `ROUTE_WORKFLOW_DTO_DIRECT_CALL` is enforced at `0`; application-service concrete-store imports remain visible as `63` report-only findings. |

## Method Note

- Values are intentionally conservative and map to artifacts already generated from
  repository-native scripts; selected zero-finding, deterministic API evaluation, and
  test-taxonomy breadth signals are now blocking gates.
- `n/a` indicates that a comparable historical pre-baseline value is not yet available in-repo.
- The next slice should review the branch-coverage gap profile before proposing any threshold,
  exception policy, or CI lane placement.
