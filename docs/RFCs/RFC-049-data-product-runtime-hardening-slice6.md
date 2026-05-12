# RFC 049 Slice 6 - Data Product, Runtime, and Platform Hardening

Date: 2026-05-12
Branch: `draft/rfc-049-composite-performance-alignment`
PR: `sgajbi/lotus-performance#162`
Status: Implemented and locally validated

## Purpose

Slice 6 promotes the implemented persisted-fact composite TWR surface into Lotus data-product
governance without overstating the remaining RFC 049 scope. The slice also closes the platform
vocabulary gap discovered during implementation: composite data products need a governed
`composite_id` identifier and period-window semantics before their trust telemetry can validate
against the platform catalog.

## Implemented Changes

### Platform Governance

Merged platform PR `sgajbi/lotus-platform#327` into `lotus-platform/main`.

That PR:

1. registered `composite_id` as a stable platform domain-data-product identifier;
2. registered `period_start` and `period_end` as governed temporal semantics;
3. regenerated `generated/domain-product-catalog.json`;
4. regenerated `generated/domain-product-dependency-graph.json`;
5. regenerated `generated/domain-product-catalog.md`;
6. passed platform contract, vocabulary, and mesh certification checks before merge.

This is a reusable platform fix, not a local lotus-performance workaround.

### lotus-performance Data Product Contract

Updated `contracts/domain-data-products/lotus-performance-products.v1.json` with
`CompositePerformanceAnalytics:v1`.

Current truthful scope:

1. product family: `analytics_output`;
2. scope level: `portfolio_set`;
3. freshness class: `batch`;
4. current route: `/performance/composites/twr`;
5. approved consumer: `lotus-gateway`;
6. identifiers: `composite_id`, `portfolio_id`, `calculation_id`, `correlation_id`;
7. required trust metadata includes source fingerprints, data quality, coverage, reconciliation,
   and lineage version;
8. lineage access class: `customer_consumable` with `customer_lineage_summary` bundle posture.

The declaration does not claim that batch/recalculation, inspector, export artifacts, Gateway
realization, Workbench realization, or client-demo support are complete. Those remain owned by later
RFC 049 slices.

### Trust Telemetry

Added `contracts/trust-telemetry/composite-performance-analytics.telemetry.v1.json`.

The snapshot binds `CompositePerformanceAnalytics:v1` to:

1. RFC 049 governance;
2. batch freshness posture;
3. persisted member-return fact source fingerprints;
4. customer-consumable lineage summary posture;
5. complete coverage and reconciled status for the current slice proof;
6. a bounded `composite-lineage-v1` lineage version.

### Tests and Documentation

Updated:

1. `tests/unit/test_domain_data_product_contracts.py`;
2. `tests/unit/test_trust_telemetry.py`;
3. `contracts/domain-data-products/README.md`;
4. `contracts/trust-telemetry/README.md`.

The tests now prevent composite data-product drift by proving:

1. the repo-native declaration includes `CompositePerformanceAnalytics`;
2. the route, scope, freshness class, identifier refs, and required metadata match the intended
   composite contract;
3. the trust telemetry snapshot references an actual declared product;
4. observed trust metadata exactly matches the required metadata set;
5. the snapshot validates with the platform trust telemetry validator and generated catalog.

## Runtime and Enterprise Hardening Assessment

| Area | Slice 6 outcome | Remaining RFC 049 closure |
| --- | --- | --- |
| Data mesh declaration | Implemented for the persisted-fact composite TWR surface. | Keep current until later APIs expand the product routes. |
| Platform vocabulary | Implemented and merged to `lotus-platform/main`. | Reuse for future composite products and avoid local vocabulary aliases. |
| Gateway publication | Declared as the approved consumer. | Slice 9 must implement and prove Gateway route realization before client/product claims. |
| Workbench publication | Not claimed in the data-product contract. | Slice 9 must update Workbench only when UI value is implementation-backed. |
| Batch/runtime isolation | Freshness posture is declared as `batch`; no separate worker is yet implemented. | Slice 7 or later must add worker/run/recalc health if introduced. |
| Observability | Existing platform gates remain active; no new runtime metric was needed for the declaration-only surface. | Add bounded composite metrics when batch runs, publish/restatement, inspector, and exports exist. |
| Audit events | No privileged operator action was added in this slice. | Add audit events when recalculation, publish, restatement, privileged reads, or exports are implemented. |
| Retention | Product contract states restatement support and lineage posture but does not add new stores in this slice. | Add retention policy when result versions, lineage manifests, and export artifacts are persisted. |
| Security | Repo-native security and dependency gates remain in CI. | Re-run after every runtime or export slice and track unresolved vulnerability treatment. |

## Validation Evidence

Platform validation for merged PR `sgajbi/lotus-platform#327`:

1. `python platform-contracts\domain-data-products\validate_domain_data_product_contracts.py`;
2. `python automation\generate_domain_product_discovery.py --check --generated-at-utc 2026-05-12T00:00:00Z`;
3. `git diff --check`;
4. GitHub checks: Cross-App Vocabulary Gate, Cross-Repo Mesh Certification Gate, Feature Lane /
   Platform Repo Contracts, PR Merge Gate / Platform Repo Contracts, and workflow lint all passed.

lotus-performance local validation:

1. `make domain-product-validate`;
2. `python -m pytest tests\unit\test_domain_data_product_contracts.py tests\unit\test_trust_telemetry.py -q`.

## Slice 6 Conclusion

Slice 6 is complete for the currently implemented composite surface. Composite performance is now a
real, implementation-backed Lotus data product for persisted-fact composite TWR, while the RFC still
truthfully blocks broader supported-feature claims until batch/recalculation, inspector, exports,
downstream realization, live proof, and final hardening slices are complete.
