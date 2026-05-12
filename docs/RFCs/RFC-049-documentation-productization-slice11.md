# RFC 049 Slice 11 - Documentation Productization and Wiki

Status: complete on branch, pending merge-time wiki publication.

## Purpose

Slice 11 converts the implemented RFC-049 composite performance capability into Lotus-owned,
implementation-backed product documentation. The material is written for audit, operations,
engineering, business users, sales, pre-sales, and demo preparation while keeping unsupported
advanced composite scopes explicit.

## Added Or Updated Documentation

| Artifact | Purpose |
| --- | --- |
| `docs/methodologies/metrics/metric-composite-twr.md` | Audit-grade methodology v3 document for persisted-fact asset-weighted composite TWR. |
| `docs/guides/composite_performance.md` | Human API and operations guide for composite TWR and composite inspection. |
| `docs/technical/composite-twr-endpoint-certification.md` | Endpoint certification, figure tie-outs, error behavior, inspector artifact contract, and test-pyramid posture. |
| `docs/technical/composite-performance-documentation-map.md` | Audience routing and documentation controls for composite performance. |
| `wiki/Composite-Performance.md` | Product and operator wiki page with source authority, business flow, non-functional posture, support interpretation, and boundaries. |
| `README.md` | Concise repo capability and navigation update. |
| `docs/guides/api_reference.md` | Human API reference entries for `POST /performance/composites/twr` and `POST /performance/composites/inspect`. |
| `docs/guides/complete_service_reference.md` | Consolidated service inventory update for composite routes. |
| `docs/methodologies/metrics/master-index.md` | Methodology index entry for composite TWR. |
| `docs/technical/methodology_index.md` | Public guide and technical reference routing for composite methodology. |
| `wiki/API-Surface.md` | Composite route group and documentation routing. |
| `wiki/Integrations.md` | Composite source-flow diagram and downstream-consumer rule. |
| `wiki/Mesh-Data-Products.md` | `CompositePerformanceAnalytics:v1` product evidence and mesh posture. |
| `wiki/Home.md`, `wiki/_Sidebar.md` | Navigation entries for the composite product page. |

## Implementation-Backed Claims

The documentation only promotes behavior that exists in code and tests:

- persisted member-return fact based composite TWR;
- asset-weighted period returns;
- geometric linking across calculable periods;
- no-member and no-ready-member fail-closed behavior;
- one-member dispersion behavior;
- return-view separation;
- single reporting-currency guard;
- source fingerprints, source snapshots, source calculation ids, and restatement versions;
- classified inspection artifacts;
- `CompositePerformanceAnalytics:v1` declaration and trust telemetry;
- Gateway and Workbench branch-level typed consumers.

## Explicit Boundaries

The following remain unsupported and are kept visible in methodology, guide, wiki, supported
features, and docs regression tests:

- composite contribution;
- composite attribution;
- composite MWR;
- sleeves and carve-outs;
- model portfolios and wrap programs;
- pooled fund and private-market composites;
- portability records;
- tax-aware, leveraged, and long/short special composite structures;
- multi-currency composite aggregation beyond the current single reporting-currency guard;
- composite benchmark active return.

## Validation

Passed:

```text
python -m pytest tests\unit\docs\test_metric_methodology_docs.py tests\unit\docs\test_public_docs_contract.py -q
53 passed
```

Passed:

```text
git diff --check
```

Wiki check:

```text
powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\Sandeep\projects\lotus-platform\automation\Sync-RepoWikis.ps1 -CheckOnly -Repository lotus-performance
```

Result: expected pre-publication drift because this slice adds and changes repo-local wiki source.
Drift includes `Composite-Performance.md`, `_Sidebar.md`, `API-Surface.md`, `Home.md`,
`Integrations.md`, and `Mesh-Data-Products.md`. This is not a content-quality failure; it is the
publication delta that must be published after merge by running:

```text
powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\Sandeep\projects\lotus-platform\automation\Sync-RepoWikis.ps1 -Publish -Repository lotus-performance
```

## Regression Controls

New and updated docs tests pin:

- v3 methodology section order and composite-specific formulas, reason codes, restatement evidence,
  and unsupported boundaries;
- composite guide, certification, documentation map, wiki, mesh data-product material, README,
  API reference, and RFC index navigation.

## Remaining RFC-049 Work

Slice 11 does not close RFC-049. Remaining slices still need:

- live front-office canonical proof;
- second-last hardening and Swagger/API certification review;
- final closure, branch hygiene, mainline merge, and wiki publication;
- post-completion LinkedIn draft based only on implemented outcomes.
