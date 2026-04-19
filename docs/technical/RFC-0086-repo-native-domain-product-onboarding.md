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

1. `ReturnsSeriesBundle`
2. `BenchmarkExposureContext`

These are the strongest current performance-owned governed products because they already have:

1. stable route surfaces,
2. explicit upstream source dependencies,
3. lineage expectations,
4. partial or fail-closed posture that can be certified truthfully.

## Current Consumer Coverage

Current repo-native consumer declarations cover the first-wave `lotus-core` dependencies already
aligned under RFC-0084:

1. `PortfolioTimeseriesInput`
2. `PortfolioAnalyticsReference`
3. `BenchmarkAssignment`
4. `MarketDataWindow`
5. `InstrumentReferenceBundle`
6. `RiskFreeSeriesWindow`

## Local Validation Path

Repo-native validation command:

```powershell
python scripts/validate_domain_data_product_contracts.py
```

Repo-native make target:

```powershell
make domain-product-validate
```

The wrapper stages:

1. local repo-native declarations from `contracts/domain-data-products/`,
2. platform-owned vocabulary from `../lotus-platform/platform-contracts/domain-vocabulary/`,
3. required upstream producer declarations from `../lotus-platform/platform-contracts/domain-data-products/`
   until federated aggregation replaces the transitional platform copies.

That keeps local ownership real without forking the shared trust vocabulary or validator semantics.

## Docs-Only Dependency Coverage Still Missing

The current RFC-0082 upstream contract-family map still contains documented dependencies that are
not yet covered by machine-readable declarations because corresponding upstream producer
declarations are not yet available:

1. benchmark definition sourcing,
2. benchmark composition-window sourcing,
3. benchmark vendor return-series sourcing,
4. index catalog sourcing,
5. index price-series sourcing,
6. FX operational-read sourcing.

These dependencies should not be declared locally with invented product semantics. They need
upstream producer onboarding or an explicit platform decision on whether each route belongs in the
governed product family.

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
