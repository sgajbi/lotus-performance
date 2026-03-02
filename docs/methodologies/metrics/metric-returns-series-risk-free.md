# Metric: Canonical Risk-Free Return Series

## Quantitative Conventions
- Unless explicitly noted otherwise, endpoint-level performance and attribution outputs are expressed in **percentage points**.
- `returns/series` payload values are expressed in **decimal return form** (`0.0012 = 12 bps`).
- Geometric linking uses `Π(1+r_t)-1`.
- Annualization uses the configured day-count basis and annualization factor.

## Lotus-Performance Endpoint(s)
- `POST /integration/returns/series` with `series_selection.include_risk_free=true`.

## Supported Calculation Modes
- Stateless or stateful.

## Upstream Data Sources and Exact Data Points
- Stateless: `stateless_input.risk_free_returns[]`.
- Stateful lotus-core: `POST /integration/reference/risk-free-series` (`series_mode=return_series`, currency required).

## Inputs
- Risk-free return points, reporting currency (stateful), policy/window controls.

## Methodology and Formulas
- Normalize/filter/resample risk-free points; apply fill/alignment policy relative to portfolio series dates where requested.

## Outputs
- `series.risk_free_returns[]` and diagnostics.

## Configuration Options
- `reporting_currency` (required in stateful), `series_selection.include_risk_free`, `data_policy.*`.

## Assumptions and Edge Cases
- Input series are expected to be date-valid, sortable, and semantically aligned with the request window.
- For insufficient observations or invalid denominator conditions, the engine returns deterministic error semantics (HTTP validation error and/or metric-level error details depending on endpoint contract).
- Where configured, policy controls (missing-data policy, fill method, reset rules, robustness policies) can materially change results and must be interpreted with diagnostics.`r`n`r`n## Worked Example
- Daily risk-free points 0.01%,0.01%,0.01% => 3-day linked `(1.0001^3)-1=0.030003%`.



