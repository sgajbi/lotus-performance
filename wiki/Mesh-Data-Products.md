# Mesh Data Products

## Mesh role

`lotus-performance` is a maturity-wave producer in the Lotus enterprise data mesh.

## Governed product

- Product ID: `lotus-performance:ReturnsSeriesBundle:v1`
- Product role: governed return-series and performance evidence consumed by risk, advisory, reporting, gateway, and Workbench discovery flows
- Source declaration: `contracts/domain-data-products/`
- Trust telemetry: `contracts/trust-telemetry/`
- MWR product evidence: `POST /performance/mwr` emits source-owned calculation quality through
  `status`, `reason_codes`, `warnings`, `fallback_reason`, `holding_period_return`,
  `convergence`, `calculation_supportability`, lineage, metadata, diagnostics, and audit fields.
  Downstream products may display or summarize those fields, but must not reinterpret ambiguous
  XIRR roots or rebuild investor cash-flow schedules outside the producer.
  Production controls and review findings are maintained in
  [docs/guides/mwr-lotus-production-controls.md](../docs/guides/mwr-lotus-production-controls.md)
  and
  [docs/technical/mwr-industry-review-findings.md](../docs/technical/mwr-industry-review-findings.md).

## Platform relationship

`lotus-platform` aggregates the repo-native declaration, validates trust telemetry, applies mesh SLO/access/evidence policies, and includes this product in generated catalog, dependency graph, live certification, maturity matrix, evidence packs, and RFC-0092 operating reports.

## Operating rule

Performance product identity, lifecycle, telemetry, reconciliation, and evidence posture belong in `lotus-performance`. Gateway and Workbench publish or display certified evidence; they do not redefine performance product truth.
