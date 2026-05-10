# Supported Features

This page lists implementation-backed `lotus-performance` capabilities. It is product material for
business users, engineers, operations, sales, pre-sales, and demo preparation. It is not a roadmap
claim list.

## Feature Matrix

| Capability | Supported scope | Primary route or surface | Evidence and boundary |
| --- | --- | --- | --- |
| Portfolio TWR | Portfolio-level stateless and stateful TWR, synchronous and async | `POST /performance/twr`, `GET /performance/twr/results/{calculation_id}` | Daily calculation evidence, linkability status, episode status, supportability metadata, reset diagnostics, lineage, and docs contract tests. Composite, group, and sleeve TWR are not supported. |
| Benchmark-aware TWR | Portfolio TWR with benchmark return and active return | `POST /performance/twr` with `include_benchmark=true` | `benchmark_context.supportability_evidence` exposes benchmark source/method, currency state, FX decomposition posture, calendar alignment, missing-date counts, and bounded warning codes. |
| TWR inspection | Source-quality, economic-plausibility, reconciliation, cash-flow classification, reset/linkability supportability | `POST /performance/inspections/twr` | Inspection findings and artifacts support operational diagnosis; resolved async TWR subjects can use durable compute-job request payloads when API-local lineage files are not yet visible. Inspection is the deeper support surface and does not replace the calculation response contract. |
| Money-weighted return | Portfolio-level XIRR, Modified Dietz fallback, Simple Dietz explicit path | `POST /performance/mwr` | Status, reason codes, warnings, convergence, fallback metadata, reporting currency, currency evidence, calculation supportability, and production-control docs. |
| Contribution | Portfolio, position, and hierarchy contribution, including stateful source-normalized input | `POST /performance/contribution` | Total, local, and FX contribution results with bounded supportability, Carino smoothing evidence, source-economics evidence, trust telemetry, and governed `ContributionAnalytics:v1` data-product declaration. RFC-047 proves external-deposit neutrality, income assignment, fee drag, missing classification, short-sleeve sign behavior, downstream Gateway preservation, and Workbench evidence display. Downstream consumers should not reconstruct contribution. |
| Attribution | Portfolio/benchmark attribution, including stateful source-normalized input | `POST /performance/attribution` | Allocation, selection, interaction, active return, currency-attribution evidence, supportability metadata, lineage artifacts, and Gateway/Workbench consumption. RFC 048 is improving status, residual materiality, alignment, daily evidence, and data-product posture; fixed-income factor, derivative, sleeve, and composite attribution are not current supported claims. |
| Returns series | Performance-owned return-series bundle for downstream analytics engines | `POST /integration/returns/series` | Correct downstream surface for risk engines; `lotus-risk` should consume this rather than direct TWR response internals. |
| Benchmark exposure context | Benchmark exposure rows for risk and integration workflows | `POST /integration/benchmarks/exposure-context` | Benchmark-context integration product; not a composite TWR calculation surface. |
| Workspace summary | Interaction-efficient performance summary for product surfaces | `POST /performance/workspace-summary` | Product-oriented summary contract for Gateway and Workbench. It should consume performance-owned calculations, not rebuild them. |
| Execution and lineage | Async polling, result retrieval, lineage metadata, artifacts | `/performance/executions/*`, `/performance/lineage/*` | Durable evidence path for reproducibility, operations, and support. |
| Runtime operations | Health, readiness, metrics, runtime status, recovery, retention | `/health`, `/metrics`, `/integration/runtime-status`, recovery and retention routes | Supports enterprise operational posture and CI/runtime diagnostics. |

## TWR RFC-046 Supported Detail

RFC-046 promotes the following TWR capabilities as supported because they are implemented,
documented, and tested:

- daily calculation evidence with denominator basis, flow timing, signed adjusted capital,
  adjusted capital after policy, performance P&L, daily return, status, reason codes, and warnings
- linkability status and episode status for reset boundaries, no-investment periods, and full-loss
  or not-calculated rows
- stateful source-quality evidence from `lotus-core` normalized inputs
- canonical inspection evidence for resolved stateful subjects, including source-quality,
  economic-plausibility, reconciliation, and cash-flow-classification check families
- benchmark/FX/calendar supportability evidence under `benchmark_context.supportability_evidence`
- Gateway workspace preservation of benchmark evidence
- Workbench presentation of benchmark evidence as an implementation-backed product metric
- explicit portfolio-only boundary for TWR

Gold-pass live validation on 2026-05-10 proved canonical stateful TWR inspection against the local
front-office stack. The inspector completed all required evidence families with zero reconciliation
gap dates, zero nonpositive capital-base dates, zero cash-flow normalization/timing/type defects,
and only the allowed canonical data warnings.

## Not Supported By RFC-046

The following are not supported product claims for RFC-046:

- composite TWR calculation
- group TWR calculation
- sleeve TWR calculation
- downstream reconstruction of TWR from raw source rows
- use of TWR response internals as the canonical risk return-series input
- unbounded Prometheus labels containing portfolio, client, account, trace, request, response, or
  security identifiers

## Data Product Posture

`TimeWeightedReturnAnalytics:v1` is a governed `lotus-performance` data product. It is declared in
`contracts/domain-data-products/lotus-performance-products.v1.json`, uses daily freshness semantics,
requires lineage, carries customer-consumable evidence posture, and is approved for Gateway
consumption. Gateway and Workbench can publish the evidence, but they do not redefine the
performance methodology.

`ContributionAnalytics:v1` is also a governed `lotus-performance` data product. It is declared in
`contracts/domain-data-products/lotus-performance-products.v1.json`, has repo-local trust telemetry
at `contracts/trust-telemetry/contribution-analytics.telemetry.v1.json`, uses daily freshness
semantics, requires lineage, and is approved for Gateway consumption. Stateful contribution depends
on `lotus-core` `PortfolioTimeseriesInput:v1` and `PositionTimeseriesInput:v1`; unsupported
component-P&L families are exposed as unsupported or degraded evidence rather than inferred
downstream. The product is detailed in [Contribution Analytics](Contribution-Analytics).

## References

- [Time-Weighted Return](Time-Weighted-Return)
- [Contribution Analytics](Contribution-Analytics)
- [Attribution Analytics](Attribution-Analytics)
- [Mesh Data Products](Mesh-Data-Products)
- [docs/guides/twr.md](../docs/guides/twr.md)
- [docs/technical/twr-documentation-map.md](../docs/technical/twr-documentation-map.md)
- [docs/technical/twr-endpoint-certification.md](../docs/technical/twr-endpoint-certification.md)
- [docs/guides/twr_inspection_checks.md](../docs/guides/twr_inspection_checks.md)
- [docs/guides/attribution.md](../docs/guides/attribution.md)
- [docs/technical/attribution-documentation-map.md](../docs/technical/attribution-documentation-map.md)
