# RFC 048 Slice 9 - Documentation Productization

Date: 2026-05-11

Branch: `feat/rfc-048-attribution-industry-alignment`

## Scope

Slice 9 converted RFC 048 attribution outcomes into durable Lotus documentation and wiki material
without copying generic source-pack language. The slice updated existing documentation surfaces
rather than creating duplicate pages.

## Documentation Updated

| Surface | Update |
| --- | --- |
| `README.md` | Added attribution to the governed data-product list and navigation to attribution certification/wiki material. |
| `docs/technical/attribution-endpoint-certification.md` | Added current downstream PR evidence, invalid linked-return-chain certification, reason-code posture, and validation commands. |
| `docs/guides/attribution.md` | Already updated in Slice 8 with invalid linked-return-chain behavior. |
| `docs/methodologies/metrics/metric-attribution-*.md` | Updated active return, allocation, selection, and interaction methodology docs to include the governed invalid-chain behavior. |
| `wiki/Attribution-Analytics.md` | Added data-product contract, support-triage flow, reason-code table, and QA/evidence summary. |
| `wiki/Mesh-Data-Products.md` | Added `AttributionAnalytics:v1` product posture and trust-telemetry boundary. |
| `wiki/Supported-Features.md` | Promoted only implementation-backed attribution claims and kept fixed-income factor, derivative, sleeve, composite, fee/tax/income, benchmark-version, classification-version, and calendar-policy attribution out of supported scope. |
| `wiki/API-Surface.md` | Added period supportability and invalid linked-return-chain behavior to the attribution API surface summary. |

## Review Decision

The documentation is implementation-backed and audience-aware:

1. developers get current request/response and methodology behavior;
2. operations get supportability, reason-code, residual, and lineage triage guidance;
3. business users and sales/pre-sales get a clear supported-feature boundary;
4. data-product reviewers get producer declaration, trust telemetry, approved consumer, lineage,
   and unsupported-boundary posture;
5. downstream teams get a clear instruction not to reconstruct attribution in Gateway or Workbench.

## Validation Evidence

Run after edits:

```powershell
python -m pytest tests\unit\docs\test_public_docs_contract.py -q
# 42 passed.

python -m pytest tests\unit\docs\test_public_docs_contract.py tests\unit\docs\test_metric_methodology_docs.py -q
# 50 passed.

make check
# Passed: ruff, format check, monetary-float guard, no-alias guard, mypy, OpenAPI quality,
# API vocabulary inventory, domain data-product validation, and 1,232 unit tests.

powershell -ExecutionPolicy Bypass -File C:\Users\Sandeep\projects\lotus-platform\automation\Sync-RepoWikis.ps1 -CheckOnly -Repository lotus-performance
# Expected pre-merge drift: repo-local branch wiki source differs from the already-published GitHub wiki for
# _Sidebar.md, API-Surface.md, Attribution-Analytics.md, Home.md, Mesh-Data-Products.md, and
# Supported-Features.md. Publication is intentionally deferred until RFC 048 is merged to main.
```

Full branch validation is required before Slice 9 closure. Published wiki synchronization remains a
final-closure action after RFC 048 is merged to `main`.
