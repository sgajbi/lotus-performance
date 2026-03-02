# Metric: Canonical Benchmark Return Series

## Quantitative Conventions
- Unless explicitly noted otherwise, endpoint-level performance and attribution outputs are expressed in **percentage points**.
- `returns/series` payload values are expressed in **decimal return form** (`0.0012 = 12 bps`).
- Geometric linking uses `Π(1+r_t)-1`.
- Annualization uses the configured day-count basis and annualization factor.

## Lotus-Performance Endpoint(s)
- `POST /integration/returns/series` with `series_selection.include_benchmark=true`.

## Supported Calculation Modes
- Stateless or stateful.

## Upstream Data Sources and Exact Data Points
- Stateless: `stateless_input.benchmark_returns[]`.
- Stateful lotus-core:
  - `POST /integration/portfolios/{portfolio_id}/benchmark-assignment` (if benchmark not provided)
  - `POST /integration/benchmarks/{benchmark_id}/return-series`.

## Inputs
- Benchmark point list (`series_date`, `benchmark_return`) and window/policy controls.

## Methodology and Formulas
- Normalize points, enforce window, resample by geometric linking, optionally align/fill against portfolio date set.

## Outputs
- `series.benchmark_returns[]`; diagnostics include gap and coverage effects.

## Configuration Options
- `benchmark.benchmark_id`, `series_selection.include_benchmark`, `data_policy.*`.

## Assumptions and Edge Cases
- Input series are expected to be date-valid, sortable, and semantically aligned with the request window.
- For insufficient observations or invalid denominator conditions, the engine returns deterministic error semantics (HTTP validation error and/or metric-level error details depending on endpoint contract).
- Where configured, policy controls (missing-data policy, fill method, reset rules, robustness policies) can materially change results and must be interpreted with diagnostics.`r`n`r`n## Worked Example
- Two daily benchmark returns 0.1%, 0.2% => 2-day linked = `(1.001*1.002)-1=0.3002%`.



