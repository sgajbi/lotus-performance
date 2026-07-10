# Workspace Summary Endpoint Certification

Status: certified for the RFC-0082 endpoint audit loop.

Endpoint:

- `POST /performance/workspace-summary`
- `GET /performance/workspace-summary/results/{calculation_id}`

## Purpose

Use workspace summary when a front-office workspace needs one coherent, source-owned performance
story across multiple horizons. The response returns bounded summary views for:

- portfolio TWR net and gross;
- benchmark return;
- active return;
- money-weighted return;
- audit, metadata, diagnostics, and async execution handles.

Do not use this endpoint for full contribution or attribution drill-downs. Use
`POST /performance/contribution` and `POST /performance/attribution` for those strategic analytical
surfaces.

Currency and FX vocabulary is governed by the
[RFC-020 multi-currency support matrix](./rfc-020-multi-currency-support-matrix.md). Workspace summary
preserves source endpoint currency posture and must not invent FX evidence absent from the source
response.

Gross/net vocabulary is governed by the
[RFC-021 gross/net support baseline](./rfc-021-gross-net-support-baseline.md). Workspace summary
ties out to direct TWR `metric_basis=NET` and `metric_basis=GROSS`; it does not emit a shared
`costs` request model or a top-level `gross_net` bridge.

## Certified Request Options

The certified request contract covers:

- `input_mode=stateless` with `stateless_input.valuation_points`;
- deprecated compatibility `valuation_points` for older stateless callers;
- `input_mode=stateful` with `stateful_input={}`;
- workspace periods `1D`, `2D`, `5D`, `10D`, `1M`, `3M`, `6M`, `YTD`, `1Y`, `2Y`, `5Y`, `10Y`,
  `SI`, and `EXPLICIT`;
- multiple breakdown frequencies per requested horizon;
- benchmark-enabled stateless requests using `return_source=vendor_series`;
- benchmark-enabled stateful requests using lotus-core benchmark assignment;
- sync response and async accepted/result response;
- `mwr_method=XIRR`, `MODIFIED_DIETZ`, or `DIETZ`;
- annualization metadata and uniform annualized-return output shape;
- `report_ccy` and `currency_mode` forwarding for stateful source reads.

## Output Figure Tie-Outs

The certification suite asserts every returned figure family against an authoritative source:

- `portfolio_twr.net.summary` equals direct `POST /performance/twr` with `metric_basis=NET`;
- `portfolio_twr.gross.summary` equals direct `POST /performance/twr` with `metric_basis=GROSS`;
- net and gross breakdown rows match direct TWR breakdown dates, period returns, and cumulative
  returns;
- `benchmark.summary` and benchmark breakdown rows match direct `POST /performance/benchmark`;
- `active.net` equals portfolio net return minus benchmark return;
- `active.gross` equals portfolio gross return minus benchmark return;
- `money_weighted_return.period_return` equals direct `POST /performance/mwr`;
- `money_weighted_return.cumulative_return` equals period return for the same resolved window;
- `money_weighted_return.annualized_return` equals cumulative return for periods up to one year;
- economics fields reconcile to the same valuation path:
  - beginning market value;
  - ending market value;
  - beginning-of-day cash flows;
  - end-of-day cash flows;
  - fees;
  - net cash flow;
  - flow-adjusted end market value.

The flow-adjusted end market value is `end_market_value - net_cash_flow` for the resolved window.
Fees remain fee drag in net TWR and are neutralized for gross TWR according to the TWR methodology.

## Upstream Integration

Stateful workspace summary uses the same governed source family as stateful TWR/MWR:

- lotus-core query-control-plane analytics reference;
- lotus-core portfolio analytics timeseries;
- lotus-core benchmark assignment and benchmark state contracts when benchmark output is requested.

The service resolves the longest required workspace window once, then derives shorter requested
horizons from the same sourced data. This avoids repeated upstream calls for each UI horizon.
Retrieval chunk and page counts are preserved in `audit.counts` for supportability.

## Downstream Consumers

Current strategic downstream consumer:

- `lotus-gateway`
  - client: `src/app/clients/lotus_analytics_client.py`
  - workspace service: `src/app/services/performance_workspace_service.py`
  - behavior: sends stateful workspace-summary requests for front-office performance workspace
    summary and detail surfaces.

No direct `lotus-risk` consumer was found for workspace summary during this certification pass.

Gateway usage is currently strategic rather than duplicate. It calls the workspace summary endpoint
for bounded front-office summary aggregation and uses dedicated surfaces for deeper analytics. No
downstream migration issue was opened for this endpoint slice.

## GitHub Issue Disposition

Open issue search found no workspace-summary-specific defect that remains valid for this slice.

Related but not closed by this endpoint certification:

- `lotus-performance#114`: already closed; the implemented workspace-summary contract and this
  certification pass are current evidence for the interaction-efficient workspace direction;
- `lotus-performance#83`: broader stateful sourcing architecture follow-up;
- `lotus-performance#123`: attribution totals, not workspace summary;
- `lotus-gateway#65`, `#66`, `#106`, `#107`: gateway front-office coverage items for adjacent
  surfaces.
- `lotus-gateway#108`: valid downstream supportability item; gateway must gate unsupported
  long-window TWR before presenting workspace horizons as clean front-office results.

## Test Pyramid

Coverage added or confirmed:

- model tests for workspace request/response schema and mode validation;
- service tests for stateful benchmark resolution, period resolution, async thresholds, and
  request validation;
- integration tests for multi-horizon response shape, annualization, async accepted/result behavior,
  and figure-level reconciliation against direct TWR/MWR/benchmark endpoints;
- OpenAPI test requiring endpoint descriptions and field descriptions for Swagger;
- docs tests covering public API references.

## Live Canonical Proof

Local runtime proof was taken against `performance-analytics` on `http://127.0.0.1:8002` with
lotus-core query-control-plane available on host port `8202`.

Request:

```json
{
  "portfolio_id": "PB_SG_GLOBAL_BAL_001",
  "report_end_date": "2026-04-10",
  "periods": [
    { "period": "YTD", "frequencies": ["daily", "monthly"] },
    { "period": "1M", "frequencies": ["daily", "monthly"] }
  ],
  "input_mode": "stateful",
  "stateful_input": {},
  "include_benchmark": true,
  "benchmark": { "input_mode": "stateful", "stateful_input": {} },
  "report_ccy": "USD",
  "currency_mode": "BASE_ONLY",
  "mwr_method": "XIRR"
}
```

Observed response:

- HTTP `200` synchronous response;
- portfolio `PB_SG_GLOBAL_BAL_001`;
- benchmark `BMK_PB_GLOBAL_BALANCED_60_40`;
- diagnostics note: `Benchmark summary uses stateful benchmark input with calculated returns.`;
- audit counts: `input_rows=100`, `periods_resolved=2`, `portfolio_chunk_count=2`,
  `portfolio_page_count=2`;
- current canonical Gateway-backed evidence for `PB_SG_GLOBAL_BAL_001`, `YTD`, `NET`,
  `BMK_PB_GLOBAL_BALANCED_60_40`, and report end `2026-05-08` returns net TWR
  `-0.691792`, gross TWR `-0.671493`, benchmark `6.997327`, active net `-7.689119`, and MWR
  `-1.926818`;
- contribution total ties to the workspace TWR at `-0.691791`; contribution smoothing evidence is
  `APPLIED` with `CARINO_FACTOR_APPLIED`, `RAW_CONTRIBUTION_DIFFERS_FROM_LINKED_RETURN`, and
  `RESIDUAL_ALLOCATED_TO_RECONCILE_PERIOD`;
- attribution returns `active_return_pct=-7.016227`, `sum_of_effects_pct=-7.016227`, and
  `residual_pct=0.0`;
- evidence view is `supported`, source service is `lotus-performance`, and calculation artifacts
  include request/response JSON plus workspace-summary portfolio daily result CSVs.

Live audit note - 2026-05-10:

- the earlier numerical certification bullets reflected a prior canonical seed snapshot and were
  stale against the currently running front-office stack;
- Gateway summary and details endpoints both returned HTTP `200` when called with required caller
  context headers;
- `input_freshness` reported `performance=stale` and `benchmark=stale` because the canonical
  Workbench as-of date is `2026-05-10` while the latest performance and benchmark evidence is
  `2026-05-08`; this is surfaced explicitly rather than hidden;
- live validation with `npm run live:validate` was rerun as part of the audit.

## Certification Commands

Focused commands for this endpoint:

```bash
python -m pytest tests/integration/test_performance_api.py::test_workspace_summary_endpoint_reconciles_all_summary_figures -q
python -m pytest tests/integration/test_response_attribute_certification.py::test_workspace_summary_does_not_drift_from_direct_twr_and_mwr_endpoints -q
python -m pytest tests/unit/app/test_workspace_summary_openapi_contract.py tests/unit/models/test_workspace_summary_models.py tests/unit/services/test_workspace_summary_service.py -q
```

For PR readiness, also run the repository OpenAPI and vocabulary gates after any schema or docs
change.
