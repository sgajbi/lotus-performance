# RFC-046 Slice 10 Documentation and Wiki Productization

| Field | Value |
| --- | --- |
| RFC | RFC-046 - TWR Industry Methodology Alignment, Evidence Contract, and Data Product Hardening |
| Slice | 10 - Lotus TWR Documentation and Wiki Productization |
| `lotus-performance` branch | `feat/rfc-046-twr-industry-evidence` |

## Implementation

Slice 10 converts the RFC-046 TWR evidence work into Lotus-owned, implementation-backed product
documentation. The output is deliberately split by audience:

- `docs/guides/twr.md` remains the developer-facing API and methodology guide.
- `docs/technical/twr-documentation-map.md` remains the durable source-of-truth map.
- `wiki/Time-Weighted-Return.md` becomes the product-facing TWR overview for business, operations,
  engineering, sales/pre-sales, and demo preparation.
- `wiki/Supported-Features.md` becomes the implementation-backed feature ledger and non-supported
  boundary page.
- `wiki/Mesh-Data-Products.md` now records `TimeWeightedReturnAnalytics:v1` as a governed
  performance data product, not only MWR and returns-series products.

Changes made:

- expanded the TWR wiki page with:
  - daily calculation evidence
  - linkability and episode status
  - stateful source-quality evidence
  - benchmark source/currency/FX/calendar supportability evidence
  - product-contract questions and implementation-backed answers
  - business flow and evidence-flow diagrams
  - Gateway/Workbench realization notes
  - demo-safe talking points
  - explicit portfolio-only limitations
- added a supported-features wiki page that separates implemented capability from unsupported
  RFC-046 claims
- linked the supported-features page from wiki `Home`, `_Sidebar`, and `Overview`
- updated `API-Surface`, `Integrations`, and `Mesh-Data-Products` so TWR evidence, downstream
  preservation, and data-product ownership are visible outside the TWR page
- updated the TWR documentation map so future agents know where supported-feature truth belongs
- added public docs contract assertions so the wiki page, supported-feature ledger, integration
  evidence, and data-product identity cannot silently disappear

## Documentation Boundary

The wiki is not duplicating formula derivation or field-level API reference. Detailed request and
response shape remains in `docs/guides/twr.md` and OpenAPI. The wiki summarizes implemented product
truth, audience-specific meaning, integration boundaries, evidence posture, and demo-safe claims.

No generic industry text was copied into Lotus documentation. The wording uses current Lotus
vocabulary: `lotus-performance`, `lotus-core`, `lotus-gateway`, Workbench,
`TimeWeightedReturnAnalytics:v1`, `calculation_evidence`, `source_quality_evidence`,
`benchmark_context.supportability_evidence`, linkability status, episode status, supportability,
lineage, and data-product ownership.

## Supported Feature Outcome

RFC-046 supported-feature truth is now explicit:

- supported: portfolio-level stateless and stateful TWR
- supported: synchronous and async TWR result retrieval
- supported: daily calculation evidence
- supported: linkability and episode status
- supported: stateful source-quality evidence
- supported: benchmark-aware TWR and benchmark supportability evidence
- supported: Gateway and Workbench preservation/presentation of benchmark evidence
- not supported by RFC-046: composite, group, or sleeve TWR calculation

## Validation

Slice 10 validation commands:

- `python -m pytest tests/unit/docs/test_public_docs_contract.py -q`
  - Result: `41 passed`

Additional gates:

- `make lint`
- Result: passed, including monetary-float guard with `135` findings and `135` allowlisted findings
- `make typecheck`
- Result: `Success: no issues found in 159 source files`
- `python scripts/openapi_quality_gate.py`
- Result: passed
- `python scripts/api_vocabulary_inventory.py --validate-only`
- Result: passed with no vocabulary drift
- `python scripts/no_alias_contract_guard.py`
- Result: passed
- `git diff --check`
- Result: passed, with line-ending warnings only
- `powershell -ExecutionPolicy Bypass -File ..\lotus-platform\automation\Sync-RepoWikis.ps1 -CheckOnly -Repository lotus-performance`
- Result: expected drift detected because the repo-authored wiki source changed in this unmerged
  branch. Drift set: `_Sidebar.md`, `API-Surface.md`, `Home.md`, `Integrations.md`,
  `Mesh-Data-Products.md`, `Overview.md`, `Supported-Features.md`, and
  `Time-Weighted-Return.md`.

The wiki publication action is intentionally deferred until the RFC branch is merged to `main`, so
published wiki truth does not get ahead of merged repository truth.
