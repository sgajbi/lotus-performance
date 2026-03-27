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

The source contract should help that user experience instead of forcing permanent orchestration
complexity into `lotus-gateway`.

## Goals

1. Add a source-owned contract optimized for performance workspace refreshes.
2. Keep the contract explicit, modeled, and methodology-safe.
3. Reduce repeated upstream calls for standard workspace interactions.
4. Preserve the existing deep analytics endpoints as the canonical detailed surfaces.
5. Make the new contract testable, documented, and OpenAPI-visible.

## Non-Goals

1. Replacing the existing TWR, MWR, contribution, or attribution endpoints.
2. Creating an unbounded “workspace mega-endpoint” with unclear semantics.
3. Hiding methodology differences behind a flattened convenience response.
4. Bundling heavy detailed surfaces by default without clear interaction evidence.

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

## Proposed Contract Shape

Illustrative direction:

- endpoint:
  - `POST /performance/workspace-summary`

- request shape:
  - one portfolio context
  - one benchmark context
  - one resolved report anchor
  - multiple requested horizons
  - frequency controls
  - basis controls
  - optional inclusion toggles for heavier blocks

- response shape:
  - resolved benchmark context
  - resolved workspace metadata
  - `net_twr_by_period`
  - `gross_twr_by_period`
  - `benchmark_by_period`
  - `active_by_period`
  - `mwr_by_period`
  - optional lightweight contribution/attribution summary blocks only if explicitly requested

The important rule is that each block must preserve the unit and methodology semantics of its
source engine rather than inventing a flattened pseudo-metric.

## Architectural Direction

### 1. Reuse Existing Engines

The new surface should orchestrate the existing analytics engines and services rather than
re-implementing formulas.

That means:

1. shared period resolution,
2. shared benchmark resolution,
3. shared execution governance,
4. shared diagnostics/audit envelope discipline.

### 2. Keep Summary and Deep Surfaces Separate

The new contract should be summary-first.

Deep analysis should still use:

1. `/performance/contribution`
2. `/performance/attribution`
3. existing detailed TWR and benchmark surfaces

This keeps the workspace-summary surface interaction-friendly without weakening domain ownership.

### 3. Support Multiple Horizons Explicitly

The main interaction win is returning multiple standard horizons in one response for one resolved
portfolio/benchmark/basis context.

That prevents repeated round-trips for:

1. YTD
2. QTD
3. MTD
4. ITD
5. explicit windows where applicable

### 4. Avoid Implicit Methodology Mixing

The summary contract must not hide:

1. `NET` versus `GROSS`,
2. TWR versus MWR,
3. benchmark return versus active return,
4. contribution versus attribution.

Each block should stay explicitly named and documented.

## Delivery Slices

### Slice 1: Workspace Summary Contract

Outcome:

1. one request returns TWR `NET`, TWR `GROSS`, benchmark summary, active summary, and MWR summary,
2. multiple horizons supported in one response,
3. no contribution or attribution bundling yet.

Acceptance gate:

1. clear request/response models,
2. OpenAPI examples,
3. meaningful integration coverage,
4. no methodology ambiguity in units or naming.

### Slice 2: Interaction Telemetry and Runtime Policy

Outcome:

1. execution costs are measurable,
2. sync/async policy is explicit for the workspace surface,
3. runtime and lineage behavior remain truthful.

Acceptance gate:

1. execution policy documented,
2. diagnostics/audit remain bounded and useful,
3. no hidden heavy-path regressions.

### Slice 3: Optional Lightweight Contribution/Attribution Summaries

Outcome:

1. only if justified by measured workspace usage,
2. add explicit opt-in lightweight summary blocks,
3. keep detailed contribution and attribution as separate first-class endpoints.

Acceptance gate:

1. the summary contract remains readable,
2. no hidden large payload drift,
3. detailed surfaces are still the canonical drill-down path.

## Risks

1. A workspace summary endpoint could become an unbounded convenience blob if not carefully fenced.
2. Bundling too much too early could increase latency instead of reducing it.
3. If units and methodology labels are not explicit, the surface could make the front-end simpler at
   the cost of downstream confusion.
4. Async behavior could become harder to reason about if the summary contract silently embeds too
   many heavy paths.

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
3. methodology clarity must remain explicit at the response-model level,
4. contribution and attribution should stay separate detailed surfaces unless later evidence justifies
   lightweight opt-in summary blocks.

This RFC is complete in implementation terms when:

1. the new workspace-summary endpoint exists,
2. it is fully modeled and documented,
3. it has meaningful unit/integration coverage,
4. it preserves explicit units and methodology semantics,
5. it measurably reduces interaction call count for the workspace use case.

## Approval Requested

Approve this RFC if the team agrees that:

1. the current granular contract is correct but too chatty for premium workspace interactions,
2. the solution should be a source-owned workspace-summary contract,
3. the first slice should be summary-first and explicitly modeled,
4. deeper bundled analytics should remain a later, evidence-driven decision rather than a default.
