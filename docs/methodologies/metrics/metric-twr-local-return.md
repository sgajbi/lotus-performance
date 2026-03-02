# Metric: TWR Local Return

## Quantitative Conventions
- Unless explicitly noted otherwise, endpoint-level performance and attribution outputs are expressed in **percentage points**.
- `returns/series` payload values are expressed in **decimal return form** (`0.0012 = 12 bps`).
- Geometric linking uses `Π(1+r_t)-1`.
- Annualization uses the configured day-count basis and annualization factor.

## Lotus-Performance Endpoint(s)
- `POST /performance/twr` (when `currency_mode=BOTH`).

## Supported Calculation Modes
- Stateless request payload with FX context.

## Upstream Data Sources and Exact Data Points
- Primary: request `valuation_points[]`.
- FX path: request `fx.rates[]`; optional `hedging.series[]`.

## Inputs
- Same valuation points as base TWR.
- Local path isolates asset return before FX.

## Methodology and Formulas
- Engine computes local leg daily return (`local_ror`) from valuation equation before FX translation.
- Period local return is geometric link of daily local returns: `R_local = Π(1 + local_ror_t) - 1` (scaled to % in response).

## Outputs
- `results_by_period[*].portfolio_return.local`.

## Configuration Options
- `currency_mode=BOTH`, `report_ccy`, `fx`, optional `hedging`, `metric_basis`.

## Assumptions and Edge Cases
- Input series are expected to be date-valid, sortable, and semantically aligned with the request window.
- For insufficient observations or invalid denominator conditions, the engine returns deterministic error semantics (HTTP validation error and/or metric-level error details depending on endpoint contract).
- Where configured, policy controls (missing-data policy, fill method, reset rules, robustness policies) can materially change results and must be interpreted with diagnostics.`r`n`r`n## Worked Example
- Local daily returns: 2.00%, 1.00% => `R_local=(1.02*1.01-1)*100=3.02%`.



