# Mesh Data Products

## Mesh role

`lotus-performance` is a maturity-wave producer in the Lotus enterprise data mesh.

## Governed products

- Product ID: `lotus-performance:TimeWeightedReturnAnalytics:v1`
- Product role: governed portfolio time-weighted return product consumed by gateway and Workbench
  experiences
- Product ID: `lotus-performance:MoneyWeightedReturnAnalytics:v1`
- Product role: governed investor capital-timing return product consumed by gateway and Workbench
  experiences
- Product ID: `lotus-performance:ContributionAnalytics:v1`
- Product role: governed performance explanation product that identifies which positions and
  hierarchy dimensions contributed to portfolio return
- Product ID: `lotus-performance:AttributionAnalytics:v1`
- Product role: governed benchmark-relative performance explanation product that decomposes active
  return into allocation, selection, interaction, residual, supportability, and lineage evidence
- Product ID: `lotus-performance:CompositePerformanceAnalytics:v1`
- Product role: governed persisted-fact composite performance product for private-banking
  composite TWR, source-fact lineage, restatement evidence, and supportable publication workflows
- Product ID: `lotus-performance:MandatePerformanceHealthContext:v1`
- Product role: governed active-return health context for DPM supportability consumers that need
  source-owned performance threshold posture without downstream methodology reconstruction
- Product ID: `lotus-performance:ReturnsSeriesBundle:v1`
- Product role: governed return-series and performance evidence consumed by risk, advisory, reporting, gateway, and Workbench discovery flows
- Product ID: `lotus-performance:BenchmarkExposureContext:v1`
- Product role: governed benchmark exposure context that preserves benchmark composition and
  resolved exposure posture for risk and idea consumers
- Source declaration: `contracts/domain-data-products/`
- Trust telemetry: `contracts/trust-telemetry/`
- TWR product evidence: `POST /performance/twr` emits portfolio TWR, benchmark-aware TWR,
  relative performance, daily calculation evidence, linkability status, episode status,
  `calculation_supportability`, stateful `source_quality_evidence`,
  `benchmark_context.supportability_evidence`, lineage, metadata, diagnostics, and audit fields.
  The product is portfolio-level only; composite, group, and sleeve TWR are not supported by
  RFC-046. Gateway and Workbench can publish the emitted evidence, but must not recompute TWR or
  redefine benchmark supportability downstream. Current feature truth is summarized in
  [Supported Features](Supported-Features) and detailed in
  [docs/guides/twr.md](../docs/guides/twr.md).
- MWR product evidence: `POST /performance/mwr` emits source-owned calculation quality through
  `status`, `reason_codes`, `warnings`, `fallback_reason`, `holding_period_return`,
  `convergence`, `reporting_currency`, `currency_evidence`, `calculation_supportability`,
  lineage, metadata, diagnostics, and audit fields. Downstream products may display or summarize
  those fields, but must not reinterpret ambiguous XIRR roots, rebuild investor cash-flow schedules
  outside the producer, or infer per-input FX provenance from pre-converted source amounts.
  It is now declared as `MoneyWeightedReturnAnalytics` in
  `contracts/domain-data-products/lotus-performance-products.v1.json`, backed by
  `contracts/trust-telemetry/money-weighted-return-analytics.telemetry.v1.json`, and approved for
  `lotus-gateway` consumption. Current MWR is a single reporting-currency product with explicit
  source-component evidence. Stateless callers may supply complete `source_preconverted_fx_evidence`;
  consumers should preserve the emitted
  `currency_evidence` and must not reconstruct FX conversion locally. Cash-flow dates are
  producer-validated against the resolved measurement window and rejected with
  `MWR_CASH_FLOW_OUT_OF_WINDOW` when outside the supported period. Stateful responses also carry
  bounded `source_cashflow_quality` counts and source transaction/event lifecycle identity when
  supplied by the upstream timeseries source, with absent lifecycle identity reported as explicit
  supportability posture. Stateful single-currency MWR emits `not_required_single_currency_inputs`
  when source and reporting currencies match. Stateful upstream cross-currency FX-aware MWR remains
  gated by
  [docs/technical/mwr-fx-contract-design.md](../docs/technical/mwr-fx-contract-design.md).
  Production controls and review findings are maintained in
  [docs/guides/mwr-lotus-production-controls.md](../docs/guides/mwr-lotus-production-controls.md)
  and
  [docs/technical/mwr-industry-review-findings.md](../docs/technical/mwr-industry-review-findings.md).
- Contribution product evidence: `POST /performance/contribution` emits source-owned
  contribution totals, position rows, optional hierarchy rows, optional daily and by-position
  series, `smoothing_evidence`, `source_economics_evidence`, `calculation_supportability`,
  metadata, diagnostics, audit fields, and async lineage. The governed product is declared as
  `ContributionAnalytics` in
  `contracts/domain-data-products/lotus-performance-products.v1.json`, backed by
  `contracts/trust-telemetry/contribution-analytics.telemetry.v1.json`, and approved for
  `lotus-gateway` consumption. Gateway and Workbench may display contribution product evidence,
  but must not reconstruct contribution totals, source-quality posture, or Carino smoothing state
  downstream. Source inputs are portfolio and position analytics inputs from `lotus-core`, with
  optional `PerformanceComponentEconomics:v1` evidence for Core-authored cashflow, fee, income,
  tax, realized P&L, and FX-context component-family supportability. Partial Core
  component-economics chunk coverage remains degraded; missing or broader component-P&L families
  remain explicit unsupported/degraded evidence rather than inferred facts.
  RFC-047 also proves source-document edge semantics for external deposits, internal trade flows,
  income assignment, fee drag, missing classifications, short-sleeve sign behavior, and
  downstream preservation through Gateway and Workbench. See
  [Contribution Analytics](Contribution-Analytics).
- Attribution product evidence: `POST /performance/attribution` emits source-owned allocation,
  selection, interaction, active-return, residual-materiality, period-status, reason-code,
  supportability, currency-attribution, `calculation_supportability`, metadata, diagnostics, audit,
  and lineage evidence. The governed product is declared as `AttributionAnalytics` in
  `contracts/domain-data-products/lotus-performance-products.v1.json`, backed by
  `contracts/trust-telemetry/attribution-analytics.telemetry.v1.json`, and approved for
  `lotus-gateway` consumption. Gateway and Workbench may display attribution product evidence, but
  must not reconstruct attribution totals, residual materiality, linked-return posture, or period
  status downstream. Source inputs are portfolio, position, benchmark, and FX/source-currency inputs
  from `lotus-core` where stateful mode is used. Fixed-income factor, derivative, sleeve,
  composite, fee/tax/income-breakout, benchmark-version, classification-version, and calendar-policy
  attribution remain explicit unsupported or source-limited boundaries. See
  [Attribution Analytics](Attribution-Analytics).
- Composite product evidence: `POST /performance/composites/twr` emits source-owned
  asset-weighted composite period return, cumulative return, member weights, member contributions,
  dispersion, source fingerprints, restatement versions, reason codes, and status from persisted
  member-return facts. `POST /performance/composites/inspect` emits supportability findings and
  classified artifacts for audit and operations. The governed product is declared as
  `CompositePerformanceAnalytics` in
  `contracts/domain-data-products/lotus-performance-products.v1.json`, backed by
  `contracts/trust-telemetry/composite-performance-analytics.telemetry.v1.json`, and approved for
  `lotus-gateway` consumption. Gateway and Workbench may display composite product evidence, but
  must not reconstruct composite returns, weights, lineage, or restatement posture downstream.
  Composite contribution, attribution, MWR, sleeves, carve-outs, and multi-currency composite
  aggregation beyond the current single reporting-currency guard remain unsupported. See
  [Composite Performance](Composite-Performance).
- Mandate performance health product evidence: `POST /performance/mandate-health-context` emits
  source-owned active-return threshold posture, methodology posture, request fingerprint, and
  reason codes for DPM supportability consumers such as `lotus-manage`. The governed product is
  declared as `MandatePerformanceHealthContext` in
  `contracts/domain-data-products/lotus-performance-products.v1.json`, backed by
  `contracts/trust-telemetry/mandate-performance-health-context.telemetry.v1.json`, and approved
  for Gateway and Manage consumption. Downstream consumers may preserve this evidence, but must not
  reconstruct active return, reinterpret TWR methodology, create mandate actions, create rebalance
  waves, contact clients, place orders, or imply OMS/execution behavior.
- Benchmark exposure product evidence preserves benchmark exposure context for downstream risk and
  idea workflows. The governed product is declared as `BenchmarkExposureContext` in
  `contracts/domain-data-products/lotus-performance-products.v1.json`, backed by
  `contracts/trust-telemetry/benchmark-exposure-context.telemetry.v1.json`, and approved for
  `lotus-risk` and `lotus-idea` consumption. Downstream consumers may use the emitted exposure
  context as source-owned evidence, but must not redefine benchmark composition or valuation-date
  alignment outside the performance product contract.

## Governed upstream dependencies

`lotus-performance` consumes active `lotus-core` data products through
`contracts/domain-data-products/lotus-performance-consumers.v1.json`.

Current benchmark and index consumer coverage includes:

| Upstream product | Producer | Performance use | Failure posture |
| --- | --- | --- | --- |
| `BenchmarkConstituentWindow:v1` | `lotus-core` | Benchmark constituent, effective-date, and weight windows for stateful calculated benchmark performance and benchmark-aware TWR workflows. | Fail closed |
| `IndexSeriesWindow:v1` | `lotus-core` | Canonical index price-series windows for calculated benchmark performance and component return derivation. | Fail closed |

Benchmark definition, benchmark vendor return-series, index catalog, and FX operational-read
dependencies remain governed by
[docs/technical/RFC-0082-upstream-contract-family-map.md](../docs/technical/RFC-0082-upstream-contract-family-map.md)
until matching upstream producer declarations are available for repo-native consumer coverage.

## Platform relationship

`lotus-platform` aggregates the repo-native declaration, validates trust telemetry, applies mesh SLO/access/evidence policies, and includes this product in generated catalog, dependency graph, live certification, maturity matrix, evidence packs, and RFC-0092 operating reports.

## Operating rule

Performance product identity, lifecycle, telemetry, reconciliation, and evidence posture belong in `lotus-performance`. Gateway and Workbench publish or display certified evidence; they do not redefine performance product truth.
