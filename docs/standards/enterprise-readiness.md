# Enterprise Readiness Baseline (lotus-performance)

- Standard reference: `lotus-platform/Enterprise Readiness Standard.md`
- Scope: advanced analytics API surfaces and lotus-core-integrated analytics delivery.
- Change control: RFC for shared standard changes; ADR for temporary deviations.

## Security and IAM Baseline

- Audit middleware logs privileged write operations with actor/tenant/role context.
- Allowed privileged write operations also emit audit metadata describing the governed surface and required capability when a governed write rule applies.
- Privileged operator read surfaces can be protected with capability-gated enterprise authz.
- Allowed privileged operator reads also emit audit metadata describing the governed surface and required capability.
- Sensitive operator write surfaces can require governed runtime-management capability, including `POST /integration/runtime-retention-cleanups/run`.
- Sensitive operator write surfaces can require governed runtime-management capability, including `POST /integration/recovery-drills/run`.
- Service-owned privileged actions should retain enterprise tenant and correlation context in durable evidence when that context exists at request time.
- Governed remediation actions should fence accidental manual double-submit with a service-owned cooldown before executing the mutation.
- Governed remediation actions should replay the original durable evidence for same-correlation retries of the same manual request instead of executing a duplicate mutation.
- Governed destructive actions should require a recent matching preview when the workflow supports a dry-run review stage.
- Cooldown fences should be scoped to the governed action shape so one safe operator action does not incorrectly block a distinct remediation request.
- Replay ownership must be scoped to the same operator and tenant context so reused correlation identifiers cannot replay another actor's durable evidence.
- Governed action policy should also fence in-flight same-shape execution so duplicate submissions cannot race before durable evidence is written.
- In-flight action leases should be reclaimable after a bounded stale threshold so a crashed process cannot block a governed action forever.
- Write request bodies are bounded by `ENTERPRISE_MAX_WRITE_PAYLOAD_BYTES`: trusted `Content-Length` values are rejected before request processing, while missing or malformed length headers are treated as untrusted and enforced by counting streamed ASGI body bytes.
- Sensitive attributes are redacted before audit emission.

Evidence:
- `app/enterprise_readiness.py`
- `main.py`
- `tests/unit/app/test_enterprise_readiness.py`

## API Governance Baseline

- Contract-first OpenAPI, versioned service metadata, and explicit governance rules.
- Contract and integration tests enforce compatibility expectations.

Evidence:
- `main.py`
- `tests/contract`
- `tests/integration`

## Configuration and Feature Management Baseline

- Feature flags support tenant/role scope with deterministic fallback precedence.
- Malformed feature flag configuration fails closed.

Evidence:
- `app/enterprise_readiness.py`
- `tests/unit/app/test_enterprise_readiness.py`

## Data Quality and Reconciliation Baseline

- Analytics inputs are validated and domain invariants are tested.
- Data-quality and durability controls remain aligned to lotus-core ownership boundaries.

Evidence:
- `docs/standards/durability-consistency.md`
- `tests/unit`

## Reliability and Operations Baseline

- Resilience controls, health checks, migration contract checks, and operational runbook standards are enforced.
- Runtime breach gauges, alert templates, and severity defaults are governed.
- Ingress and proxy request-size limits should be configured at or below the application `ENTERPRISE_MAX_WRITE_PAYLOAD_BYTES` value so oversized write payloads are rejected early, with the service-level stream guard retained as the final enforcement boundary.

Evidence:
- `app/clients/http_resilience.py`
- `docs/standards/scalability-availability.md`
- `docs/standards/runtime-alert-policy.md`
- `docs/standards/runtime-threshold-profiles.md`
- `docs/standards/migration-contract.md`

## Privacy and Compliance Baseline

- Audit fields include traceability attributes and apply mandatory redaction.

Evidence:
- `app/enterprise_readiness.py`
- `tests/unit/app/test_enterprise_readiness.py`

## Deviations

- Any deviation requires ADR with rationale and expiry review date.

