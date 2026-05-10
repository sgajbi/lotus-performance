# API Surface

## Surface groups

`lotus-performance` exposes three major surface families:

1. analytics surfaces
2. integration surfaces
3. operator and platform surfaces

Use this page as the short navigation layer. Use the deep guides for payload detail.

## Analytics surfaces

Authoritative analytics routes:

- `POST /performance/twr`
- `POST /performance/benchmark`
- `POST /performance/mwr`
- `POST /performance/workspace-summary`
- `POST /performance/contribution`
- `POST /performance/attribution`
- `POST /performance/inspections/twr`

Async and supportability routes:

- `GET /performance/executions/{calculation_id}`
- `GET /performance/twr/results/{calculation_id}`
- `GET /performance/benchmark/results/{calculation_id}`
- `GET /performance/workspace-summary/results/{calculation_id}`
- `GET /performance/contribution/results/{calculation_id}`
- `GET /performance/attribution/results/{calculation_id}`
- `GET /performance/inspections/{inspection_id}`
- `GET /performance/lineage/{calculation_id}`

## Integration surfaces

Cross-service and downstream-facing routes:

- `GET /integration/capabilities`
- `POST /integration/returns/series`
- `GET /integration/returns/series/results/{calculation_id}`
- `POST /integration/benchmarks/exposure-context`

`POST /performance/mwr` supports both stateless caller-owned inputs and stateful lotus-core
timeseries sourcing. In stateful mode it is the source-owned investor capital-timing methodology
surface for downstream product experiences; clients should consume its emitted MWR response and
supportability block rather than rebuilding cash-flow schedules locally. The response now carries
calculation-quality metadata (`status`, `reason_codes`, `warnings`, `fallback_reason`,
`is_approximation`) plus `holding_period_return` and XIRR convergence diagnostics so demos,
support workflows, and downstream UI panels can explain whether the value is an annualized XIRR, a
Modified Dietz fallback, Simple Dietz result, or not calculable.

`POST /performance/contribution` supports both stateless caller-owned inputs and stateful lotus-core
portfolio/position timeseries sourcing. In stateful mode it is the source-owned contribution
methodology surface for downstream product experiences; clients should consume emitted total,
local, and FX contribution results rather than reconstructing contribution downstream.

`POST /performance/attribution` supports both stateless caller-owned inputs and stateful lotus-core
portfolio/position, benchmark, and source currency sourcing. In stateful mode it is the source-owned
attribution methodology surface for downstream product experiences; clients should consume emitted
allocation, selection, interaction, active-return, and currency-attribution results rather than
reconstructing attribution downstream.

## Operator and platform surfaces

Runtime and supportability routes:

- `GET /health`
- `GET /health/live`
- `GET /health/ready`
- `GET /metrics`
- `GET /integration/runtime-status`
- `GET /integration/runtime-work-items`
- `GET /integration/runtime-recoveries`
- `GET /integration/recovery-drills`
- `POST /integration/recovery-drills/run`
- `GET /integration/runtime-retention-cleanups`
- `POST /integration/runtime-retention-cleanups/run`

## Where to go next

- contract and payload detail:
  [docs/guides/api_reference.md](../docs/guides/api_reference.md)
- full examples and config inventory:
  [docs/guides/complete_service_reference.md](../docs/guides/complete_service_reference.md)
- Lotus MWR production controls and review findings:
  [docs/guides/mwr-lotus-production-controls.md](../docs/guides/mwr-lotus-production-controls.md),
  [docs/technical/mwr-industry-review-findings.md](../docs/technical/mwr-industry-review-findings.md)
- runtime behavior and readiness:
  [Operations Runbook](Operations-Runbook)
- upstream contract boundary:
  [Integrations](Integrations)
