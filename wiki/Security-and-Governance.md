# Security and Governance

## Governing standards

The most relevant current governance for this repo includes:

- `lotus-platform/rfcs/RFC-0067-centralized-api-vocabulary-inventory-and-openapi-documentation-governance.md`
- `lotus-platform/rfcs/RFC-0072-platform-wide-multi-lane-ci-validation-and-release-governance.md`
- `lotus-platform/rfcs/RFC-0073-lotus-ecosystem-engineering-context-and-agent-guidance-system.md`
- `lotus-platform/rfcs/RFC-0082-lotus-core-domain-authority-and-analytics-serving-boundary-hardening.md`

## Local governance surfaces

- enterprise readiness:
  [docs/standards/enterprise-readiness.md](../docs/standards/enterprise-readiness.md)
- durability consistency:
  [docs/standards/durability-consistency.md](../docs/standards/durability-consistency.md)
- durable schema inventory:
  [docs/standards/durable-schema-inventory.md](../docs/standards/durable-schema-inventory.md)
- migration contract:
  [docs/standards/migration-contract.md](../docs/standards/migration-contract.md)
- runtime alerts:
  [docs/standards/runtime-alert-policy.md](../docs/standards/runtime-alert-policy.md)

## Important cautions

- emitted figures are product-facing and must stay auditably correct
- privileged operator read and write surfaces are governed, not ad hoc
- async execution and lineage behavior must remain durable and observable
- benchmark and stateful integration wording must stay truthful to shipped behavior
