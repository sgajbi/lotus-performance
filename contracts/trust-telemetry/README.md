# Lotus Performance Trust Telemetry

This directory contains repo-owned RFC-0087 trust telemetry snapshots for governed
`lotus-performance` domain products.

The current snapshots are:

1. `time-weighted-return-analytics.telemetry.v1.json`
   Runtime trust proof for `lotus-performance:TimeWeightedReturnAnalytics:v1`.
2. `returns-series-bundle.telemetry.v1.json`
   Runtime trust proof for `lotus-performance:ReturnsSeriesBundle:v1`.
3. `contribution-analytics.telemetry.v1.json`
   Runtime trust proof for `lotus-performance:ContributionAnalytics:v1`.
4. `attribution-analytics.telemetry.v1.json`
   Runtime trust proof for `lotus-performance:AttributionAnalytics:v1`.
5. `money-weighted-return-analytics.telemetry.v1.json`
   Runtime trust proof for `lotus-performance:MoneyWeightedReturnAnalytics:v1`.
6. `mandate-performance-health-context.telemetry.v1.json`
   Runtime trust proof for `lotus-performance:MandatePerformanceHealthContext:v1`.
7. `benchmark-exposure-context.telemetry.v1.json`
   Runtime trust proof for `lotus-performance:BenchmarkExposureContext:v1`.
8. `composite-performance-analytics.telemetry.v1.json`
   Runtime trust proof for `lotus-performance:CompositePerformanceAnalytics:v1`.

Every active product in `contracts/domain-data-products/lotus-performance-products.v1.json` must
have one repo-owned telemetry snapshot or an explicit machine-readable exception policy. The unit
test suite derives expected coverage from the active producer declaration so newly promoted products
cannot be declared as governed without trust telemetry evidence.

Validate locally with:

```powershell
python -m pytest tests\unit\test_trust_telemetry.py -q
```

When `../lotus-platform` is available, the test validates the snapshot with the platform
`automation/validate_trust_telemetry.py` contract validator and checks that observed trust metadata
matches the repo-native declaration in
`contracts/domain-data-products/lotus-performance-products.v1.json`.
