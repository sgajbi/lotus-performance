# Metric: Total Active Return (Attribution Reconciliation)

## Quantitative Conventions
- Unless explicitly noted otherwise, endpoint-level performance and attribution outputs are expressed in **percentage points**.
- `returns/series` payload values are expressed in **decimal return form** (`0.0012 = 12 bps`).
- Geometric linking uses `Π(1+r_t)-1`.
- Annualization uses the configured day-count basis and annualization factor.

## Lotus-Performance Endpoint(s)
- `POST /performance/attribution`.

## Supported Calculation Modes
- Stateless.

## Upstream Data Sources and Exact Data Points
- Request payload portfolio and benchmark grouped data.

## Inputs
- Per-period portfolio and benchmark returns (derived from group panels).

## Methodology and Formulas
- Arithmetic (no linking): `AR = Σ_t (R_p,t - R_b,t)`.
- Linked mode: geometric active return from compounded portfolio minus compounded benchmark.
- Reconciliation: `residual = total_active_return - sum_of_effects`.

## Outputs
- `reconciliation.total_active_return`, `sum_of_effects`, `residual`.

## Configuration Options
- `linking` setting controls arithmetic vs scaled linked effects.

## Assumptions and Edge Cases
- Input series are expected to be date-valid, sortable, and semantically aligned with the request window.
- For insufficient observations or invalid denominator conditions, the engine returns deterministic error semantics (HTTP validation error and/or metric-level error details depending on endpoint contract).
- Where configured, policy controls (missing-data policy, fill method, reset rules, robustness policies) can materially change results and must be interpreted with diagnostics.`r`n`r`n## Worked Example
- If portfolio period return 6% and benchmark 5%, active return = 1.00%.



