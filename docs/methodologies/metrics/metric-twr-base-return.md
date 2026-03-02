# Metric: TWR Base Return

## Quantitative Conventions
- Unless explicitly noted otherwise, endpoint-level performance and attribution outputs are expressed in **percentage points**.
- `returns/series` payload values are expressed in **decimal return form** (`0.0012 = 12 bps`).
- Geometric linking uses `Π(1+r_t)-1`.
- Annualization uses the configured day-count basis and annualization factor.

## Lotus-Performance Endpoint(s)
- `POST /performance/twr`

## Supported Calculation Modes
- Stateless request payload (caller provides valuation points).

## Upstream Data Sources and Exact Data Points
- Primary: request payload `valuation_points[]` (`perf_date`, `begin_mv`, `end_mv`, `bod_cf`, `eod_cf`, `mgmt_fees`).
- No runtime upstream service call for this endpoint.

## Inputs
- Daily valuation series in portfolio/reporting base view.
- `metric_basis` (`NET` includes `mgmt_fees`; `GROSS` excludes).
- Period definitions via `analyses[]` and date anchors.

## Methodology and Formulas
- Daily return (percent): `daily_ror = ((end_mv - bod_cf - begin_mv - eod_cf + fee_adjustment) / abs(begin_mv + bod_cf)) * 100`, where `fee_adjustment = mgmt_fees` only for `NET`.
- Multi-day period return: geometric link `R_period = (Π(1 + daily_ror_t/100) - 1) * 100`.
- With reset events, period total is derived from cumulative return ladders before/after reset boundaries (see `engine/ror.py` + endpoint reset slice logic).

## Outputs
- `results_by_period[*].portfolio_return.base`
- Breakdown summaries `period_return_pct`, optional `cumulative_return_pct_to_date`, optional `annualized_return_pct`.

## Configuration Options
- `metric_basis`, `analyses[]`, `annualization.*`, `output.include_*`, `rounding_precision`, `data_policy`.

## Assumptions and Edge Cases
- Input series are expected to be date-valid, sortable, and semantically aligned with the request window.
- For insufficient observations or invalid denominator conditions, the engine returns deterministic error semantics (HTTP validation error and/or metric-level error details depending on endpoint contract).
- Where configured, policy controls (missing-data policy, fill method, reset rules, robustness policies) can materially change results and must be interpreted with diagnostics.`r`n`r`n## Worked Example
- Day1: begin 1000, end 1010, CF=0 => `r1=1.0%`
- Day2: begin 1010, end 1020.1, CF=0 => `r2=1.0%`
- TWR base = `(1.01*1.01 - 1)*100 = 2.01%`.



