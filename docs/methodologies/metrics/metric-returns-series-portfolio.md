# Metric: Canonical Portfolio Return Series

## Quantitative Conventions
- Unless explicitly noted otherwise, endpoint-level performance and attribution outputs are expressed in **percentage points**.
- `returns/series` payload values are expressed in **decimal return form** (`0.0012 = 12 bps`).
- Geometric linking uses `Π(1+r_t)-1`.
- Annualization uses the configured day-count basis and annualization factor.

## Lotus-Performance Endpoint(s)
- `POST /integration/returns/series`.

## Supported Calculation Modes
- `input_mode=stateless` or `input_mode=stateful`.

## Upstream Data Sources and Exact Data Points
- Stateless: caller supplies `stateless_input.portfolio_returns[]`.
- Stateful: lotus-core APIs via `CoreIntegrationService`:
  - `POST /integration/portfolios/{portfolio_id}/analytics/portfolio-timeseries`
  - transformed to valuation points and computed through lotus-performance TWR daily engine.

## Inputs
- Date/value return points (decimal form), frequency/window, data policy.

## Methodology and Formulas
- Validate/sort/filter window.
- If sourced from portfolio-timeseries, derive daily return using TWR formula from valuation points.
- Resample weekly/monthly by geometric linking.
- Apply alignment/fill/missing-data policies.

## Outputs
- `series.portfolio_returns[]`, plus diagnostics (`coverage`, `gaps`, warnings).

## Configuration Options
- `window`, `frequency`, `metric_basis`, `data_policy.*`, `series_selection`.

## Assumptions and Edge Cases
- Input series are expected to be date-valid, sortable, and semantically aligned with the request window.
- For insufficient observations or invalid denominator conditions, the engine returns deterministic error semantics (HTTP validation error and/or metric-level error details depending on endpoint contract).
- Where configured, policy controls (missing-data policy, fill method, reset rules, robustness policies) can materially change results and must be interpreted with diagnostics.`r`n`r`n## Worked Example
- Daily decimal returns: 0.01, 0.005, -0.0025, 0.003, 0.0015 => weekly linked return `(1.01*1.005*0.9975*1.003*1.0015)-1`.



