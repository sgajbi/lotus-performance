# RFC-047 Slice 6 - Data Product And Platform Hardening Evidence

Status: complete

## Scope Completed

Slice 6 promoted contribution from an endpoint-level capability to a governed Lotus data product:

1. added `ContributionAnalytics:v1` to
   `contracts/domain-data-products/lotus-performance-products.v1.json`;
2. added `PositionTimeseriesInput:v1` as a machine-readable `lotus-core` upstream dependency in
   `contracts/domain-data-products/lotus-performance-consumers.v1.json`;
3. added repo-local trust telemetry at
   `contracts/trust-telemetry/contribution-analytics.telemetry.v1.json`;
4. updated README, endpoint certification, and wiki source so contribution is discoverable as a
   data product with freshness, lineage, source-economics evidence, access, and consumer posture;
5. opened the same-slice platform branch `docs/rfc047-contribution-mesh-hardening` to refresh the
   generated domain-product catalog and add SLO, access, and evidence policies for
   `lotus-performance:ContributionAnalytics:v1`.

## Data Mesh Posture

`ContributionAnalytics:v1` is declared as a portfolio-level performance analytics output with:

- daily freshness semantics based on valuation-date source observations;
- required lineage and customer-consumable lineage summary posture;
- approved `lotus-gateway` consumption;
- trust metadata for product identity, generated/as-of dates, correlation and request
  fingerprints, source services, upstream request fingerprints, data-quality status, coverage
  status, and coverage ratio;
- source dependency coverage for `PortfolioTimeseriesInput:v1` and `PositionTimeseriesInput:v1`.

## Validation Evidence

Local validation:

```text
python scripts/validate_domain_data_product_contracts.py
Validated 1 repo-native producer declaration(s) and 1 repo-native consumer declaration(s)

python -m pytest tests/unit/test_domain_data_product_contracts.py tests/unit/test_trust_telemetry.py -q
10 passed

python -m ruff check tests/unit/test_trust_telemetry.py tests/unit/test_domain_data_product_contracts.py
All checks passed
```

Platform mesh policy validation on `lotus-platform` branch
`docs/rfc047-contribution-mesh-hardening`:

```text
python automation/validate_mesh_slo_policies.py
Mesh SLO policies validated

python automation/validate_mesh_access_policies.py
Mesh access policies validated

$env:PYTHONPATH='automation'; python -c "from generate_mesh_evidence_pack import validate_mesh_evidence_policies; ..."
Mesh evidence policies validated

python automation/mesh_certification_gate.py --mode advisory --generated-at-utc 2026-05-10T00:00:00Z --telemetry-path contracts/trust-telemetry --skip-publication-checks
Mesh certification certified_with_warnings in advisory mode; 0 error(s), 5 warning(s), 0 info issue(s).
```

The five advisory warnings are unrelated first-wave required-product telemetry gaps for sibling
repositories (`lotus-core`, `lotus-risk`, `lotus-advise`, `lotus-report`, and `lotus-manage`).
Contribution telemetry itself validates against the refreshed platform catalog.

## Review Notes

No API response shape change was introduced in Slice 6. Downstream code changes are reserved for
Slice 7, where Gateway and Workbench must consume the already-added contribution evidence fields
through governed APIs only.
