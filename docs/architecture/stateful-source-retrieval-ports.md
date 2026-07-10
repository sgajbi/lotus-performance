# Stateful Source Retrieval Ports

This note records the governed design boundary for GitHub issue `#447`.

`StatefulInputService` remains the application orchestration layer for stateful source retrieval.
It owns date-window planning, bounded pagination traversal, request fingerprinting, upstream
snapshot recording, response failure selection, and deduped payload assembly. It should not own
direct downstream Core API call details for every source family.

## Target Port Split

The target design is one named source-family port per high-risk source family:

| Source family | Port boundary | Current status |
| --- | --- | --- |
| Portfolio reference and portfolio timeseries | `StatefulPortfolioSourcePort` with `CoreStatefulPortfolioSourceAdapter` | Extracted behind a named port. |
| Position timeseries | Future `StatefulPositionSourcePort` | Still inside `StatefulInputService`; next similar-pattern candidate. |
| Benchmark/reference/market/index/risk-free series | Future market/reference source ports | Still inside `StatefulInputService`; should follow the same adapter pattern. |
| Performance component economics | Future economics source port | Still inside `StatefulInputService`; should preserve supportability aggregation semantics. |

The first extraction deliberately targets the portfolio source family because it is consumed by TWR,
MWR, Contribution, Attribution, Workspace Summary, inspections, and lineage evidence. It is also the
source family where pagination, dedupe, request fingerprinting, and upstream snapshot recording must
remain deterministic.

## Preserved Behavior

The extraction does not change public API behavior, OpenAPI shape, lineage contracts, result payload
shape, pagination guards, or execution evidence. `StatefulInputService.get_portfolio_timeseries(...)`
and `StatefulInputService.get_portfolio_reference(...)` remain the public methods used by existing
service and integration tests.

The portfolio port only owns the downstream source call contract:

- `fetch_reference(...)` maps to Core portfolio analytics reference.
- `fetch_timeseries_page(...)` maps to one bounded Core portfolio analytics timeseries page.

`StatefulInputService` still owns:

- chunk planning and concurrency,
- page-token loop detection and max-page failure,
- request payload construction for snapshot identity,
- request fingerprint and snapshot id generation,
- upstream snapshot batch recording,
- observation dedupe and retrieval metadata assembly.

## Runtime-Modularity Decision

This is an internal design-modularity improvement inside the existing `lotus-performance` deployable.
No separately deployed retrieval service is introduced. The current issue is monolithic responsibility
and source-call coupling, not independent scaling, data ownership, failure isolation, or separate
deployment cadence. A runtime split would add distributed-systems complexity without evidence that it
solves the measured hotspot.

## Regression Evidence

Focused tests cover:

- Core adapter request forwarding for portfolio reference and paged timeseries calls,
- injected fake-port orchestration proving `StatefulInputService` uses the portfolio source port,
- pagination request sequencing across `page_token=None` and `page_token="page-2"`,
- deduped observation output and retrieval metadata,
- upstream snapshot recording for portfolio timeseries and portfolio reference,
- request fingerprints and paging metadata after the extraction.

The same-pattern follow-up remains the non-portfolio source families listed in the target split table.
They should be extracted in later issue slices using the same port/adapter plus orchestration test
pattern, while preserving public `StatefulInputService` methods for compatibility until callers are
deliberately migrated.
