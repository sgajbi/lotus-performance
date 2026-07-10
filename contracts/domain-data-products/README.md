## Repo-Native Domain Data Product Declarations

This directory is the repo-native declaration path for `lotus-performance` under RFC-0086.

`lotus-performance` owns the declaration content in this directory.

`lotus-platform` remains the owner of:

1. schemas,
2. identifier and temporal-semantics vocabulary,
3. trust metadata vocabulary,
4. shared validation logic,
5. future aggregation and certification automation.

Current declaration files:

1. `lotus-performance-products.v1.json`
   Producer declaration for performance-owned governed products.
2. `lotus-performance-consumers.v1.json`
   Consumer declaration for governed upstream dependencies consumed from `lotus-core`.
3. `lotus-performance-upstream-dependency-inventory.v1.json`
   Route-level inventory for every active `CoreIntegrationService.get_*` dependency, including
   time-bound exceptions where upstream producer declarations are not available yet.

Local validation command:

```powershell
python scripts/validate_domain_data_product_contracts.py
```

Repo-native make target:

```powershell
make domain-product-validate
```

Validation posture:

1. local declarations and upstream dependency inventory are validated in-repo,
2. platform-owned vocabulary is loaded from sibling repo `../lotus-platform`,
3. upstream cross-reference validation stages the required upstream producer declarations from `lotus-platform`
   until federation aggregation moves fully off the transitional platform-owned files.

Current coverage boundary:

1. this directory covers the currently governed `TimeWeightedReturnAnalytics`,
   `MoneyWeightedReturnAnalytics`, `ContributionAnalytics`, `AttributionAnalytics`,
   `ReturnsSeriesBundle`,
   `MandatePerformanceHealthContext`, `BenchmarkExposureContext`, and `CompositePerformanceAnalytics`
   products
   plus the first-wave `lotus-core` dependency declarations already aligned under RFC-0084,
2. benchmark composition-window and index price-series dependencies are now machine-readable
   `BenchmarkConstituentWindow:v1` and `IndexSeriesWindow:v1` consumer declarations because active
   upstream producer declarations exist in `lotus-platform`.
3. route-level upstream dependency coverage is governed by
   `lotus-performance-upstream-dependency-inventory.v1.json` and interpreted with
   `docs/technical/RFC-0082-upstream-contract-family-map.md`. Benchmark definition, benchmark
   vendor return-series, and FX operational-read dependencies currently carry time-bound exception
   records until corresponding upstream producer declarations are onboarded or an explicit
   owner-approved operational-read posture is renewed.
