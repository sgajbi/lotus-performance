# Metric: Position FX Contribution

## Quantitative Conventions
- Unless explicitly noted otherwise, endpoint-level performance and attribution outputs are expressed in **percentage points**.
- `returns/series` payload values are expressed in **decimal return form** (`0.0012 = 12 bps`).
- Geometric linking uses `Π(1+r_t)-1`.
- Annualization uses the configured day-count basis and annualization factor.

## Lotus-Performance Endpoint(s)
- `POST /performance/contribution` (multi-currency path).

## Supported Calculation Modes
- Stateless.

## Upstream Data Sources and Exact Data Points
- Request valuation/FX inputs.

## Inputs
- Total contribution and local contribution by position/day.

## Methodology and Formulas
- Daily FX contribution derived as residual: `fx_contribution = total_contribution - local_contribution`.
- Period FX contribution is aggregated across days/groups.

## Outputs
- `fx_contribution` fields in position rows and summaries.

## Configuration Options
- `currency_mode=BOTH`, `fx`, smoothing mode.

## Assumptions and Edge Cases
- Input series are expected to be date-valid, sortable, and semantically aligned with the request window.
- For insufficient observations or invalid denominator conditions, the engine returns deterministic error semantics (HTTP validation error and/or metric-level error details depending on endpoint contract).
- Where configured, policy controls (missing-data policy, fill method, reset rules, robustness policies) can materially change results and must be interpreted with diagnostics.`r`n`r`n## Worked Example
- If period total contribution=1.10% and local=0.80%, FX contribution=0.30%.



