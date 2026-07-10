# RFC-0086 Repo-Native Domain Product Onboarding

This document records the `lotus-performance` implementation posture for RFC-0086 and the
preparatory assessment for RFC-0087.

## Repo-Native Ownership Split

`lotus-performance` now owns its declaration content in:

1. `contracts/domain-data-products/lotus-performance-products.v1.json`
2. `contracts/domain-data-products/lotus-performance-consumers.v1.json`

`lotus-platform` remains the owner of:

1. schemas,
2. semantics and trust vocabulary registries,
3. shared declaration validation logic,
4. future aggregation and certification automation.

The local validation wrapper deliberately reuses the platform validator and platform vocabulary
instead of copying those registries into `lotus-performance`.

## Current Producer Coverage

Current repo-native producer declarations cover:

1. `TimeWeightedReturnAnalytics`
2. `MoneyWeightedReturnAnalytics`
3. `ContributionAnalytics`
4. `AttributionAnalytics`
5. `MandatePerformanceHealthContext`
6. `ReturnsSeriesBundle`
7. `BenchmarkExposureContext`
8. `CompositePerformanceAnalytics`

Each declared performance-owned governed product must retain:

1. stable route surfaces,
2. explicit upstream source dependencies,
3. lineage expectations,
4. partial or fail-closed posture that can be certified truthfully.

## Current Consumer Coverage

Current repo-native consumer declarations cover the `lotus-core` dependencies already aligned under
RFC-0084/RFC-0082:

1. `PortfolioTimeseriesInput`
2. `PositionTimeseriesInput`
3. `PerformanceComponentEconomics`
4. `PortfolioAnalyticsReference`
5. `BenchmarkAssignment`
6. `MarketDataWindow`
7. `InstrumentReferenceBundle`
8. `RiskFreeSeriesWindow`
9. `BenchmarkConstituentWindow`
10. `IndexSeriesWindow`

## Local Validation Path

Repo-native validation command:

```powershell
python scripts/validate_domain_data_product_contracts.py
```

Repo-native make target:

```powershell
make domain-product-validate
```

The wrapper validates:

1. local repo-native declarations from `contracts/domain-data-products/`,
2. the route-level upstream dependency inventory in
   `contracts/domain-data-products/lotus-performance-upstream-dependency-inventory.v1.json`,
3. platform-owned vocabulary from `../lotus-platform/platform-contracts/domain-vocabulary/`,
4. required upstream producer declarations from `../lotus-platform/platform-contracts/domain-data-products/`
   until federated aggregation replaces the transitional platform copies.

That keeps local ownership real without forking the shared trust vocabulary or validator semantics.

## Route-Level Exception Coverage

The current RFC-0082 upstream contract-family map still contains active routes where the upstream
producer declaration is not yet available or where the route is explicitly operational-read only.
Those are no longer docs-only gaps: they are recorded in
`lotus-performance-upstream-dependency-inventory.v1.json` with owner, expiry, route/contract
posture, freshness/trust metadata, failure posture, validation lane, allowed downstream
interpretation, promotion condition, and evidence tests.

Current time-bound exceptions:

1. benchmark definition sourcing,
2. benchmark vendor return-series sourcing,
3. FX operational-read sourcing.

These dependencies should not be promoted with invented product semantics. They need upstream
producer onboarding or an explicit owner-approved renewal before the exception expiry.

## RFC-0087 First-Wave Telemetry Candidates

Strongest first-wave runtime trust telemetry targets for `lotus-performance`:

1. `ReturnsSeriesBundle`
   Rationale: already has as-of-date semantics, fail-closed versus partial behavior for risk-free
   enrichment, async execution tracking, durable lineage, and inspection-ready source-quality
   evidence.
2. `BenchmarkExposureContext`
   Rationale: already depends on governed benchmark assignment, market-window, and instrument
   reference inputs, and it can surface freshness, completeness, and lineage posture without
   inventing gateway-local trust logic.

Second-wave watchlist, but not first-wave declaration targets yet:

1. `GET /integration/runtime-status`
   Strong operator-facing trust signal, but it is a runtime control-plane surface rather than a
   governed domain product declaration today.
2. TWR inspection supportability outputs
   Rich trust evidence exists, but the surface is currently a supportability contract family rather
   than one of the RFC-0084 governed domain products.
