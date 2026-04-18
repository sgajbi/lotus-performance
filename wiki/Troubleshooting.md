# Troubleshooting

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

References:

- [docs/runbooks/runtime-alerts.md](../docs/runbooks/runtime-alerts.md)
- [docs/technical/runtime-status-endpoint-certification.md](../docs/technical/runtime-status-endpoint-certification.md)

## README or public-guide edits fail validation

Run:

```bash
python -m pytest tests/unit/docs/test_public_docs_contract.py -q
```

Treat failures there as public-contract drift first, not as superficial wording checks.
