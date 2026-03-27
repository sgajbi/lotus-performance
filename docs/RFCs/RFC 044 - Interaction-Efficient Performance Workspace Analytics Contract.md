# RFC 044 - Interaction-Efficient Performance Workspace Analytics Contract

- Status: Proposed
- Date: 2026-03-27
- Owners: Performance Analytics Service
- Requires Approval From: lotus-performance maintainers

## Summary

`lotus-performance` should add a source-owned, interaction-efficient analytics contract for the
front-office performance workspace.

The goal is not to replace the existing deep analytics endpoints. The goal is to give
`lotus-gateway` and `lotus-workbench` one explicitly modeled contract for high-frequency workspace
refreshes where users change horizon, basis, frequency, and benchmark and expect a near-instant,
coherent analytical response.

This RFC proposes a new workspace-summary contract first, not a vague “everything bundle” endpoint.
It also fixes the economic-response bar for that surface: each requested period summary and
breakdown should return enough market-value and cash-flow context that the UI can render a serious
front-office performance workspace without reverse-engineering basic economics.

## Why This Is Needed

The current granular surfaces are correct and well-governed:

1. `POST /performance/twr`
2. `POST /performance/mwr`
3. `POST /performance/contribution`
4. `POST /performance/attribution`

That separation is good for methodology clarity and for bounded endpoint ownership. But it is not
ideal for an interactive front-office workspace.

Today a single workspace refresh can require multiple upstream calls for:

1. TWR `NET`
2. TWR `GROSS`
3. MWR
4. contribution
5. attribution

Even with gateway batching and UI caching, the upstream contract shape still drives avoidable
interaction cost.

## Problem Statement

The current contract is analytically correct but interaction-expensive.

For premium front-office workflows, users expect:

1. fast horizon switching,
2. smooth basis switching,
3. responsive benchmark changes,
4. dense analytical context without waiting on multiple stitched calls.

They also expect the standard workspace horizon family to be available directly from the source
contract, not inferred by the UI:

1. `1D`
2. `2D`
3. `5D`
4. `10D`
5. `1M`
6. `3M`
7. `6M`
8. `YTD`
9. `1Y`
10. `2Y`
11. `5Y`
12. `10Y`
13. `SI`

The source contract should help that user experience instead of forcing permanent orchestration
complexity into `lotus-gateway`.

## Goals

1. Add a source-owned contract optimized for performance workspace refreshes.
2. Keep the contract explicit, modeled, and methodology-safe.
3. Reduce repeated upstream calls for standard workspace interactions.
4. Preserve the existing deep analytics endpoints as the canonical detailed surfaces.
5. Make the new contract testable, documented, and OpenAPI-visible.
6. Support all standard attached period types plus `SI` in one request.
7. Return enough economic context per period that summary and breakdown rows are self-explanatory.
8. Keep contribution and attribution on one consistent segmentation model when both are included.
9. Keep benchmark support explicit and consistent across user-input and lotus-core-linked modes.
10. Use the same canonical vocabulary as the rest of `lotus-performance`, with no workspace-specific
    naming dialect.
11. Stay aligned with the broader Lotus cross-application vocabulary direction rather than
    introducing new local terms casually.

## Non-Goals

1. Replacing the existing TWR, MWR, contribution, or attribution endpoints.
2. Creating an unbounded “workspace mega-endpoint” with unclear semantics.
3. Hiding methodology differences behind a flattened convenience response.
4. Bundling heavy detailed surfaces by default without clear interaction evidence.
5. Allowing contribution and attribution to diverge into different segmentation contracts inside the
   same workspace surface.
6. Inventing workspace-local terms that drift from the rest of `lotus-performance` or from the
   broader Lotus vocabulary standard.

## Current State

The repository already has strong building blocks:

1. multi-period request resolution,
2. benchmark-aware TWR,
3. MWR,
4. contribution,
5. attribution,
6. durable async execution,
7. benchmark context,
8. cross-app validation with lotus-platform.

This means the problem is no longer missing analytics logic. The problem is contract composition for
interactive workspace use.

This RFC should therefore be read together with the repository’s broader vocabulary-governance
direction, especially:

1. [RFC 038 - PA Domain Vocabulary Alignment with Platform Glossary](C:/Users/Sandeep/projects/lotus-performance/docs/RFCs/RFC%20038%20-%20PA%20Domain%20Vocabulary%20Alignment%20with%20Platform%20Glossary.md)
2. the API vocabulary inventory under
   [docs/standards/api-vocabulary](C:/Users/Sandeep/projects/lotus-performance/docs/standards/api-vocabulary)

## Decision Direction

`lotus-performance` should introduce a new workspace-summary surface as the first slice.

The first version should optimize for the most common high-value interaction payload:

1. TWR `NET`
2. TWR `GROSS`
3. benchmark summary
4. active summary
5. MWR summary
6. multiple standard horizons in one response

Contribution and attribution should remain separate detailed surfaces initially unless measured
workspace evidence shows they must refresh on every interaction and can do so without making the
summary contract too heavy.

The surface should still support all requested attached period types plus `SI`, and it should be
smart about data sourcing:

1. fetch only the longest underlying date window required by the requested periods,
2. derive shorter requested periods from that same underlying data,
3. chunk downstream retrieval so upstream/core calls stay efficient and bounded.

If contribution and attribution are brought into the workspace surface in later slices, they should
use one shared segmentation model and the same requested period family. The workspace contract
should not force downstream consumers to normalize one grouping logic into another.

## Proposed Contract Shape

Illustrative direction:

- endpoint:
  - `POST /performance/workspace-summary`

- request shape:
  - one portfolio context
  - one benchmark context
  - one resolved report anchor
  - multiple requested horizons selected from the standard workspace family plus `SI`
  - frequency controls
  - basis controls
  - one shared segmentation definition for contribution and attribution when those blocks are requested
  - optional inclusion toggles for heavier blocks

- response shape:
  - resolved benchmark context
  - resolved workspace metadata
  - `net_twr_by_period`
  - `gross_twr_by_period`
  - `benchmark_by_period`
  - `active_by_period`
  - `mwr_by_period`
  - optional contribution and attribution blocks only if explicitly requested, both using the same
    segmentation contract when present

The important rule is that each block must preserve the unit and methodology semantics of its
source engine rather than inventing a flattened pseudo-metric.

The same rule applies to naming:

1. the workspace contract should reuse existing canonical Lotus vocabulary wherever those terms
   already exist,
2. new terms should be introduced only when they are genuinely new concepts,
3. any new public term should be suitable for reuse across Lotus apps rather than being a local UI
   convenience label.

Each returned period block should carry:

1. cumulative return,
2. annualized return,
3. beginning market value,
4. ending market value,
5. beginning-of-day cash flow,
6. end-of-day cash flow,
7. fees,
8. net cash flow,
9. flow-adjusted value.

Each requested breakdown inside that period should carry the same economic fields where they are
meaningful for the surface.

If contribution is included, the response should support both:

1. segmented contribution,
2. position-level contribution as a first-class output.

If attribution is included, the response should use the same segmentation definition as
contribution and support the same requested period family.

## Period Support and Annualization Semantics

The workspace-summary contract should directly support:

1. `1D`
2. `2D`
3. `5D`
4. `10D`
5. `1M`
6. `3M`
7. `6M`
8. `YTD`
9. `1Y`
10. `2Y`
11. `5Y`
12. `10Y`
13. `SI`

Annualization rule:

1. for periods longer than one year, the response must include an annualized return derived from
   the corresponding cumulative return over that period,
2. for periods at or below one year, `annualized_return` should still be present to keep the API
   surface consistent,
3. for those sub-one-year periods, `annualized_return` should equal `cumulative_return`.

This keeps the response model uniform and removes downstream conditional field handling.

The same period family rule should apply consistently to:

1. TWR summary,
2. benchmark summary,
3. active summary,
4. MWR summary,
5. contribution when included,
6. attribution when included.

## Architectural Direction

### 1. Reuse Existing Engines

The new surface should orchestrate the existing analytics engines and services rather than
re-implementing formulas.

That means:

1. shared period resolution,
2. shared benchmark resolution,
3. shared execution governance,
4. shared diagnostics/audit envelope discipline.

The summary surface should orchestrate those engines, not fork them.

### 2. Keep Summary and Deep Surfaces Separate

The new contract should be summary-first.

Deep analysis should still use:

1. `/performance/contribution`
2. `/performance/attribution`
3. existing detailed TWR and benchmark surfaces

This keeps the workspace-summary surface interaction-friendly without weakening domain ownership.

If contribution and attribution are later added to the workspace contract, the new summary surface
must still preserve the current deep endpoints as the canonical drill-down surfaces.

### 3. Support Multiple Horizons Explicitly

The main interaction win is returning multiple standard horizons in one response for one resolved
portfolio/benchmark/basis context.

That prevents repeated round-trips for:

1. YTD
2. QTD
3. MTD
4. ITD
5. explicit windows where applicable

For the performance workspace specifically, the standard attached-period family should be first-class
and source-owned, not left to UI emulation.

### 4. Source Data Once for the Longest Requested Period

The service should resolve the longest requested effective period first, then fetch only the data
needed for that longest window.

After that:

1. shorter requested periods should be derived from the same underlying retrieved data,
2. the service should not trigger a fresh downstream retrieval per requested horizon,
3. benchmark and portfolio sourcing should follow the same longest-window discipline where the
   underlying source contracts permit it.

This is one of the main performance wins of the RFC and should be treated as a core implementation
constraint, not an optional optimization.

### 5. Chunk Downstream Retrieval Explicitly

When the longest requested period implies a large window or large underlying series set, downstream
requests should be chunked rather than sent as one large unbounded pull.

That applies particularly to:

1. stateful portfolio timeseries retrieval,
2. stateful position timeseries retrieval,
3. benchmark component sourcing,
4. FX and related supplemental series.

Chunking must remain:

1. deterministic,
2. bounded,
3. observable through diagnostics/audit when needed,
4. invisible to the economic meaning of the final response.

### 6. Avoid Implicit Methodology Mixing

The summary contract must not hide:

1. `NET` versus `GROSS`,
2. TWR versus MWR,
3. benchmark return versus active return,
4. contribution versus attribution.

Each block should stay explicitly named and documented.

That also means:

1. contribution and attribution cannot silently use different segmentation semantics in the same
   workspace contract,
2. benchmark mode behavior cannot differ unpredictably across the returned analytical blocks.

### 7. Keep Vocabulary Canonical Across Surfaces

All API surfaces in `lotus-performance` should use the same vocabulary.

This workspace contract should therefore:

1. reuse the same canonical terms already used elsewhere in `lotus-performance`,
2. avoid introducing endpoint-local aliases for concepts that already exist,
3. align with the cross-Lotus vocabulary goal rather than creating a new workspace dialect.

That means the contract should be reviewed not only for response richness, but also for naming
discipline across:

1. request fields,
2. response fields,
3. diagnostics,
4. audit blocks,
5. OpenAPI descriptions,
6. examples,
7. downstream documentation.

Where this RFC proposes a new field, the default expectation should be:

1. use an existing canonical Lotus term if one already exists,
2. otherwise introduce a term that can be promoted across apps later rather than a local-only label.

### 8. Return Economic Context, Not Just Performance Percentages

This surface should not return “performance only.”

For each period summary and each requested breakdown, the response should provide the economic
context needed for front-office interpretation:

1. beginning market value,
2. ending market value,
3. beginning-of-day cash flow,
4. end-of-day cash flow,
5. fees,
6. net cash flow,
7. flow-adjusted value,
8. cumulative return,
9. annualized return.

Definitions should be explicit:

1. `net_cash_flow = bod_cash_flow + eod_cash_flow`
2. `flow_adjusted_value` should be documented per surface so downstream consumers do not guess how
   the denominator or adjusted capital base was formed

If one block cannot support one of these fields honestly, that omission should be explicitly modeled
and documented rather than silently skipped.

### 9. Keep Segmentation Consistent Across Contribution and Attribution

When the workspace contract carries contribution and attribution, both should support the same
segmentation model.

That means:

1. the same grouping vocabulary,
2. the same requested period family,
3. the same multi-level segmentation rules where multi-level output is supported,
4. no hidden downstream mapping requirement to reconcile one block with another.

Illustrative segmentation dimensions:

1. `asset_class`
2. `sector`
3. `country`
4. `currency`
5. approved multi-level combinations of those same dimensions

If the underlying stateful attribution path remains temporarily narrower than contribution for some
dimensions, that should be called out explicitly as a phased implementation constraint rather than
buried inside the workspace contract.

### 10. Position Contribution Must Remain First-Class

Position-level contribution should remain available whenever contribution is included.

That is important because:

1. top and bottom contributor views are fundamentally position-oriented,
2. grouped contribution alone is not sufficient for front-office ranking workflows,
3. the workspace should not force downstream consumers to reconstruct position ranking from grouped
   rollups.

### 11. Benchmark Support Must Be Consistent in Two Modes

The workspace contract should support benchmark context in two explicit modes:

1. user-input benchmark
2. linked benchmark sourced from lotus-core

This benchmark mode must be handled consistently across:

1. benchmark summary,
2. active summary,
3. attribution when included,
4. any later benchmark-aware contribution extension.

The response should preserve explicit benchmark context so consumers know whether they are looking
at:

1. a caller-supplied benchmark payload,
2. or a benchmark linked and resolved from lotus-core.

## Delivery Slices

### Slice 1: Workspace Summary Contract

Outcome:

1. one request returns TWR `NET`, TWR `GROSS`, benchmark summary, active summary, and MWR summary,
2. multiple horizons supported in one response,
3. all standard attached period types plus `SI` are supported,
4. annualized return is present for every returned period,
5. economic context fields are present for each summary and breakdown,
6. no contribution or attribution bundling yet.

Acceptance gate:

1. clear request/response models,
2. OpenAPI examples,
3. meaningful integration coverage,
4. no methodology ambiguity in units or naming,
5. longest-window sourcing is verified,
6. shorter periods are proven to reuse the same underlying sourced data,
7. downstream retrieval chunking is implemented and tested.

### Slice 2: Interaction Telemetry and Runtime Policy

Outcome:

1. execution costs are measurable,
2. sync/async policy is explicit for the workspace surface,
3. runtime and lineage behavior remain truthful.

Acceptance gate:

1. execution policy documented,
2. diagnostics/audit remain bounded and useful,
3. no hidden heavy-path regressions,
4. chunked sourcing behavior is observable enough to support troubleshooting,
5. longest-window optimization is regression-tested.
6. vocabulary choices are reviewed against existing canonical Lotus terms before they are exposed.

### Slice 3: Optional Lightweight Contribution/Attribution Summaries

Outcome:

1. only if justified by measured workspace usage,
2. add explicit opt-in lightweight summary blocks,
3. contribution and attribution use a shared segmentation model,
4. both support the same requested period family,
5. position-level contribution is present when contribution is included,
6. keep detailed contribution and attribution as separate first-class endpoints.

Acceptance gate:

1. the summary contract remains readable,
2. no hidden large payload drift,
3. detailed surfaces are still the canonical drill-down path,
4. contribution and attribution segmentation remains aligned,
5. benchmark mode behavior is explicit and testable.
6. vocabulary remains consistent with the rest of `lotus-performance` and suitable for broader
   Lotus reuse.

## Risks

1. A workspace summary endpoint could become an unbounded convenience blob if not carefully fenced.
2. Bundling too much too early could increase latency instead of reducing it.
3. If units and methodology labels are not explicit, the surface could make the front-end simpler at
   the cost of downstream confusion.
4. Async behavior could become harder to reason about if the summary contract silently embeds too
   many heavy paths.
5. If longest-window reuse is not enforced, the endpoint could become merely a server-side fan-out
   wrapper instead of a real interaction-efficiency improvement.
6. If market value, cash flow, fee, and flow-adjusted fields are not defined carefully, the
   contract could look rich while still leaving downstream consumers to guess economics.
7. If contribution and attribution segmentation drift, the workspace may look unified while still
   pushing hidden mapping complexity downstream.
8. If benchmark mode behavior is not explicit, user-input and lotus-core-linked benchmark paths
   could diverge in confusing ways.
9. If workspace-specific labels drift from the rest of the service, downstream systems may need
   special-case mapping logic even though the analytics are source-owned.

## Alternatives Considered

### Alternative 1: Keep all orchestration in lotus-gateway

Rejected as the long-term answer.

Reason:

1. the interaction cost is being driven partly by the upstream contract shape,
2. leaving that permanently in the gateway pushes source-owned API design debt downstream.

### Alternative 2: Bundle every analytics surface immediately

Rejected for the initial slice.

Reason:

1. contribution and attribution are heavier and more detailed,
2. bundling them by default risks turning the new surface into an opaque mega-endpoint.

### Alternative 3: Add only gateway/client caching and no upstream change

Rejected as sufficient on its own.

Reason:

1. caching helps,
2. but it does not remove the core contract chattiness for benchmark/basis/horizon refreshes.

## Acceptance Criteria

This RFC is ready for approval when the team agrees that:

1. `lotus-performance` should own an interaction-efficient workspace summary contract,
2. the first slice should focus on multi-horizon summary analytics rather than a full mega-bundle,
3. all standard attached period types plus `SI` should be supported directly by the contract,
4. annualized return should be returned for every period, with sub-one-year periods using the same
   value as cumulative return for surface consistency,
5. longest-window retrieval and chunked downstream sourcing should be required behavior,
6. methodology clarity must remain explicit at the response-model level,
7. contribution and attribution should stay separate detailed surfaces unless later evidence justifies
   lightweight opt-in summary blocks,
8. when contribution and attribution are included, they should use one shared segmentation model,
9. position-level contribution should remain available,
10. benchmark support should be explicit and consistent across user-input and lotus-core-linked
    modes.
11. the workspace contract should use canonical Lotus vocabulary and avoid endpoint-local naming
    drift.

This RFC is complete in implementation terms when:

1. the new workspace-summary endpoint exists,
2. it is fully modeled and documented,
3. it has meaningful unit/integration coverage,
4. it preserves explicit units and methodology semantics,
5. it supports all standard attached periods plus `SI`,
6. it returns cumulative and annualized return consistently for every period,
7. it returns market values, both cash flows, fees, net cash flow, and flow-adjusted value for
   each summary and requested breakdown,
8. it proves longest-window retrieval reuse and chunked downstream sourcing through meaningful
   tests,
9. when contribution and attribution are included, they use the same segmentation contract and the
   same requested period family,
10. position-level contribution is present when contribution is requested,
11. benchmark mode is explicit and consistent for user-input and lotus-core-linked paths,
12. vocabulary in models, OpenAPI, examples, and tests remains aligned with the rest of
    `lotus-performance` and compatible with cross-Lotus standardization,
13. it measurably reduces interaction call count for the workspace use case.

## Approval Requested

Approve this RFC if the team agrees that:

1. the current granular contract is correct but too chatty for premium workspace interactions,
2. the solution should be a source-owned workspace-summary contract,
3. the first slice should be summary-first and explicitly modeled,
4. the contract should directly support the standard attached period family plus `SI`,
5. the service should source only the longest required window and derive the shorter periods from the
   same data,
6. deeper bundled analytics should remain a later, evidence-driven decision rather than a default,
7. contribution and attribution should converge on a shared segmentation model inside the workspace
   contract,
8. benchmark support should remain explicit and consistent across user-input and lotus-core-linked
   modes,
9. the workspace contract should use canonical Lotus vocabulary and avoid introducing a new local
   naming dialect.
