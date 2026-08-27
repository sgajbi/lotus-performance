# Security and Governance

## Governing standards

The most relevant current governance for this repo includes:

- `lotus-platform/rfcs/RFC-0067-centralized-api-vocabulary-inventory-and-openapi-documentation-governance.md`
- `lotus-platform/rfcs/RFC-0072-platform-wide-multi-lane-ci-validation-and-release-governance.md`
- `lotus-platform/rfcs/RFC-0073-lotus-ecosystem-engineering-context-and-agent-guidance-system.md`
- `lotus-platform/rfcs/RFC-0082-lotus-core-domain-authority-and-analytics-serving-boundary-hardening.md`

## Local governance surfaces

- enterprise readiness:
  [docs/standards/enterprise-readiness.md](https://github.com/sgajbi/lotus-performance/blob/main/docs/standards/enterprise-readiness.md)
- durability consistency:
  [docs/standards/durability-consistency.md](https://github.com/sgajbi/lotus-performance/blob/main/docs/standards/durability-consistency.md)
- durable schema inventory:
  [docs/standards/durable-schema-inventory.md](https://github.com/sgajbi/lotus-performance/blob/main/docs/standards/durable-schema-inventory.md)
- migration contract:
  [docs/standards/migration-contract.md](https://github.com/sgajbi/lotus-performance/blob/main/docs/standards/migration-contract.md)
- runtime alerts:
  [docs/standards/runtime-alert-policy.md](https://github.com/sgajbi/lotus-performance/blob/main/docs/standards/runtime-alert-policy.md)
- license compliance:
  [contracts/license-compliance-policy.v1.json](https://github.com/sgajbi/lotus-performance/blob/main/contracts/license-compliance-policy.v1.json)
  and [quality/license_compliance_inventory.md](https://github.com/sgajbi/lotus-performance/blob/main/quality/license_compliance_inventory.md)

## Production runtime authorization

Production-like profiles are explicit: `ENTERPRISE_RUNTIME_PROFILE=production`, `prod`, or
`staging`. In those profiles the application fails closed at startup unless:

- `ENTERPRISE_ENFORCE_AUTHZ=true`
- `ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ=true`
- `ENTERPRISE_ENFORCE_RUNTIME_CONFIG=true`
- `ENTERPRISE_PRIMARY_KEY_ID` is configured
- governed runtime-status degradation thresholds are set to non-zero production-like values

Governed operator write surfaces such as `POST /integration/recovery-drills/run` and
`POST /integration/runtime-retention-cleanups/run` require enterprise identity plus
`operations.runtime.manage`. Governed operator read surfaces such as
`GET /integration/runtime-status` require enterprise identity plus `operations.runtime.read`.
Execution polling and endpoint-specific async result routes are not readable by calculation id
alone when privileged-read authz is enabled; callers need enterprise identity plus either
`operations.runtime.read` or `X-Portfolio-Id` matching the durable execution `portfolio_id`.
Local relaxed mode remains explicit through `ENTERPRISE_RUNTIME_PROFILE=local` or an unset runtime
profile with the authz switches disabled. Local mode is the diagnostic exception where disabled
`0` runtime degradation thresholds are allowed; disabled `0` runtime degradation thresholds are allowed
only in local mode.

## Important cautions

- emitted figures are product-facing and must stay auditably correct
- privileged operator read and write surfaces are governed, not ad hoc
- write request payload limits are enforced by both trusted `Content-Length` rejection and
  service-owned streamed body-byte counting when length headers are missing or malformed; the
  governed default is 1 MiB (`1048576` bytes), and ingress/API gateway limits should be at or below
  the effective `ENTERPRISE_MAX_WRITE_PAYLOAD_BYTES` value
- async execution and lineage behavior must remain durable and observable
- `make migration-apply` must remain executable schema apply/verify evidence, not a prose-only
  contract check
- `make license-compliance-gate` must pass before release; after dependency changes regenerate
  `quality/license_compliance_inventory.md` with
  `python scripts/license_compliance_inventory.py --write` and review owner-bound/time-bound
  license exceptions in `contracts/license-compliance-policy.v1.json`
- benchmark and stateful integration wording must stay truthful to shipped behavior
