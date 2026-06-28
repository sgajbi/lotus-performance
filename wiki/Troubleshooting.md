# Troubleshooting

Use this page for first-response triage. Keep incident notes grounded in observable runtime state:
health payloads, readiness payloads, execution records, lineage metadata, runtime work items,
recovery history, retention history, logs, metrics, and exact request identifiers.

## Service starts but readiness fails

Check:

- durable metadata database reachability
- runtime config required by enterprise-readiness validation
- whether the API is intentionally draining

References:

- [docs/technical/runtime_topology.md](../docs/technical/runtime_topology.md)
- [docs/runbooks/durable-metadata-recovery.md](../docs/runbooks/durable-metadata-recovery.md)

## Stateful requests fail against upstream sources

Check:

- `CORE_CONTROL_PLANE_BASE_URL`
- local ingress or host-port reachability to `lotus-core`
- whether the request depends on source data that is absent, not a methodology fallback

Reference:

- [docs/technical/RFC-0082-upstream-contract-family-map.md](../docs/technical/RFC-0082-upstream-contract-family-map.md)

## Async workflows stall

Check:

- `GET /integration/runtime-status`
- `GET /integration/runtime-work-items`
- `GET /integration/runtime-recoveries`
- `GET /performance/executions/{calculation_id}`

Escalate with:

- `calculation_id`
- endpoint family, for example TWR, MWR, contribution, attribution, workspace summary, or returns series
- execution state and stage
- oldest pending work-item age
- recent recovery attempt status

References:

- [docs/runbooks/runtime-alerts.md](../docs/runbooks/runtime-alerts.md)
- [docs/technical/runtime-status-endpoint-certification.md](../docs/technical/runtime-status-endpoint-certification.md)

## Demo certification fails

Check:

- whether the failure is an API reachability problem, a seeded-data problem, or a calculation
  assertion problem
- `output/demo-api-certification/latest.json`
- the specific route and check name reported by `make demo-api-certification`
- whether Gateway or Workbench evidence is being requested even though only backend API proof was
  run

References:

- [docs/guides/demo_readiness.md](../docs/guides/demo_readiness.md)
- [Supported Features](Supported-Features)

## README or public-guide edits fail validation

Run:

```bash
python -m pytest tests/unit/docs/test_public_docs_contract.py -q
```

Treat failures there as public-contract drift first, not as superficial wording checks.
