# lotus-performance

Authoritative performance analytics service for the Lotus ecosystem.

Repository-local engineering context: [REPOSITORY-ENGINEERING-CONTEXT.md](REPOSITORY-ENGINEERING-CONTEXT.md)

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
4. Time-weighted return, money-weighted return, contribution, attribution, returns-series, and
   benchmark exposure context are declared as governed data products under
   `contracts/domain-data-products/`.
5. OpenAPI, API vocabulary, domain-product validation, migration, security, and Docker parity are
   part of the real merge gate.

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
- [docs/technical/RFC-0082-upstream-contract-family-map.md](docs/technical/RFC-0082-upstream-contract-family-map.md)

Grouped public surfaces are derived from the router layout in [main.py](main.py):

- `/performance`
  TWR, benchmark, contribution, executions, inspections, and lineage
- `/integration`
  capabilities, returns-series, benchmark exposure context, runtime status, runtime work items,
  runtime recoveries, recovery drill history, and runtime retention history
- platform surfaces
  `/`, `/health`, `/health/live`, `/health/ready`, `/metrics`, `/docs`, and `/openapi.json`

## Repository Layout

- `app/`
  FastAPI application layer, models, services, and workers
- `engine/`
  analytics and orchestration logic
- `core/`
  shared calculation and support foundations
- `adapters/`
  storage and integration seams
- `docs/`
  architecture, guides, runbooks, standards, RFCs, and certification evidence
- `scripts/`
  repo-native validation and operational tooling
- `tests/`
  unit, integration, e2e, benchmarks, and docs regression coverage

## Quick Start

Install dependencies:

```bash
make install
```

Run the API locally:

```bash
make run
```

Then open `/docs` or `/openapi.json`.

For topology-parity local runs, the governed runtime overlays live in
[docs/examples/](docs/examples). The production-profile compose overlay command remains:

```bash
docker compose -f docker-compose.yml -f docs/examples/docker-compose.runtime-thresholds.production.yml up
```

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
- migration and recovery smoke
  `make migration-smoke`
- retention smoke
  `make runtime-retention-smoke`
- Docker image proof
  `make docker-build`

## Validation And CI Lanes

`lotus-performance` follows the Lotus multi-lane model:

1. `Remote Feature Lane`
2. `Pull Request Merge Gate`
3. `Main Releasability Gate`

The local mapping is:

- `make check`
  lint, no-alias gate, typecheck, OpenAPI gate, API vocabulary gate, and unit tests
- `make ci`
  governance, migration smoke, security audit, unit, integration, e2e, coverage, and Docker build
- `make ci-local`
  local Docker-parity proof with full coverage and dependency checks

When a slice changes `README.md` or public guides, also run:

```bash
python -m pytest tests/unit/docs/test_public_docs_contract.py -q
```

## API Contract Notes

Important public route groups:

1. `/performance`
   TWR, benchmark, MWR, workspace summary, contribution, attribution, execution polling, and lineage
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
- benchmark exposure context is currently certified at `frequency=DAILY`; `ISSUER` remains gated
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

Repository-authored wiki pages live under [wiki/](wiki). If the GitHub wiki is published later,
keep `wiki/` as the canonical source and treat any separate `*.wiki.git` clone as publication
plumbing only.
