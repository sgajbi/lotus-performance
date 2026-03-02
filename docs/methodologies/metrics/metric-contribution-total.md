# Metric: Position Total Contribution

## Quantitative Conventions
- Unless explicitly noted otherwise, endpoint-level performance and attribution outputs are expressed in **percentage points**.
- `returns/series` payload values are expressed in **decimal return form** (`0.0012 = 12 bps`).
- Geometric linking uses `Π(1+r_t)-1`.
- Annualization uses the configured day-count basis and annualization factor.

## Lotus-Performance Endpoint(s)
- `POST /performance/contribution`.

## Supported Calculation Modes
- Stateless input bundle (`portfolio_data`, `positions_data`).

## Upstream Data Sources and Exact Data Points
- Request payload only.

## Inputs
- Position and portfolio valuation series, weighting scheme (`BOD`), smoothing method.

## Methodology and Formulas
- Daily weight: `w_i,t = capital_i,t / capital_port,t`, where `capital = begin_mv + bod_cf` for BOD mode.
- Raw contribution: `c_i,t = w_i,t * r_i,t`.
- Multi-period linking uses Carino smoothing when configured, plus residual allocation by average weight so sum of position contributions reconciles to portfolio return.

## Outputs
- `results_by_period[*].position_contributions[].total_contribution`
- Period `total_contribution` and `total_portfolio_return`.

## Configuration Options
- `weighting_scheme`, `smoothing.method`, `hierarchy`, `currency_mode`.

## Assumptions and Edge Cases
- Input series are expected to be date-valid, sortable, and semantically aligned with the request window.
- For insufficient observations or invalid denominator conditions, the engine returns deterministic error semantics (HTTP validation error and/or metric-level error details depending on endpoint contract).
- Where configured, policy controls (missing-data policy, fill method, reset rules, robustness policies) can materially change results and must be interpreted with diagnostics.`r`n`r`n## Worked Example
- If two days have `w=0.6`, returns 1% and 2%, raw contribution = `0.6*0.01 + 0.6*0.02 = 1.8%` before smoothing/residual.



