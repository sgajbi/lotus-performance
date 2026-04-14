# Workspace Summary Guide

`POST /performance/workspace-summary` is the source-owned, interaction-efficient surface for
front-office performance workspaces.

It is designed for the case where one user action needs several coherent views of the same
economic window:

- portfolio TWR `NET`
- portfolio TWR `GROSS`
- benchmark return
- active return
- money-weighted return

The purpose of this endpoint is not to replace the dedicated deep-analysis surfaces. The purpose is
to let one request return one coherent multi-horizon workspace story with canonical vocabulary and
clear economics.

## Current request contract

The current request shape is:

- `input_mode: "stateless" | "stateful"`
- `portfolio_id`
- `report_end_date`
- `periods`
- optional `report_start_date` when periods include `EXPLICIT`
- optional `include_benchmark`
- optional `benchmark`

Stateless callers provide:

- `performance_start_date`
- `stateless_input.valuation_points`

Stateful callers provide:

- `stateful_input`
- optional `report_ccy`
- optional `currency_mode`
- optional `fx`

## Supported period family

The current workspace period family is:

- `1D`
- `2D`
- `5D`
- `10D`
- `1M`
- `3M`
- `6M`
- `YTD`
- `1Y`
- `2Y`
- `5Y`
- `10Y`
- `SI`
- `EXPLICIT`

Annualization is always present in the response:

- for periods up to one year, `annualized_return` intentionally equals `cumulative_return`
- for periods longer than one year, `annualized_return` is derived from the cumulative return over
  the resolved window

This keeps the workspace surface uniform across all requested periods.

Return semantics are now explicit across the workspace surface:

- `period_return` is the return earned inside the current resolved summary window or breakdown bucket
- `cumulative_return` is the return accumulated through the end of that summary window or bucket
- `annualized_return` is always present; for periods up to one year it intentionally equals
  `cumulative_return`

## Economic context returned

Workspace summary and breakdown blocks return the economics needed to interpret the period honestly:

- `begin_market_value`
- `end_market_value`
- `beginning_cash_flow`
- `ending_cash_flow`
- `fees`
- `net_cash_flow`
- `flow_adjusted_end_market_value`
- `period_return`
- `cumulative_return`
- `annualized_return`

This is deliberate. The workspace surface should not force downstream apps to guess basic market
value and flow context from return percentages alone.

## Longest-window sourcing behavior

The service resolves the longest requested effective period first, then sources only that longest
window from upstream systems.

After that:

- shorter periods are derived from the same sourced data
- the service does not perform one fresh upstream retrieval per requested horizon
- stateful retrieval is chunked and bounded
- audit counts preserve the retrieval shape so troubleshooting remains possible

This is one of the main reasons the endpoint exists.

## Benchmark support

Benchmark behavior is explicit in two modes:

- user-input benchmark
- lotus-core-linked benchmark

Stateless mode requires an explicit benchmark payload when `include_benchmark=true`.

Stateful mode can:

- resolve an explicitly supplied stateful benchmark request
- or resolve the linked benchmark from lotus-core assignment

The response keeps this explicit through:

- `benchmark.benchmark_id`
- `benchmark.input_mode`
- `benchmark.return_source`

## Sync and async behavior

Workspace summary can run synchronously or asynchronously.

For lighter requests:

- the endpoint returns a final `WorkspaceSummaryResponse`

For heavier requests:

- the endpoint returns `202 Accepted`
- the response includes:
  - `calculation_id`
  - `poll_path`
  - `result_path`

Polling pattern:

1. submit `POST /performance/workspace-summary`
2. if accepted, poll `GET /performance/executions/{calculation_id}`
3. retrieve the final result from `GET /performance/workspace-summary/results/{calculation_id}`

## Canonical examples

Canonical example files:

- [workspace_summary_request.json](../examples/workspace_summary_request.json)
- [workspace_summary_stateful_detail_request.json](../examples/workspace_summary_stateful_detail_request.json)
- [workspace_summary_accepted_response.json](../examples/workspace_summary_accepted_response.json)

### Stateless example

This shape is used when the caller owns the portfolio valuations and benchmark return points
directly.

Key characteristics:

- multiple requested horizons in one request
- explicit user-input benchmark
- no contribution or attribution detail blocks

### Stateful example

This shape is used when lotus-performance should source the underlying portfolio and benchmark
state.

Key characteristics:

- explicit benchmark inclusion with stateful resolution
- one coherent request for TWR, benchmark, active, and MWR views

### Async accepted example

This is the canonical accepted-response shape:

```json
{
  "calculation_id": "0d000003-1111-4222-8333-abcdefabcdef",
  "poll_path": "/performance/executions/0d000003-1111-4222-8333-abcdefabcdef",
  "result_path": "/performance/workspace-summary/results/0d000003-1111-4222-8333-abcdefabcdef"
}
```

## Response reading guide

A healthy workspace response should tell one coherent economic story at different levels of detail:

- `portfolio_twr` is the headline portfolio performance
- `benchmark` is the comparison baseline
- `active` is the arithmetic difference between portfolio and benchmark
- `money_weighted_return` is the capital-timing lens for the same window

At the field level, read the return blocks as:

- `portfolio_twr.<basis>.summary.period_return`: return earned in the resolved period
- `portfolio_twr.<basis>.summary.cumulative_return`: cumulative return for that resolved period
- `portfolio_twr.<basis>.breakdowns.<frequency>[].period_return`: return earned inside that bucket
- `portfolio_twr.<basis>.breakdowns.<frequency>[].cumulative_return`: cumulative return through the
  end of that bucket
- `benchmark.summary.period_return` and `benchmark.summary.cumulative_return`: same semantics for
  the resolved benchmark window
- `active.net.period_return` and `active.net.cumulative_return`: active-period and active-cumulative
  views for the same window
- `active.gross.period_return` and `active.gross.cumulative_return`: same semantics for the gross
  active lens
- `money_weighted_return.period_return` and `money_weighted_return.cumulative_return`: both are
  emitted for surface consistency on the resolved MWR window

That is why shared vocabulary matters. These are not separate truths; they are different lenses on
the same underlying economic path.

## Useful audit and diagnostics fields

The workspace surface keeps runtime and sourcing behavior visible:

- `audit.counts.portfolio_chunk_count`
- `audit.counts.portfolio_page_count`
- `audit.counts.benchmark_chunk_count`

Diagnostics notes make sourcing posture explicit, including:

- benchmark summary enabled

Use `/docs` for the generated field-level schema and examples. Use the dedicated deep endpoints when
the workspace needs full analytical drill-down rather than bounded summary context.

## Capability discovery

Downstream Lotus apps should not hardcode workspace-summary behavior from prose documentation alone.

`GET /integration/capabilities` now advertises `workspace_summary` as a first-class analytics
surface with:

- `path=/performance/workspace-summary`
- `supports_async=true`
- `poll_path_template=/performance/executions/{calculation_id}`
- `result_path_template=/performance/workspace-summary/results/{calculation_id}`
- `contract_notes` for:
  - multi-horizon workspace period support
  - annualized-return semantics
  - longest-window sourcing behavior
- machine-readable `options` for:
  - `benchmark_mode`

That capability contract is the machine-readable source for downstream surface discovery. The guide
explains the behavior; the capabilities surface advertises what is currently supported.

The current workspace-summary option map should be read as:

- `benchmark_mode`
  - `user_input_stateless`
  - `linked_stateful`

This lets a downstream client validate the broad request shape before sending the request:

- whether the desired benchmark mode is supported

For one concrete machine-readable example, see:

- [integration_capabilities_response.json](../examples/integration_capabilities_response.json)
