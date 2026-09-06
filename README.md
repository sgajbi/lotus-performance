# lotus-performance

Authoritative performance analytics service for the Lotus ecosystem.

Agent operating contract: [AGENTS.md](AGENTS.md) defines the governed reading order, skill-routing
expectations, and wiki publication rule. Repository-local engineering context:
[REPOSITORY-ENGINEERING-CONTEXT.md](REPOSITORY-ENGINEERING-CONTEXT.md).

## Purpose And Scope

`lotus-performance` is the Lotus domain service for benchmark-aware performance analytics,
returns-series integration, durable execution tracking, and lineage-backed reproducibility.

It owns:

- time-weighted return (`POST /performance/twr`)
- benchmark performance (`POST /performance/benchmark`)
- money-weighted return (`POST /performance/mwr`)
- front-office workspace summary (`POST /performance/workspace-summary`)
- contribution (`POST /performance/contribution`)
- attribution (`POST /performance/attribution`)
- composite performance (`POST /performance/composites/twr`,
  `POST /performance/composites/inspect`)
- canonical returns-series integration (`POST /integration/returns/series`)
- benchmark exposure context (`POST /integration/benchmarks/exposure-context`)
- execution polling, runtime control-plane, and lineage retrieval surfaces

It does not own source-of-record portfolio, benchmark, index, FX, or reference datasets, and it
does not delegate performance conclusions to `lotus-core`.

## Current Operational Posture

1. `lotus-performance` is an active domain service consumed primarily through `lotus-gateway`.
2. Stateful integration with `lotus-core` is live under the RFC-0082 contract-family map.
3. Async execution, lineage capture, and durable runtime-control surfaces are shipped parts of the
   contract.
4. Time-weighted return, money-weighted return, contribution, attribution, composite performance,
   returns-series, and benchmark exposure context are declared as governed data products under
   `contracts/domain-data-products/`.
5. OpenAPI, API vocabulary, domain-product validation, migration, security, Docker parity, and
   container supply-chain evidence are part of the real merge gate.
6. Compose initializes persisted lineage-volume ownership before any non-root API or worker starts;
   PR and Main Releasability prove root-owned-volume repair, restart health, and retained evidence.

## Enterprise Readiness Evidence

Enterprise buyers should evaluate `lotus-performance` as an implementation-backed analytics
service, not as a calculation demo. The current bank-readiness evidence includes:

- source-boundary discipline:
  `lotus-core` owns source data while `lotus-performance` owns performance methodology and emitted
  analytics contracts
- supportability metadata:
  calculation responses carry supportability, warning, reason-code, benchmark-context, currency,
  and lineage posture where the workflow supports it
- operational control plane:
  runtime status, work-item, recovery, recovery-drill, retention, health, readiness, and metrics
  surfaces expose real runtime posture for operators
- governed product contracts:
  domain-data-product declarations, trust telemetry fixtures, OpenAPI quality gates, API
  vocabulary checks, and no-alias governance are part of repo-native validation
- release evidence:
  `make check`, `make ci`, and `make ci-local` map local proof to the Lotus multi-lane delivery
  model
- container supply-chain evidence:
  PR/Main release lanes build `lotus-performance:ci` with Git SHA, branch, build timestamp,
  repository URL, CI run id, and image-digest metadata fields, generate a CycloneDX SBOM and
  high/critical image vulnerability report, and Main Releasability also attests SBOM provenance.
  Runtime `GET /version` exposes the same support-safe identity fields for release audit.
- license and IP compliance:
  repo metadata and `LICENSE` declare MIT, while `make license-compliance-gate` validates
  `contracts/license-compliance-policy.v1.json` against the generated
  `quality/license_compliance_inventory.md`; regenerate the inventory with
  `python scripts/license_compliance_inventory.py --write` after dependency changes and review
  owner-bound/time-bound exceptions before release
- repository hygiene:
  `make repository-hygiene-gate` blocks tracked local byproducts such as Python caches, virtual
  environments, local coverage files, build outputs, logs, and local databases; `make clean`
  delegates to the tested cleanup utility in `scripts/clean_generated_artifacts.py` and removes
  ignored runtime/evidence roots such as `artifacts/`, `output/`, and `lineage_data/` plus local
  SQLite/log sidecars while preserving source truth under `docs/`, `contracts/`, `wiki/`, and
  `quality/`
- observability guardrails:
  `make quality-observability-readiness-gate` blocks missing health/metrics, correlation,
  structured logging, metrics, readiness markers, deployable Prometheus alert rules, and
  Grafana-style dashboard panels before feature branches can degrade runtime supportability

This is not a blanket production certification for every client environment. Final bank-buyable
readiness still requires the target deployment, entitlement model, SLOs, observability integration,
security review, data entitlements, and operating runbooks to be validated for that client context.

## Architecture At A Glance

The current runtime is a four-service topology:

1. `performance-analytics`
2. `performance-compute-executor`
3. `performance-lineage-worker`
4. `performance-lineage-db`

Optional ops profile:

5. `performance-runtime-retention-worker`

Source-of-truth runtime docs:

- [docs/technical/architecture.md](docs/technical/architecture.md)
- [docs/technical/runtime_topology.md](docs/technical/runtime_topology.md)
- [docs/runbooks/lineage-volume-recovery.md](docs/runbooks/lineage-volume-recovery.md)
- [docs/technical/RFC-0082-upstream-contract-family-map.md](docs/technical/RFC-0082-upstream-contract-family-map.md)

Grouped public surfaces are derived from the router layout in [main.py](main.py):

- `/performance`
  TWR, benchmark, contribution, attribution, composite performance, executions, inspections, and
  lineage
- `/integration`
  capabilities, returns-series, benchmark exposure context, runtime status, runtime work items,
  runtime recoveries, recovery drill history, and runtime retention history
- platform surfaces
  `/`, `/health`, `/health/live`, `/health/ready`, `/metrics`, `/docs`, and `/openapi.json`

## Repository Layout

- `app/`
  FastAPI application layer, models, services, and workers; see [app/README.md](app/README.md)
- `engine/`
  analytics and orchestration logic; see [engine/README.md](engine/README.md)
- `core/`
  shared calculation and support foundations; see [core/README.md](core/README.md)
- `adapters/`
  storage and integration seams; see [adapters/README.md](adapters/README.md)
- `contracts/`
  domain data-product and trust-telemetry contracts; see
  [contracts/README.md](contracts/README.md)
- `docs/`
  architecture, guides, runbooks, standards, RFCs, and certification evidence; see
  [docs/README.md](docs/README.md)
- `monitoring/`
  deployable alert and dashboard artifacts; see [monitoring/README.md](monitoring/README.md)
- `quality/`
  quality scorecards, inventories, and CI evidence; see [quality/README.md](quality/README.md)
- `scripts/`
  repo-native validation and operational tooling; see [scripts/README.md](scripts/README.md)
- `tests/`
  unit, integration, e2e, benchmarks, and docs regression coverage; see
  [tests/README.md](tests/README.md)
- `wiki/`
  authored source for the GitHub wiki; see [wiki/README.md](wiki/README.md)

## Quick Start

### Prerequisites

Resolved from `PATH`. Nothing here assumes an operating system, drive or workspace layout:

| tool | version | source of the claim |
|---|---|---|
| Python | 3.11 | every CI lane pins `PYTHON_VERSION: "3.11"`; note that `pyproject.toml` declares no `requires-python`, so CI is the only authority |
| `make` | any | every gate and lane is a make target |
| Docker | any recent | compose overlays and `make ci`'s `docker-build` |
| `git` | any recent | version control |

### Install

`make install` runs `pip install` directly rather than into a managed environment, so create and
activate a virtualenv FIRST. PEP 668 distributions — most current Linux packages, and Homebrew
Python on macOS — mark the system interpreter externally managed and refuse a system-wide
`pip install`, so on such a machine the documented first step fails before anything else runs.
This has not been reproduced here: it is the specified behaviour of PEP 668 plus the observation
below, not an error anyone on this project has hit.

On Linux or macOS:

```bash
python -m venv .venv
. .venv/bin/activate
make install
```

On Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
make install
```

CI does not need this step because `actions/setup-python` supplies an isolated interpreter, which
is why the requirement is invisible in a green pipeline and only appears on a developer machine.

Run the API locally:

```bash
make run
```

This serves on port **8000** (`uvicorn --port 8000`, matching the container, which EXPOSEs and
listens on 8000). Then open `/docs` or `/openapi.json`.

Under Docker Compose the same service is reachable on the HOST at `${PA_HOST_PORT:-8002}`, which
maps to 8000 in the container. Examples further down this file use `127.0.0.1:8002` because they
assume the compose path; if you started the service with `make run`, use `127.0.0.1:8000`
instead.

For topology-parity local runs, the governed runtime overlays live in
[docs/examples/](docs/examples). The production-profile compose overlay command remains:

```bash
docker compose -f docker-compose.yml -f docs/examples/docker-compose.runtime-thresholds.production.yml up
```

The production overlay also sets `ENTERPRISE_RUNTIME_PROFILE=production`,
`ENTERPRISE_ENFORCE_AUTHZ=true`, `ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ=true`, and
`ENTERPRISE_ENFORCE_RUNTIME_CONFIG=true`. Replace the sample `ENTERPRISE_PRIMARY_KEY_ID` before
using the overlay outside local rehearsal; production-like profiles fail closed at startup when
those controls are missing.

Canonical stateful TWR inspection can be validated locally with:

```bash
python scripts/validate_canonical_twr_inspection.py \
  --performance-base-url http://127.0.0.1:8002 \
  --core-control-plane-base-url http://127.0.0.1:8202
```

This probes the lotus-core query-control-plane analytics-input POST routes, runs stateful TWR for
`PB_SG_GLOBAL_BAL_001` as of `2026-04-10`, and verifies the RFC-045 inspection evidence has no
source-economics or reconciliation regressions.

## Common Commands

- install
  `make install`
- fast local gate
  `make check`
- PR-grade local gate
  `make ci`
- Docker-parity local gate
  `make ci-local`
- full test and coverage run
  `make test-all`
- report-only branch coverage baseline
  `make branch-coverage-baseline`
- migration and recovery smoke
  `make migration-smoke`
- durable schema apply/verify
  `make migration-apply`
- retention smoke
  `make runtime-retention-smoke`
- lineage volume restart recovery
  `make lineage-volume-recovery-smoke`
- quality baseline reports
  `make quality-baseline`
- demo API certification
  `make demo-api-certification`
- RFC-0002 Idea opportunity evidence gate
  `make idea-opportunity-evidence-gate`
- RFC-0002 Idea opportunity runtime evidence artifact
  `make idea-opportunity-runtime-evidence`
- observability readiness marker gate
  `make quality-observability-readiness-gate`
- repository hygiene gate
  `make repository-hygiene-gate`
- Docker image proof
  `make docker-build`
- container supply-chain evidence
  `make container-supply-chain-evidence`
- license compliance evidence
  `make license-compliance-gate`

## Demo Readiness

For a demo, client review, or internal delivery checkpoint, use one repeatable backend API sweep
before presenting product claims:

```bash
make demo-api-certification
```

The command seeds deterministic synthetic data where needed, calls the supported demo-critical API
routes, asserts expected domain figures, verifies enabled capability publication, and writes
machine-readable evidence to `output/demo-api-certification/latest.json`. Review the evidence with
[docs/guides/demo_readiness.md](docs/guides/demo_readiness.md), then cross-check claims against
[wiki/Supported-Features.md](wiki/Supported-Features.md).

This backend certification is necessary demo evidence for `lotus-performance`; it is not a blanket
production certification and does not replace Gateway or Workbench runtime proof when presenting
front-office product surfaces.

For `lotus-idea` RFC-0002 Slice 16/17 source-proof consumption, run:

```bash
make idea-opportunity-runtime-evidence
```

The command produces a source-safe `ReturnsSeriesBundle:v1` evidence artifact at
`output/idea-opportunity-runtime-evidence/latest.json`. The artifact proves Performance-owned
runtime evidence for underperformance review and missing-benchmark readiness scenarios using
digests, execution receipts, coverage, freshness, benchmark-context posture, and bounded metric
summaries only. It does not publish raw portfolio identifiers, raw return-series observations,
Gateway/Workbench proof, client-publication proof, or supported-feature promotion for Idea.

## Validation And CI Lanes

`lotus-performance` follows the Lotus multi-lane model:

1. `Remote Feature Lane`
2. `Pull Request Merge Gate`
3. `Main Releasability Gate`

The local mapping is:

- `make check`
  lint, repository hygiene, static quality gates including observability-readiness markers,
  no-alias gate, typecheck, OpenAPI gate, API vocabulary gate, and unit tests
- `make ci`
  governance, migration smoke, security audit, unit, integration, e2e, coverage, Docker build, and
  container supply-chain evidence
- `make ci-local`
  local Docker-parity proof with full coverage and dependency checks
- `make branch-coverage-baseline`
  report-only branch coverage measurement. It runs unit, integration, and e2e suites with
  `pytest --cov-branch`, writes raw coverage JSON under `output/branch-coverage/`, and refreshes
  `quality/coverage_inventory.md`. It does not add or enforce a branch-coverage threshold.
- `make quality-baseline`
  report-only baseline refresh for the enterprise refactor scorecard. It updates the durable
  `quality/baseline_report.md` and writes raw scanner snapshots under
  `output/quality-baseline/`. The Quality Baseline Snapshot workflow uses the same target so local
  and GitHub evidence are generated from one command surface.
- `make demo-api-certification`
  one request-level demo certification sweep covering health/readiness, integration capabilities,
  TWR, MWR, benchmark, returns-series, contribution, attribution, workspace summary, mandate health
  context, and composite persisted-fact TWR with deterministic synthetic seed data and expected
  calculation assertions. It writes machine-readable evidence to
  `output/demo-api-certification/latest.json`. The Quality Baseline Snapshot workflow also runs
  this command as report-only CI evidence and uploads the JSON artifact; it is not yet a blocking
  readiness gate.
- `make idea-opportunity-evidence-gate`
  focused unit gate for the RFC-0002 Idea opportunity evidence contract. It verifies source-safe
  payload bounds, underperformance posture, missing-benchmark posture, coverage, freshness,
  benchmark-context handling, and unsupported-promotion preservation.
- `make idea-opportunity-runtime-evidence`
  local artifact generator for source-safe `ReturnsSeriesBundle:v1` proof consumed by
  `lotus-idea` RFC-0002 Slice 16/17 implementation tracking. The output is runtime evidence from
  `lotus-performance`, not a substitute for Core benchmark-assignment, Gateway, Workbench,
  data-mesh, client-publication, or deployment certification evidence.
- `make container-supply-chain-evidence`
  release-image evidence for `lotus-performance:ci`. It builds the image with non-secret Git SHA,
  branch, build timestamp, repository URL, CI run id, and image-digest metadata fields, writes a
  CycloneDX SBOM and high/critical Trivy vulnerability report under `output/container-security/`,
  and is published by PR/Main workflows. Main Releasability also attests the SBOM artifact. Runtime
  `GET /version` exposes the same support-safe metadata shape so operators can correlate a live
  service to image labels and release evidence. The vulnerability report is report-only until the
  first PR/main baseline is reviewed; promotion to strict blocking uses
  `make container-vulnerability-gate` and the exception policy in
  [quality/container_supply_chain_report.md](quality/container_supply_chain_report.md).
- `make license-compliance-gate`
  validates that `LICENSE`, dependency license policy, and generated first-/third-party inventory
  remain aligned before release. Run `python scripts/license_compliance_inventory.py --write` after
  editing `requirements.txt` or `requirements-dev.txt`, review new license families, and keep any
  review-required package exception owner-bound and time-bound in
  [contracts/license-compliance-policy.v1.json](contracts/license-compliance-policy.v1.json).

When a slice changes `README.md` or public guides, also run:

```bash
python -m pytest tests/unit/docs/test_public_docs_contract.py -q
```

## API Contract Notes

Important public route groups:

1. `/performance`
   TWR, benchmark, MWR, workspace summary, contribution, attribution, composite performance,
   execution polling, and lineage
2. `/integration`
   capabilities, returns-series, benchmark exposure context, runtime status, work items, recoveries,
   recovery drills, and retention history

Async-capable workflows use one common pattern:

1. submit the request
2. receive either a final response or `202 Accepted`
3. poll `/performance/executions/{calculation_id}`
4. retrieve the endpoint-specific async result from the returned `result_path`

Operational note:

- caller may omit `calculation_id`

Representative async result routes include:

- `/performance/twr/results/{calculation_id}`
- `/performance/workspace-summary/results/{calculation_id}`
- `/integration/returns/series/results/{calculation_id}`

Current request-model highlights:

- TWR, benchmark, contribution, and attribution use `input_mode: "stateless" | "stateful"` and
  `analyses`
- TWR benchmark-aware request shape still uses `include_benchmark`
- stateless request shapes still use `valuation_points` where applicable and the deeper guides
  explain the current compatibility posture
- lotus-performance stamps source consumer identity server-side for stateful sourcing contracts
- benchmark-aware responses can emit `benchmark_context` and `relative_performance`
- returns-series stateful benchmark sourcing supports
  `benchmark.return_source="vendor_series"`
- stateful benchmark sourcing now defaults to lotus-performance benchmark calculation
- returns-series outputs include `active_returns` and `cumulative_active_returns`
- source-safe RFC-0002 Idea opportunity proof for returns-series underperformance and
  missing-benchmark readiness is generated through `make idea-opportunity-runtime-evidence`
- attribution emits source-owned `currency_attribution_totals` for portfolio-level
  Karnosky-Singer FX attribution when `currency_mode=BOTH` is source-ready
- MWR stateless requests may supply complete `source_preconverted_fx_evidence`; the service
  validates per-input FX provenance and emits `currency_evidence` while still computing on a
  single reporting-currency schedule
- benchmark exposure context is certified at `frequency=DAILY` for `POSITION`, `SECTOR`,
  `ASSET_CLASS`, and `ISSUER`; issuer groups use lotus-core index-catalog issuer labels
- Older examples using `period_type` are not current
- Older examples using `daily_data` are not current

Key deeper references:

- Human API map:
  [docs/guides/api_reference.md](docs/guides/api_reference.md)
- Complete service reference:
  [docs/guides/complete_service_reference.md](docs/guides/complete_service_reference.md)
- TWR certification:
  [docs/technical/twr-endpoint-certification.md](docs/technical/twr-endpoint-certification.md)
- Benchmark certification:
  [docs/technical/benchmark-endpoint-certification.md](docs/technical/benchmark-endpoint-certification.md)
- MWR certification:
  [docs/technical/mwr-endpoint-certification.md](docs/technical/mwr-endpoint-certification.md)
- Contribution certification:
  [docs/technical/contribution-endpoint-certification.md](docs/technical/contribution-endpoint-certification.md)
- Contribution Analytics product wiki:
  [wiki/Contribution-Analytics.md](wiki/Contribution-Analytics.md)
- Attribution certification:
  [docs/technical/attribution-endpoint-certification.md](docs/technical/attribution-endpoint-certification.md)
- Attribution Analytics product wiki:
  [wiki/Attribution-Analytics.md](wiki/Attribution-Analytics.md)
- Composite Performance guide:
  [docs/guides/composite_performance.md](docs/guides/composite_performance.md)
- Composite TWR certification:
  [docs/technical/composite-twr-endpoint-certification.md](docs/technical/composite-twr-endpoint-certification.md)
- Composite Performance product wiki:
  [wiki/Composite-Performance.md](wiki/Composite-Performance.md)
- Benchmark Exposure Context Endpoint Certification:
  [docs/technical/benchmark-exposure-context-endpoint-certification.md](docs/technical/benchmark-exposure-context-endpoint-certification.md)

Additional async result references:

- `/performance/benchmark/results/{calculation_id}`

## Integration Boundaries

Primary ecosystem relationships:

- downstream consumers:
  `lotus-gateway`, selected `lotus-risk` stateful workflows, and operator/support tooling
- upstream dependencies:
  `lotus-core` control-plane and source-data contracts for stateful sourcing

Current transport posture remains REST/OpenAPI through `CORE_CONTROL_PLANE_BASE_URL`; there is no
current gRPC contract between `lotus-performance` and `lotus-core`.

Governed base-URL examples for the control-plane contract family are:

1. local ingress: `http://core-control.dev.lotus`
2. local host-port: `http://127.0.0.1:8202`
3. local Docker-to-host: `http://host.docker.internal:8202`
4. platform-stack internal: `http://lotus-core-control:8002`

## Operations And Runtime Posture

The runtime is intentionally durable:

- `/health/ready` returns `200` only when the API can support executor-backed and lineage-backed workflows
- `/performance/executions/{calculation_id}` is the canonical polling surface
- async result routes are durable, not process-local memory
- runtime status, work-item, recovery-drill, runtime-recovery, and retention surfaces are governed operator APIs

Key operator and certification references:

- [monitoring/prometheus/lotus-performance-alerts.prometheusrule.json](monitoring/prometheus/lotus-performance-alerts.prometheusrule.json)
- [monitoring/grafana/lotus-performance-operability-dashboard.json](monitoring/grafana/lotus-performance-operability-dashboard.json)
- [docs/runbooks/runtime-alerts.md](docs/runbooks/runtime-alerts.md)
- [docs/operations/mwr-alert-rule-templates.md](docs/operations/mwr-alert-rule-templates.md)
- [docs/runbooks/durable-metadata-recovery.md](docs/runbooks/durable-metadata-recovery.md)
- [docs/runbooks/runtime-retention-cleanup.md](docs/runbooks/runtime-retention-cleanup.md)
- [docs/technical/lineage-endpoint-certification.md](docs/technical/lineage-endpoint-certification.md)
- [docs/technical/platform-surfaces-endpoint-certification.md](docs/technical/platform-surfaces-endpoint-certification.md)
- [docs/technical/execution-polling-endpoint-certification.md](docs/technical/execution-polling-endpoint-certification.md)
- [docs/technical/runtime-status-endpoint-certification.md](docs/technical/runtime-status-endpoint-certification.md)
- [docs/technical/runtime-work-items-endpoint-certification.md](docs/technical/runtime-work-items-endpoint-certification.md)
- [docs/technical/runtime-recoveries-endpoint-certification.md](docs/technical/runtime-recoveries-endpoint-certification.md)
- [docs/technical/recovery-drills-endpoint-certification.md](docs/technical/recovery-drills-endpoint-certification.md)
- [docs/technical/runtime-retention-endpoint-certification.md](docs/technical/runtime-retention-endpoint-certification.md)
- [docs/technical/twr-inspection-endpoint-certification.md](docs/technical/twr-inspection-endpoint-certification.md)
- [docs/technical/twr-mwr-response-attribute-certification.md](docs/technical/twr-mwr-response-attribute-certification.md)

## Documentation Map

- demo readiness:
  [docs/guides/demo_readiness.md](docs/guides/demo_readiness.md)
- human API map:
  [docs/guides/api_reference.md](docs/guides/api_reference.md)
- complete service reference:
  [docs/guides/complete_service_reference.md](docs/guides/complete_service_reference.md)
- reproducibility and lineage:
  [docs/guides/reproducibility.md](docs/guides/reproducibility.md)
- workspace-summary guide:
  [docs/guides/workspace_summary.md](docs/guides/workspace_summary.md)
- TWR inspection checks:
  [docs/guides/twr_inspection_checks.md](docs/guides/twr_inspection_checks.md)
- methodology index:
  [docs/technical/methodology_index.md](docs/technical/methodology_index.md)
- local RFC estate:
  [docs/RFCs/RFC-INDEX.md](docs/RFCs/RFC-INDEX.md)

## Wiki Source

Repository-authored wiki pages live under [wiki/](wiki). Keep `wiki/` as the canonical source and
use the governed platform wiki sync automation to publish it. Treat any separate `*.wiki.git` clone
as publication plumbing only.
