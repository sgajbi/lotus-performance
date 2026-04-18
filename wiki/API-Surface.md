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
- runtime behavior and readiness:
  [Operations Runbook](Operations-Runbook)
- upstream contract boundary:
  [Integrations](Integrations)
