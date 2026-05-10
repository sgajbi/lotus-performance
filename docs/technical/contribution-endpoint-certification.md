# Contribution Endpoint Certification

Status: certified for `POST /performance/contribution`

Canonical live portfolio: `PB_SG_GLOBAL_BAL_001`

Governed as-of date: `2026-04-10`

## Endpoint Purpose

`POST /performance/contribution` explains which positions and optional grouping dimensions drove a
portfolio return. Use it for front-office performance explanation, manager review, and private
banking portfolio conversations where the business question is "what contributed to this return?"

Use this endpoint for:

- position-level contribution and average-weight ranking;
- hierarchy-level contribution by supported stateful dimensions such as `asset_class`, `sector`,
  `country`, `currency`, and `position_id`;
- daily total contribution ladders;
- daily by-position contribution ladders;
- stateless caller-supplied valuation points;
- stateful lotus-core-sourced portfolio and position analytics inputs.

Do not use this endpoint for:

- portfolio headline return without position explanation. Use `POST /performance/twr`;
- investor capital-timing return. Use `POST /performance/mwr`;
- benchmark active-return attribution. Use the attribution endpoint;
- source-quality triage. Use the TWR inspector and upstream snapshots.

## Supported Request Options

Validated option families:

- `input_mode="stateful"` with `stateful_input.metric_basis`;
- `stateful_input.dimensions` for hierarchy metadata sourcing from lotus-core position timeseries;
- `stateful_input.include_cash_flows=true` and `false`;
- `input_mode="stateless"` with `stateless_input` or legacy top-level stateless payloads;
- `hierarchy` with level rows that reconcile to the period contribution total;
- `emit.timeseries`;
- `emit.by_position_timeseries`;
- `emit.top_n_per_level`;
- `emit.threshold_weight`;
- `emit.include_other`;
- `emit.include_unclassified`;
- `smoothing.method="CARINO"` and `"NONE"`;
- `currency_mode="BASE_ONLY"`, `"LOCAL_ONLY"`, and `"BOTH"` where source fields and FX inputs are
  sufficient;
- async `202 Accepted` result polling through `/performance/contribution/results/{calculation_id}`.

Compatibility note: `hierarchy` implies level output for existing clients. `emit.by_level=true`
documents the caller intent but is not required to receive hierarchy rows when hierarchy dimensions
are supplied.

## Required Figure Tie-Outs

Every certified contribution response must satisfy these invariants for each resolved period:

- `total_portfolio_return` is the portfolio TWR for the period in percentage-point units;
- `total_contribution` reconciles to `total_portfolio_return` after residual allocation;
- summed `position_contributions[].total_contribution` reconciles to `total_contribution`;
- summed `position_contributions[].average_weight` reconciles to 100%, allowing only tiny rounding
  dust;
- when `timeseries` is requested, summed daily total contribution reconciles to
  `total_contribution`;
- when `by_position_timeseries` is requested, summed by-position daily contribution reconciles to
  `total_contribution`;
- when `hierarchy` is requested, `summary.portfolio_contribution` and summed first-level
  `levels[].rows[].contribution` reconcile to `total_contribution`;
- hierarchy row `weight_avg` values are average portfolio weights in percentage units, and first
  level rows should reconcile to 100% when the requested visible scope covers the full portfolio.
- `smoothing_evidence.linked_return` reconciles to `total_portfolio_return`;
- `smoothing_evidence.final_contribution` reconciles to `total_contribution`;
- `smoothing_evidence.raw_residual`, `smoothing_residual`, and `post_allocation_residual` explain
  raw arithmetic mismatch, Carino smoothing residual, and final residual allocation posture without
  hidden recomputation.

The hierarchy path now builds rows from the same residual-adjusted daily position series used for
position output. This prevents hierarchy rows from drifting away from first-class position
contribution and avoids double-counting a position's weight when grouping metadata changes across
the period.

## Upstream Integration

Stateful contribution reads:

- `POST /integration/portfolios/{portfolio_id}/analytics/portfolio-timeseries`;
- `POST /integration/portfolios/{portfolio_id}/analytics/position-timeseries`.

The base URL must be `CORE_CONTROL_PLANE_BASE_URL`, not the lotus-core query-service read plane.

Stateful normalization maps lotus-core position rows into canonical contribution inputs:

- position and portfolio market values become beginning and ending valuation points;
- canonical `cash_flow_type="external_flow"` and `cash_flow_type="internal_trade_flow"` rows
  become position cash-flow adjustments;
- operational `cash_flow_type="fee"` rows remain fee drag;
- position dimensions become grouping metadata;
- source cash-flow type counts, selected FX metadata, and selected classification dimensions are
  preserved into `source_economics_evidence`;
- `include_cash_flows=false` is a scoped-source option that can intentionally remove cash-flow
  rows from the position story, and diagnostics should be read carefully when this creates
  non-flow-neutral slices.

Slice 5 upstream review concluded that `lotus-core` already supplies the essential contribution
analytics input contract for the current Lotus methodology: portfolio market values, position
market values, source cash-flow rows, FX conversion rates, dimensions, snapshot epoch, runtime
metadata, and execution snapshot lineage. No `lotus-core` code change was required in this slice.
Component P&L families that are not source-authored by the current contract remain explicit
unsupported/degraded evidence in lotus-performance rather than being reconstructed locally.

## Downstream Consumers

Current downstream consumers are:

| Consumer | How it uses contribution | Evidence |
| --- | --- | --- |
| `lotus-gateway` Workbench performance workspace | Calls `/performance/contribution` through `LotusAnalyticsClient.get_contribution_analytics`, then shapes contribution into performance workspace detail and summary blocks while preserving source-owned contribution return, smoothing evidence, and source-economics evidence. | `lotus-gateway/src/app/clients/lotus_analytics_client.py`; `lotus-gateway/src/app/services/performance_workspace_service.py`; `lotus-gateway/tests/unit/test_performance_workspace_service.py`; `lotus-gateway` PR `sgajbi/lotus-gateway#206` |
| `lotus-advise` through gateway-generated advisor brief context | Consumes Workbench performance contribution context rather than calling lotus-performance directly. | `lotus-gateway/src/app/services/advisor_brief_service.py` |
| `lotus-risk` | Does not consume `/performance/contribution`; its contribution terminology is risk-component contribution and attribution, not performance contribution. | `lotus-risk` client search |

## Supportability and Observability

Completed contribution responses now include `calculation_supportability` with bounded `state`,
`reason`, and `freshness_bucket` values plus input-row and resolved-period counts. The service also
increments:

`lotus_performance_calculation_supportability_total{operation="contribution",supportability_state,reason,freshness_bucket}`

Use this block as the source-owned freshness and degraded-state signal for front-office contribution
panels. The response publishes `calculation_supportability.metric_labels` with the same bounded
label keys used by the metric. The metric labels must not include portfolio, tenant, account,
benchmark, calculation, trace, correlation, request body, response body, or security identifiers.

Each resolved period also includes `smoothing_evidence`, a support-safe evidence block for raw
versus smoothed contribution. Use it to answer whether Carino was applied, whether invalid-domain
fallback occurred, what factor range was used, how far raw contribution was from linked return, and
whether final residual allocation was needed.

The top-level `source_economics_evidence` block explains whether contribution used caller-supplied
stateless inputs or lotus-core stateful analytics inputs, which source contracts were used, which
cash-flow families and classification dimensions were present, which component-P&L families are not
source-authored, and where upstream snapshot lineage is retained. Downstream consumers must preserve
this block instead of inferring source quality from rounded contribution totals.

## Data Product And Mesh Posture

Contribution is now promoted as `lotus-performance:ContributionAnalytics:v1`, a governed
portfolio-level performance explanation data product rather than a standalone endpoint. The product
declaration lives in `contracts/domain-data-products/lotus-performance-products.v1.json` and covers:

- routes: `POST /performance/contribution` and
  `GET /performance/contribution/results/{calculation_id}`;
- approved consumer: `lotus-gateway`, which feeds Workbench and advisor-brief experiences;
- freshness: daily, based on governed valuation-date source observations;
- lineage: required, customer-consumable lineage summary posture;
- trust metadata: product identity, generation/as-of dates, correlation and request fingerprints,
  source services, upstream fingerprints, data-quality status, coverage status, and coverage ratio;
- source dependencies: `lotus-core` `PortfolioTimeseriesInput:v1` and
  `PositionTimeseriesInput:v1`.

Repo-local trust telemetry is stored at
`contracts/trust-telemetry/contribution-analytics.telemetry.v1.json`. Platform SLO, access, and
evidence policy participation is provided under the RFC-047 platform branch so mesh certification
can recognize contribution as a governed product with blocking freshness, completeness,
reconciliation, data-quality, and lineage treatment.

## GitHub Issue Disposition

Open issue search for contribution currently finds only broad stateful-sourcing issue `#83`. That
issue remains open because it covers more than contribution endpoint certification. No direct open
contribution-output defect was found during this pass.

## Test Pyramid Assessment

| Layer | Coverage | Assessment |
| --- | --- | --- |
| Model and validation tests | Request-mode exclusivity, stateless and stateful payload validation, extra-field rejection, and emitted schema descriptions. | Good, with Swagger operation text hardened in this pass. |
| Engine and service tests | Position return, contribution linking, hierarchy aggregation, residual allocation, reset-aware shadow methodology, source-economics evidence, currency behavior, and async execution. | Strong for core contribution behavior. |
| Integration tests | `/performance/contribution`, async result retrieval, stateful resolution, source-economics evidence, hierarchy, series emission, lineage, duplicate submission fencing, and reset-heavy tie-out. | Strong after the source-economics and hierarchy tie-out regression tests added in this pass. |
| Documentation and OpenAPI tests | Public guide plus OpenAPI quality and vocabulary gates. | Adequate; this certification note records the endpoint-level invariants and consumer posture. |
| Cross-repo consumer tests | Gateway upstream client and performance workspace tests cover the known direct consumer; Workbench tests prove evidence status display. | Strong for known downstream consumers after RFC-047 Slice 7. |
| Live canonical probes | Stateful option matrix for `PB_SG_GLOBAL_BAL_001` across NET/GROSS, dimensions, hierarchy, cash-flow inclusion, top-N Other bucketing, and series emission. | Passed on rebuilt local service. |

## Live Canonical Evidence

Artifacts are under:

`artifacts/contribution-certification-2026-04-10/`

Rebuilt local runtime evidence for `PB_SG_GLOBAL_BAL_001`, YTD through `2026-04-10`:

| Case | Result |
| --- | --- |
| NET, `asset_class`, full emit | status `200`; portfolio return `0.122704%`; contribution `0.122704%`; 11 position rows; 100 daily rows; 11 by-position series; 4 level rows; first-level weights sum to about 100%; no diagnostics |
| GROSS, `asset_class`, full emit | status `200`; portfolio return `0.143168%`; contribution `0.143168%`; 11 position rows; 100 daily rows; 11 by-position series; 4 level rows; no diagnostics |
| NET, `sector`, with cash flows | status `200`; contribution and hierarchy rows reconcile to `0.122704%`; 7 first-level rows; first-level weights sum to about 100%; no diagnostics |
| NET, `country`, summary only | status `200`; hierarchy rows reconcile to `0.122704%`; 6 first-level rows; no series emitted because series were not requested |
| NET, flat position timeseries | status `200`; position rows, daily total series, and by-position series all reconcile to `0.122704%` |
| NET, `asset_class`, `top_n_per_level=2` | status `200`; 2 explicit rows plus one `Other` row; hierarchy contribution and weights reconcile |
| NET, `sector`, `include_cash_flows=false` | status `200`; contribution still reconciles to `0.122704%`, but diagnostics correctly flag the scoped-source caveat: position weights sum to about `99.4093%`, position reset boundary differs from portfolio reset boundary on one date, and position-level cash flows are non-flow-neutral on two dates |

Gateway live proof through `http://gateway.dev.lotus`:

- `/api/v1/workbench/PB_SG_GLOBAL_BAL_001/performance/details?as_of_date=2026-04-10&include_contribution=true&contribution_dimension=asset_class`
- returned `200` with `contribution_dimension="asset_class"`, one contribution level, 10
  rounded position rows, contribution capability `supported`, and portfolio contribution about
  `0.122704%`.

Downstream certification status:

- `lotus-gateway` successfully calls the contribution endpoint and preserves the source-owned
  contribution return, `smoothing_evidence`, and `source_economics_evidence` into the performance
  workspace contract.
- `lotus-workbench` renders source-economics and smoothing statuses from Gateway in the Performance
  Drivers module without inventing local quality state.
- RFC-047 Slice 7 downstream proof is recorded in
  `docs/RFCs/RFC-047-api-contract-downstream-slice7.md`. Gateway PR `sgajbi/lotus-gateway#206`
  and Workbench PR `sgajbi/lotus-workbench#177` were locally validated and CI-green when the slice
  was closed.

## Validation Commands

Focused checks for this certification slice:

```bash
python -m pytest tests/integration/test_contribution_api.py -q
python -m ruff check app/api/endpoints/contribution.py app/models/contribution_requests.py app/models/contribution_responses.py app/services/contribution_service.py tests/integration/test_contribution_api.py
python -m ruff format --check app/api/endpoints/contribution.py app/models/contribution_requests.py app/models/contribution_responses.py app/services/contribution_service.py tests/integration/test_contribution_api.py
python -m mypy app/api/endpoints/contribution.py app/models/contribution_requests.py app/models/contribution_responses.py app/services/contribution_service.py
python scripts/openapi_quality_gate.py
python scripts/api_vocabulary_inventory.py --validate-only
```

Focused downstream check:

```bash
# lotus-gateway
PYTHONPATH=src python -m pytest tests/unit/test_upstream_clients.py tests/unit/test_performance_workspace_service.py -q
```
