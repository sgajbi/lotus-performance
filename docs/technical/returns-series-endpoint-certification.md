# Returns-Series Endpoint Certification

Last reviewed: 2026-07-06

Endpoint:

- `POST /integration/returns/series`
- `GET /integration/returns/series/results/{calculation_id}`

## Purpose

`POST /integration/returns/series` is the strategic integration contract for downstream analytics
engines that need aligned portfolio, benchmark, active, and risk-free return series. Use it when
another Lotus service needs reusable return observations. Do not call portfolio TWR, MWR, or
benchmark endpoints merely to reconstruct a return series.

The endpoint returns simple returns as decimal ratios. For example, `0.0012` means `0.12%`, not
`1.2%`.

Currency and FX vocabulary for returns-series is governed by the
[RFC-020 multi-currency support matrix](./rfc-020-multi-currency-support-matrix.md). This endpoint
emits aligned return observations and risk-free series by reporting currency; it does not emit
local/FX/base decomposition.

## Supported Options

| Option | Certified behavior |
| --- | --- |
| `input_mode=stateless` | Caller supplies portfolio returns and, when selected, benchmark/risk-free returns. |
| `input_mode=stateful` | lotus-performance sources portfolio analytics timeseries from lotus-core query control plane and resolves selected benchmark/risk-free side series. |
| `window.mode=EXPLICIT` | Uses caller-provided inclusive `from_date` and `to_date`. |
| `window.mode=RELATIVE` | Resolves MTD, QTD, YTD, 1Y, 3Y, 5Y, SI, or YEAR from `as_of_date`. |
| `frequency=DAILY` | Returns requested observations unchanged after window filtering and policy application. |
| `frequency=WEEKLY` / `MONTHLY` | Geometrically links daily points into period returns. |
| `metric_basis=NET` | Stateful portfolio series includes fee drag in the upstream portfolio-return calculation. |
| `metric_basis=GROSS` | Stateful portfolio series uses gross performance methodology from the shared engine normalization. |
| `series_selection.include_benchmark=true` | Emits benchmark, cumulative benchmark, active, and cumulative active series. |
| `series_selection.include_risk_free=true` | Emits risk-free and cumulative risk-free series when supplied or sourced. |
| `data_policy.FAIL_FAST` | Rejects missing portfolio coverage after calendar-policy filtering. |
| `data_policy.ALLOW_PARTIAL` | Returns available points with coverage diagnostics. |
| `data_policy.STRICT_INTERSECTION` | Keeps only dates common to selected series after any selected side-series fill method has been applied. |
| `fill_method=FORWARD_FILL` | Forward-fills selected benchmark/risk-free side series to portfolio dates before strict-intersection alignment. Leading side-series dates that cannot be filled remain absent. |
| `fill_method=ZERO_FILL` | Zero-fills selected benchmark/risk-free side series to portfolio dates before strict-intersection alignment. |
| `calendar_policy=BUSINESS` | Filters daily output to weekdays before coverage diagnostics and alignment. |
| `calendar_policy=MARKET` | Filters daily output to `lotus-reference-market-holidays.v1`, a generated Lotus reference market calendar for 1970-01-01 through 2099-12-31 with Good Friday, New Year, Christmas, and observed weekday holidays. Requests outside the certified horizon fail closed with `INVALID_REQUEST`. |
| `calendar_policy=CALENDAR` | Retains calendar-date daily observations. |
| `max_gap_days` | Emits a bounded `RETURNS_SERIES_GAP_TOLERANCE_EXCEEDED` warning when retained gaps exceed the caller tolerance; rejects under `FAIL_FAST`. |
| duplicate normalized dates | Rejects duplicate effective dates after request/model date normalization across portfolio, benchmark, and risk-free return series. |
| async accepted response | Long stateful windows, large resolved stateful workloads, and large stateless payloads return `202` with `poll_path` and endpoint-specific `result_path`. |

## Figure Tie-Outs

Every returned figure must satisfy these invariants:

| Output field | Certification check |
| --- | --- |
| `portfolio_returns` | Point returns match supplied stateless returns or stateful TWR-normalized daily observations, expressed as decimal ratios. |
| `cumulative_portfolio_returns` | Geometric link of `portfolio_returns`: product of `(1 + r)` minus `1`. |
| `benchmark_returns` | Caller-supplied stateless benchmark returns, vendor benchmark series, or calculated benchmark-engine output according to `benchmark.return_source`. |
| `cumulative_benchmark_returns` | Geometric link of `benchmark_returns`. |
| `risk_free_returns` | Caller-supplied or sourced risk-free period returns as decimal ratios. |
| `cumulative_risk_free_returns` | Geometric link of `risk_free_returns`. |
| `active_returns` | Arithmetic pointwise excess: `portfolio_return - benchmark_return` on aligned dates. |
| `cumulative_active_returns` | Arithmetic cumulative excess: `cumulative_portfolio_return - cumulative_benchmark_return`. It is intentionally not a linked active-return series. |
| `diagnostics.coverage` | Requested, returned, missing, and coverage-ratio values reconcile to the resolved window and calendar policy. |
| `diagnostics.gaps` | Retained gaps identify series type, start, end, and gap length. BUSINESS and MARKET daily diagnostics do not flag normal weekends as data gaps; MARKET also excludes the governed Lotus reference market holiday set. |
| `diagnostics.calendar_source` | MARKET responses expose the calendar source id, version, supported horizon, and holiday count so downstream consumers can distinguish certified market-calendar evidence from weekday-only behavior. |
| `diagnostics.fill_evidence` | Lists benchmark/risk-free dates synthesized by `FORWARD_FILL` or `ZERO_FILL` so filled side-series points are distinguishable from source-observed points. |
| `diagnostics.risk_free_source_quality` | Present when risk-free data is requested; reports raw, normalized, and skipped source-row counts so malformed optional reference rows are auditable. |
| `benchmark_context` | Present when benchmark was selected and includes resolved `benchmark_id` and `return_source`. |
| `provenance` | Stateful executions hash the resolved immutable input payload, not only the original lookup request. |

Completed returns-series executions emit bounded supportability metrics with
`operation="returns_series"`. `diagnostics.freshness="stale"` maps to
`supportability_state="stale"` and `reason="stale_source_observations"`; partial coverage,
retained gaps, warnings, or skipped risk-free source rows map to
`supportability_state="degraded"` and `reason="calculation_quality_issue"`; fully current and
complete responses map to `supportability_state="ready"` and `reason="calculation_complete"`.
Metric labels must remain limited to `operation`, `supportability_state`, `reason`, and
`freshness_bucket` and must not include portfolio, client, request, trace, or calculation
identifiers. Operator triage for stale freshness, partial coverage, skipped risk-free source rows,
and async failures is governed by `docs/runbooks/returns-series-operator-triage.md`.

## Upstream Integration

Stateful portfolio series source reads must use the lotus-core query control plane analytics-input
contract through `CORE_CONTROL_PLANE_BASE_URL`, especially:

- `POST /integration/portfolios/{portfolio_id}/analytics/reference`
- `POST /integration/portfolios/{portfolio_id}/analytics/portfolio-timeseries`

Stateful benchmark sourcing defaults to the lotus-performance benchmark calculation path. The
`vendor_series` override calls the lotus-core benchmark return-series contract only when explicitly
requested.

Risk-free source points are normalized by their `value_convention`. If lotus-core emits
`value_convention="annualized_rate"`, lotus-performance converts the annualized rate to a one-day
period return using the supplied day-count convention before any weekly or monthly geometric
linking. Supported day-count conventions are `ACT_360`, `ACT/360`, `ACT_365`, `ACT/365`,
`30_360`, `30/360`, and `THIRTY_360`; unsupported conventions are skipped and counted in
`diagnostics.risk_free_source_quality.skipped_points` instead of defaulting to `ACT_360`. This keeps
`risk_free_returns` contractually aligned with the rest of the endpoint: all returned series values
are period returns as decimal ratios.

Risk-free sourcing is currently available through stateful returns-series, but some downstream risk
paths still call lotus-core risk-free coverage and risk-free series directly when they need coverage
diagnostics alongside the return observations.

## Downstream Consumers

| Consumer | Status |
| --- | --- |
| `lotus-risk` stateful risk calculate, drawdown, rolling metrics, and historical attribution | Correctly calls `POST /integration/returns/series` and polls async results. It converts decimal ratios to percentage points at the risk-engine boundary. |
| `lotus-risk` rolling Sharpe risk-free support | Uses returns-series for portfolio/benchmark and lotus-core directly for risk-free series/coverage. This is not a returns-series defect, but it should remain an explicit downstream design choice because returns-series can also emit risk-free returns. |
| `lotus-gateway` risk workspace | Does not call returns-series directly. It reaches the series through `lotus-risk`, which is the correct orchestration boundary for risk analytics. |
| `lotus-gateway` performance workspace | Does not use returns-series directly; it uses performance workspace/TWR/contribution/attribution surfaces for UI analytics. |

No downstream direct call to a duplicate raw benchmark or TWR endpoint was found for this use case.
If a downstream UI only needs aligned return observations, it should use risk or this returns-series
contract rather than reconstructing returns from TWR, MWR, or benchmark endpoint payloads.

## Open Issue Review

- `lotus-performance#83` remains the broad RFC-0082 stateful sourcing hardening issue. This endpoint
  slice is aligned with that direction but does not close the issue by itself.
- `lotus-risk#77` remains a risk-side rolling Sharpe follow-up around live risk-free validation. The
  issue is not closed from lotus-performance because risk intentionally owns the rolling Sharpe
  application and currently uses lotus-core risk-free coverage detail directly.
- `lotus-gateway#107` is a contribution-detail gateway issue and is not applicable to returns-series.

## Validation Evidence

Focused certification covers:

- unit helpers for window resolution, resampling, market-calendar filtering, gap detection,
  max-gap tolerance, risk-free source normalization, async offload thresholds, and stateful settings;
- model validation for stateless/stateful envelopes and stateful-only benchmark overrides;
- integration tests for stateless figure tie-outs, stateful portfolio/benchmark/risk-free sourcing,
  vendor-series override, async accepted/result behavior, duplicate submission fencing, and policy behavior;
- OpenAPI schema tests for endpoint descriptions and field descriptions.

Live canonical validation on 2026-04-15 used portfolio `PB_SG_GLOBAL_BAL_001` with
`as_of_date=2026-04-10`, stateful YTD input, benchmark, risk-free selection, and
`calendar_policy=BUSINESS`. The source risk-free payload emitted `value="0.0435000000"` with
`value_convention="annualized_rate"` and `day_count_convention="ACT_360"`; the endpoint must return
a daily risk-free period return near `0.000120833333`, not `0.0435`. With BUSINESS calendar policy,
the YTD canonical response should return 72 weekday points and coverage ratio `1.0`.
