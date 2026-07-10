# Contracts Pack

## Purpose

This pack contains repo-authored contracts that make `lotus-performance` data-product,
trust-telemetry, license compliance, and integration posture machine-readable.

## Audience

- platform and data-mesh governance teams,
- backend engineers adding or consuming source products,
- agents validating contract drift before PR merge.

## Reading Order

1. `domain-data-products/README.md`
2. `domain-data-products/lotus-performance-products.v1.json`
3. `domain-data-products/lotus-performance-consumers.v1.json`
4. `domain-data-products/lotus-performance-upstream-dependency-inventory.v1.json`
5. `license-compliance-policy.v1.json`
6. `trust-telemetry/README.md`
7. the matching validator or docs regression test

## Ownership Boundaries

| Contract family | Owner | Validation |
| --- | --- | --- |
| Domain data products | `lotus-performance` for produced products and consumer declarations | `make domain-product-validate` |
| Upstream dependency inventory | `lotus-performance` for active route-level dependency coverage and time-bound exceptions | `make domain-product-validate` |
| License compliance | `lotus-performance` for first-party license truth, dependency license policy, and review-required exceptions | `make license-compliance-gate` |
| Trust telemetry | `lotus-performance` evidence for active governed products | `tests/unit/test_trust_telemetry.py` |

## Maintenance Notes

- Keep declarations aligned with implementation and source-authority truth.
- Do not declare a product or dependency as active until the owning producer/consumer contract and
  tests support that claim.
- Every active `CoreIntegrationService.get_*` route must be covered by either a consumer declaration
  or a time-bound exception in `lotus-performance-upstream-dependency-inventory.v1.json`.
- Regenerate `quality/license_compliance_inventory.md` with
  `python scripts/license_compliance_inventory.py --write` after dependency changes and review
  license-policy exceptions before release.
- Update `docs/technical/RFC-0082-upstream-contract-family-map.md` when upstream source posture
  changes.
