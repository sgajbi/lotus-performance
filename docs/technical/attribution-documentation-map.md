# Attribution Documentation Map

This map is the current documentation structure for Lotus performance attribution. It exists to keep
RFC 048 work from spreading attribution truth across disconnected files or duplicating long-lived
product material in both `docs/` and `wiki/`.

## Audience Routing

| Audience | Start here | Purpose |
| --- | --- | --- |
| Developers | [guides/attribution.md](../guides/attribution.md) | Current request and response shape, stateless/stateful modes, async behavior, grouping, currency path, and examples. |
| Methodology reviewers | [methodologies/metrics/master-index.md](../methodologies/metrics/master-index.md) | Metric-level formulas for active return, allocation, selection, interaction, and currency attribution effects. |
| API reviewers | [attribution-endpoint-certification.md](attribution-endpoint-certification.md) | Certified endpoint behavior, downstream consumers, figure tie-outs, supportability posture, and validation commands. |
| Business, sales, pre-sales, operations, and demos | [wiki/Attribution-Analytics.md](../../wiki/Attribution-Analytics.md) | Product-level explanation, implemented capability boundary, integration posture, current limits, and demo-safe language. |
| Supported-feature reviewers | [wiki/Supported-Features.md](../../wiki/Supported-Features.md) | Implementation-backed feature ledger and boundaries for attribution claims. |
| RFC implementers | [RFC 048 - Attribution Industry Methodology Alignment and Evidence Contract.md](../RFCs/RFC%20048%20-%20Attribution%20Industry%20Methodology%20Alignment%20and%20Evidence%20Contract.md) | Execution plan, slice gates, evidence expectations, and RFC-specific implementation decisions. |

## Source Of Truth Layers

| Layer | Owns | Should not own |
| --- | --- | --- |
| `docs/guides/attribution.md` | Current public API usage, request modes, response shape, async path, and high-level methodology. | Sales/demo narrative, future target-state claims, or full formula derivations. |
| `docs/methodologies/metrics/metric-attribution-*.md` | Metric-level variable dictionary, formulas, deterministic computation steps, validation/failure behavior, and worked examples. | API routing, downstream consumer policy, or RFC implementation status. |
| `docs/technical/attribution-endpoint-certification.md` | Endpoint certification, known consumers, supportability, current caveats, and focused validation commands. | Broad product storytelling or unimplemented RFC 048 target state. |
| `wiki/Attribution-Analytics.md` | Durable product-facing overview for business users, operations, developers, sales/pre-sales, and demos. | Field-level API reference, test evidence logs, or detailed formula derivation. |
| `wiki/Supported-Features.md` | Implementation-backed supported capability ledger and demo-safe feature claims. | Future roadmap claims or unsupported fixed-income factor, derivative, sleeve, or composite attribution language. |
| `docs/RFCs/RFC-048-*.md` | RFC 048 implementation control evidence, slice decisions, validation, and branch reconciliation. | Durable product documentation after RFC closure. |

## Current Structure Decisions

1. Keep field-level API detail in OpenAPI and `docs/guides/attribution.md`.
2. Keep formulas in the metric methodology set; do not duplicate formula derivations in the wiki.
3. Keep RFC 048 source maps, slice evidence, and validation transcripts under `docs/RFCs/`.
4. Use `wiki/Attribution-Analytics.md` as the curated audience entrypoint for current
   implementation-backed attribution capability and limitations.
5. Do not promote fixed-income factor attribution, derivative exposure attribution, sleeve
   attribution, or composite attribution unless later RFC 048 slices implement and prove those
   capabilities.
6. Keep supported-feature claims in `wiki/Supported-Features.md`; link to detailed guides instead
   of duplicating field-level API reference in the wiki.

## Slice 2 Cleanup Review

Slice 2 did not remove attribution engine code. A targeted structure review found no safe dead
attribution code to delete before the status, residual, alignment, evidence, and data-product
slices. Removing calculation paths before those characterization tests would increase risk.

The cleanup performed in Slice 2 is documentation-structure cleanup:

1. create this single attribution documentation map;
2. add an implementation-backed wiki page for durable attribution product navigation;
3. update the methodology index and wiki navigation to point to the map and product page;
4. correct stale downstream Gateway issue status in endpoint certification;
5. add a docs contract test so the map and wiki page stay in navigation.

Later RFC 048 slices may still remove, consolidate, or refactor code if tests prove a path is dead,
duplicated, misleading, or overly coupled.
