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

Local validation command:

```powershell
python scripts/validate_domain_data_product_contracts.py
```

Repo-native make target:

```powershell
make domain-product-validate
```

Validation posture:

1. local declarations are validated in-repo,
2. platform-owned vocabulary is loaded from sibling repo `../lotus-platform`,
3. upstream cross-reference validation stages the required upstream producer declarations from `lotus-platform`
   until federation aggregation moves fully off the transitional platform-owned files.

Current coverage boundary:

1. this directory covers the currently governed `TimeWeightedReturnAnalytics`,
   `MoneyWeightedReturnAnalytics`, `ContributionAnalytics`, `ReturnsSeriesBundle`, and
   `BenchmarkExposureContext` products
   plus the first-wave `lotus-core` dependency declarations already aligned under RFC-0084,
2. benchmark-definition, benchmark-composition, vendor-return, index-catalog, index-price-series, and
   FX operational-read dependencies remain documented in `docs/technical/RFC-0082-upstream-contract-family-map.md`
   but are not yet machine-readable here because the corresponding upstream producer declarations have not
   been onboarded yet.
