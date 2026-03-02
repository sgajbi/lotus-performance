# Metric: TWR FX Return

## Quantitative Conventions
- Unless explicitly noted otherwise, endpoint-level performance and attribution outputs are expressed in **percentage points**.
- `returns/series` payload values are expressed in **decimal return form** (`0.0012 = 12 bps`).
- Geometric linking uses `Π(1+r_t)-1`.
- Annualization uses the configured day-count basis and annualization factor.

## Lotus-Performance Endpoint(s)
- `POST /performance/twr` (when `currency_mode=BOTH`).

## Supported Calculation Modes
- Stateless request payload with FX rates.

## Upstream Data Sources and Exact Data Points
- Request `fx.rates[]` by date/currency; optional hedge ratios from request.

## Inputs
- Start and end FX rates per day (`start_rate`, `end_rate`) and optional hedge ratio.

## Methodology and Formulas
- Daily FX return: `fx_ror_t = (end_rate_t/start_rate_t - 1)`, adjusted by hedge: `fx_ror_t *= (1-hedge_ratio_t)` when configured.
- Base return relation: `(1+R_base) = (1+R_local)*(1+R_fx)`, so period FX return reported as `R_fx = ((1+R_base)/(1+R_local)-1)*100`.

## Outputs
- `results_by_period[*].portfolio_return.fx`.

## Configuration Options
- `currency_mode`, `fx.rates`, `hedging.mode/series`.

## Assumptions and Edge Cases
- Input series are expected to be date-valid, sortable, and semantically aligned with the request window.
- For insufficient observations or invalid denominator conditions, the engine returns deterministic error semantics (HTTP validation error and/or metric-level error details depending on endpoint contract).
- Where configured, policy controls (missing-data policy, fill method, reset rules, robustness policies) can materially change results and must be interpreted with diagnostics.`r`n`r`n## Worked Example
- If period base=4.98228% and local=3.02%, then `fx=((1.0498228/1.0302)-1)*100=1.90476%`.



