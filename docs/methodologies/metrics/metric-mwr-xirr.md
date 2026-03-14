## Metric
Money-Weighted Return via XIRR (`money_weighted_return` when method resolves to `XIRR`)

## Endpoint and Mode Coverage
- Endpoint: `POST /performance/mwr`
- Request mode: stateless payload (`begin_mv`, `end_mv`, `cash_flows[]`)
- Path coverage: applies when `mwr_method="XIRR"` and root solve converges

## Inputs
- `begin_mv`
- `end_mv`
- `cash_flows[]` (`date`, `amount`)
- `as_of` (terminal valuation date)
- `mwr_method` (`XIRR`)
- Optional controls: `annualization` block, `solver` object (currently informational in API; engine uses fixed Brent bounds)

## Upstream Data Sources
- No runtime upstream dependencies.
- All required data is provided in the request.

## Unit Conventions
- Cash flow and market values are currency amounts.
- `money_weighted_return` and `mwr_annualized` are returned in percentage points.
- XIRR solver uses decimal rate internally, then multiplies by 100 for response fields.

## Variable Dictionary
- `BV`: `begin_mv`
- `EV`: `end_mv`
- `CF_i`: cash flow amount on date `d_i`
- `t0`: XIRR anchor date `min(cash_flow_dates U {as_of})`
- `T`: terminal valuation date `as_of`
- `r`: XIRR annualized decimal rate
- `tau_j`: year fraction from anchor date using ACT/365.25: `(date_j - t0).days / 365.25`
- `V_j`: signed value at position `j` in the solver vector
- `NPV(r)`: discounted cash-flow sum used for root solving

## Methodology and Formulas
1. Cash-flow vector construction (`calculate_money_weighted_return`):
- `t0 = min(cash_flow_dates U {as_of})` (or `as_of` if no cash flows)
- `dates = [t0] + [d_i] + [T]`
- `values = [-BV] + [-CF_i] + [EV]`
- This means the engine treats a positive external contribution as a negative solver cash flow, because it is a cash outflow from the investor to the portfolio.

2. XIRR solve (`_xirr`):
- Define `NPV(r) = sum_j V_j / (1 + r)^(tau_j)`
- Solve `NPV(r)=0` with Brent on interval `[-0.99, 100.0]`
- If all `values` are same sign, solve is skipped and marked non-converged

3. Response mapping on convergence:
- `money_weighted_return = 100 * r`
- `mwr_annualized = 100 * r` (same value in current implementation)
- `method = "XIRR"`
- `start_date = t0`
- `end_date = T`

## Step-by-Step Computation
1. Determine `start_date`/`end_date` from request (`end_date = as_of`).
2. Build signed cash-flow schedule for XIRR solve (`-begin`, `-cashflows`, `+end`).
3. Check sign-change condition on `values`.
4. If sign change exists, solve `NPV(r)=0` with Brent.
5. On convergence, return XIRR outputs and `convergence.converged=true`.
6. On non-convergence/failure, append solver note, append `XIRR failed, falling back to Simple Dietz.`, and fall back to the Dietz path.

## Validation and Failure Behavior
- Request schema enforces required fields and types.
- If XIRR cannot run due to no sign change, engine returns note: `No sign change in cash flows.` and falls back to Dietz.
- If Brent fails/convergence error, engine note includes failure reason and falls back to Dietz.
- `convergence.iterations` and `convergence.residual` are currently `null`; the engine only populates `convergence.converged`.
- Endpoint-level unexpected error handling: HTTP 500.
- `solver` request parameters are currently not applied to engine solver settings.

## Configuration Options
- `mwr_method`: must be `XIRR` to attempt this path.
- `annualization`: ignored for successful XIRR path (engine already returns annual rate as both fields).
- `solver`: accepted by contract but currently informational only.

## Outputs
Primary fields for this metric when XIRR succeeds:
- `money_weighted_return`
- `mwr_annualized`
- `method` (`XIRR`)
- `convergence.converged`
- `convergence.iterations` (`null` in current implementation)
- `convergence.residual` (`null` in current implementation)
- `cashflows_used` when `emit_cashflows_used=true`
- `start_date`, `end_date`, `notes`

## Worked Example
Inputs:
- `begin_mv = 1000`
- `cash_flows = [{date: 2026-01-31, amount: 100}]`
- `end_mv = 1150`
- `as_of = 2026-12-31`

Constructed schedule for solver:

| j | date | `V_j` | `tau_j` (years from 2026-01-31) |
|---|---|---:|---:|
| 0 | 2026-01-31 | -1000 | 0.0000 |
| 1 | 2026-01-31 | -100 | 0.0000 |
| 2 | 2026-12-31 | +1150 | 0.9144 |

Equation:
- `-1100 + 1150 / (1+r)^0.9144 = 0`
- `r = (1150/1100)^(1/0.9144) - 1 = 0.05417`

Output mapping:
- `money_weighted_return = 5.417`
- `mwr_annualized = 5.417`
- `method = "XIRR"`
- `start_date = 2026-01-31`
- `end_date = 2026-12-31`
