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

