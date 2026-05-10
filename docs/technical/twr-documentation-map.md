# TWR Documentation Map

This map is the current documentation structure for Lotus time-weighted return. It exists to keep
RFC-046 work from spreading TWR truth across disconnected files or duplicating long-lived product
material in both `docs/` and `wiki/`.

## Audience Routing

| Audience | Start here | Purpose |
| --- | --- | --- |
| Developers | [guides/twr.md](../guides/twr.md) | Request and response shape, execution mode, benchmark inclusion, and supportability fields. |
| Methodology reviewers | [methodologies/metrics/master-index.md](../methodologies/metrics/master-index.md) | Metric-level formulas, variable dictionaries, validation behavior, and worked examples. |
| Operations and support | [performance-reset-scenarios.md](performance-reset-scenarios.md), [twr-inspection-endpoint-certification.md](twr-inspection-endpoint-certification.md) | Reset behavior, no-investment-period diagnostics, source-quality inspection, and supportability workflows. |
| API reviewers | [twr-endpoint-certification.md](twr-endpoint-certification.md) | Certified endpoint behavior, downstream consumers, figure tie-outs, and test pyramid posture. |
| Business, sales, pre-sales, and demos | [wiki/Time-Weighted-Return.md](../../wiki/Time-Weighted-Return.md) | Product-level explanation, implemented capability boundary, integration posture, and current limitations. |
| RFC implementers | [RFC 046 - TWR Industry Methodology Alignment and Evidence Contract.md](../RFCs/RFC%20046%20-%20TWR%20Industry%20Methodology%20Alignment%20and%20Evidence%20Contract.md) | Execution plan, slice gates, evidence expectations, and RFC-specific implementation decisions. |

## Source Of Truth Layers

| Layer | Owns | Should not own |
| --- | --- | --- |
| `docs/guides/twr.md` | Current public API usage, request modes, response shape, async path, and high-level methodology. | Detailed product narrative, sales/demo material, or future target-state claims. |
| `docs/methodologies/metrics/metric-twr-*.md` | Metric-level variable dictionary, formulas, deterministic computation steps, validation/failure behavior, and worked examples. | API routing, operational runbooks, or RFC status. |
| `docs/technical/performance-reset-scenarios.md` | Reset and no-investment-period business scenarios that explain linkability and economic continuity. | Full API contract examples or final RFC-046 evidence contract claims before implementation. |
| `docs/technical/twr-endpoint-certification.md` | Endpoint certification, downstream consumers, test pyramid assessment, and known supportability issues. | Generic methodology or unproven roadmap statements. |
| `docs/technical/twr-inspection-endpoint-certification.md` | Supportability and inspection endpoint certification, artifact boundaries, and operator evidence workflow. | Normal calculation-response contract detail. |
| `wiki/Time-Weighted-Return.md` | Durable product-facing TWR overview for business users, operations, developers, sales/pre-sales, and demos. | Field-level API reference or detailed formula derivation. |
| `docs/RFCs/RFC-046-*.md` | RFC-046 implementation control evidence, slice decisions, validation, and branch reconciliation. | Durable product documentation after RFC closure. |

## Current Structure Decisions

1. Do not move detailed field-level API content into the wiki. OpenAPI and `docs/guides/twr.md`
   remain the developer contract references.
2. Do not duplicate metric formulas in the wiki. The metric methodology set remains the formula
   authority.
3. Keep RFC-046 slice evidence under `docs/RFCs/` because it is execution control material, not
   durable product documentation.
4. Use the wiki as a curated audience entrypoint that links to implementation-backed docs and
   states limitations plainly.
5. Composite, group, and sleeve TWR are not promoted by this documentation structure. RFC-046
   remains portfolio TWR focused unless later approved implementation work proves otherwise.

## Slice 2 Cleanup Review

Slice 2 did not remove TWR engine code. A targeted structure review found no safe dead TWR code to
delete before the evidence-contract slices. Removing calculation paths before Slice 4 and Slice 5
would increase risk because those slices first need characterization tests for denominator,
linkability, reset, and source-quality behavior.

The cleanup performed in Slice 2 is documentation-structure cleanup:

1. create this single TWR documentation map,
2. add a wiki page for durable TWR product navigation,
3. link the map from the methodology index,
4. add a docs contract test that prevents the map and wiki page from drifting out of navigation.

Later RFC-046 slices may still remove or consolidate code if tests prove a path is dead,
duplicated, or misleading.
