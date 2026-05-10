# RFC 048 Slice 6 - Data Product and Platform Hardening

Date: 2026-05-11

Branch: `feat/rfc-048-attribution-industry-alignment`

Related platform branch: `feat/rfc-048-attribution-domain-product-catalog`

Related platform PR: `sgajbi/lotus-platform#324`

## Scope

Slice 6 promoted attribution from an implemented analytics endpoint to a governed Lotus data
product with explicit mesh metadata, trust telemetry, approved consumer posture, lineage posture,
and platform catalog discoverability.

The slice deliberately keeps the product boundary truthful. It does not claim composite
attribution, fixed-income factor attribution, derivative attribution, sleeve attribution, fee/tax
attribution, or benchmark/classification versioning until those source contracts exist and are
implemented.

## Implementation

The implementation added `AttributionAnalytics` to the repo-native domain data product declaration
in `contracts/domain-data-products/lotus-performance-products.v1.json`.

The declaration records:

1. authoritative domain: `performance_analytics`;
2. product family: `analytics_output`;
3. portfolio-level request scope;
4. daily freshness expectation tied to requested valuation/as-of dates;
5. approved downstream consumer: `lotus-gateway`;
6. current product routes:
   - `/performance/attribution`;
   - `/performance/attribution/results/{calculation_id}`;
7. required trust metadata for benchmark context, source services, upstream request fingerprints,
   data quality, coverage, reconciliation, request fingerprint, and correlation;
8. customer-consumable lineage posture for support and evidence review;
9. explicit identifier references for `portfolio_id`, `benchmark_id`, `calculation_id`, and
   `correlation_id`.

The slice also added
`contracts/trust-telemetry/attribution-analytics.telemetry.v1.json` as the current governed trust
snapshot for `lotus-performance:AttributionAnalytics:v1`.

## Platform Alignment

The new trust snapshot exposed a legitimate platform generated-catalog gap: the platform discovery
catalog did not yet include `lotus-performance:AttributionAnalytics:v1`.

That gap was fixed at platform level by refreshing the generated domain-product catalog and
dependency graph in `lotus-platform` on `feat/rfc-048-attribution-domain-product-catalog`. The
refresh adds the attribution product to platform discovery and records `lotus-gateway` as the
approved consumer.

This keeps the data-product truth in the proper layered model:

1. `lotus-performance` owns the repo-native source declaration and trust telemetry.
2. `lotus-platform` owns generated cross-repository discovery and mesh catalog evidence.
3. Validators prove the telemetry snapshot points at a declared product known to the platform
   catalog.

## Tests Added Or Strengthened

1. `tests/unit/test_domain_data_product_contracts.py`
   - proves the repo-native declaration includes `AttributionAnalytics`;
   - proves attribution approved consumers and current routes are explicit;
   - proves benchmark, coverage, and reconciliation trust metadata are required.
2. `tests/unit/test_trust_telemetry.py`
   - proves the attribution trust snapshot is tied to the repo-native declaration;
   - proves observed trust metadata matches the declaration;
   - proves benchmark context is present and uses calculated benchmark returns;
   - proves lineage is materialized and customer-consumable;
   - proves the product is not blocked in the current snapshot.

## Validation Evidence

```powershell
python scripts\validate_domain_data_product_contracts.py
# Domain data product declarations validated.

python C:\Users\Sandeep\projects\lotus-platform\automation\validate_trust_telemetry.py contracts\trust-telemetry --catalog C:\Users\Sandeep\projects\lotus-platform\generated\domain-product-catalog.json
# Validated 4 trust telemetry snapshot(s).

python -m pytest tests\unit\test_domain_data_product_contracts.py tests\unit\test_trust_telemetry.py -q
# 11 passed.

make check
# ruff, format check, monetary float guard, no-alias guard, mypy, OpenAPI quality gate,
# API vocabulary inventory, domain-product validation, and 1229 unit tests passed.
```

Platform catalog validation:

```powershell
python automation\generate_domain_product_discovery.py --check --generated-at-utc 2026-04-19T00:00:00Z
# Generated domain-product discovery artifacts are current.
```

## Review Decision

Slice 6 is complete for the approved RFC 048 scope once both the `lotus-performance` RFC branch and
the platform catalog refresh branch are merged. The data-product declaration is validator-backed,
trust telemetry is intentionally bounded, and platform discovery now has the required generated
truth to recognize attribution as a governed Lotus data product.
