# Lotus Performance Trust Telemetry

This directory contains repo-owned RFC-0087 trust telemetry snapshots for governed
`lotus-performance` domain products.

The current first-wave snapshot is:

1. `returns-series-bundle.telemetry.v1.json`
   Runtime trust proof for `lotus-performance:ReturnsSeriesBundle:v1`.

Validate locally with:

```powershell
python -m pytest tests\unit\test_trust_telemetry.py -q
```

When `../lotus-platform` is available, the test validates the snapshot with the platform
`automation/validate_trust_telemetry.py` contract validator and checks that observed trust metadata
matches the repo-native declaration in
`contracts/domain-data-products/lotus-performance-products.v1.json`.
