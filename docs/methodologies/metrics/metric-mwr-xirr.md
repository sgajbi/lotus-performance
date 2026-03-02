# Metric: Money-Weighted Return (XIRR)

## Quantitative Conventions
- Unless explicitly noted otherwise, endpoint-level performance and attribution outputs are expressed in **percentage points**.
- `returns/series` payload values are expressed in **decimal return form** (`0.0012 = 12 bps`).
- Geometric linking uses `Π(1+r_t)-1`.
- Annualization uses the configured day-count basis and annualization factor.

## Lotus-Performance Endpoint(s)
- `POST /performance/mwr` with `mwr_method="XIRR"`.

## Supported Calculation Modes
- Stateless (cash-flow schedule supplied in request).

## Upstream Data Sources and Exact Data Points
- Request payload only: `begin_mv`, `end_mv`, `cash_flows[]`, `as_of`.

## Inputs
- Cash-flow amounts/dates, initial value (negative sign in solver), terminal value.

## Methodology and Formulas
- Solve rate `r` such that `Σ CF_i/(1+r)^{t_i}=0` using Brent root finder over `[-0.99,100]`.
- Time exponent uses year fraction from earliest cash-flow date with 365.25 day denominator.
- If no sign change or convergence fails, engine falls back to Dietz.

## Outputs
- `money_weighted_return` (%), `mwr_annualized` (% for XIRR path), `method`, `convergence`, `notes`.

## Configuration Options
- `mwr_method`, `annualization` block, solver metadata fields (currently informational at API layer).

## Assumptions and Edge Cases
- Input series are expected to be date-valid, sortable, and semantically aligned with the request window.
- For insufficient observations or invalid denominator conditions, the engine returns deterministic error semantics (HTTP validation error and/or metric-level error details depending on endpoint contract).
- Where configured, policy controls (missing-data policy, fill method, reset rules, robustness policies) can materially change results and must be interpreted with diagnostics.`r`n`r`n## Worked Example
- Request from integration test returns ~`11.7234%` for given schedule (100000 -> 115000 with +10000 and -5000 intra-year flows).



