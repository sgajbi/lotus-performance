## Metric
Money-Weighted Return via XIRR (`money_weighted_return` when method resolves to `XIRR`)

## Endpoint and Mode Coverage
- Endpoint: `POST /performance/mwr`
- Request modes:
  - stateless payload (`stateless_input.begin_mv`, `stateless_input.end_mv`, `stateless_input.cash_flows[]`)
  - legacy stateless top-level `begin_mv`, `end_mv`, and `cash_flows[]`
  - stateful payload (`stateful_input.window_start_date`) resolved from lotus-core portfolio timeseries
- Path coverage: applies when `mwr_method="XIRR"` and root solve converges

## Inputs
- `begin_mv`
- `end_mv`
- `cash_flows[]` (`date`, `amount`)
- `start_date` when supplied directly or resolved from stateful normalization
- `as_of` (terminal valuation date)
- `mwr_method` (`XIRR`)
- Optional controls: `annualization` block, `solver` object (currently informational in API; engine uses fixed Brent bounds)

## Upstream Data Sources
- Stateless mode has no runtime upstream dependency; all required values are supplied by the caller.
- Stateful mode resolves source input from `lotus-core`
  `POST /integration/portfolios/{portfolio_id}/analytics/portfolio-timeseries` through
  `CORE_CONTROL_PLANE_BASE_URL`.
- Stateful normalization uses the first and last valid source observations for beginning and
  ending market value, includes explicit external or missing-classified source cash-flow rows,
  adds cross-observation carry-forward capital adjustments where beginning market value differs
  from the prior valid ending market value, and excludes operational fee-classified rows from the
  investor capital-flow schedule.

## Unit Conventions
- Cash flow and market values are currency amounts.
- `money_weighted_return` and `mwr_annualized` are returned in percentage points.
- XIRR solver uses decimal rate internally, then multiplies by 100 for response fields.

## Variable Dictionary
- `BV`: `begin_mv`
- `EV`: `end_mv`
- `CF_i`: cash flow amount on date `d_i`
- `S`: resolved start date (`stateful_input.window_start_date`, explicit `start_date`, or the
  earliest cash-flow date when no start date is supplied)
- `T`: terminal valuation date `as_of`
- `r`: XIRR annualized decimal rate
- `tau_j`: year fraction from resolved start date using ACT/365.25: `(date_j - S).days / 365.25`
- `V_j`: signed value at position `j` in the solver vector
- `NPV(r)`: discounted cash-flow sum used for root solving

## Methodology and Formulas
1. Cash-flow vector construction (`calculate_money_weighted_return`):
- `S` is the resolved measurement start date. In stateful mode it is the requested
  `stateful_input.window_start_date`; in stateless mode it is explicit `start_date`, the earliest
  cash-flow date, or `as_of` when no cash flows exist.
- `dates = [S] + [d_i] + [T]`
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
1. Resolve mode-specific inputs. In stateful mode retrieve lotus-core portfolio timeseries and
   normalize it into `begin_mv`, `end_mv`, signed `cash_flows[]`, and `start_date`.
2. Determine `start_date`/`end_date` from the resolved request (`end_date = as_of`).
3. Build signed cash-flow schedule for XIRR solve (`-begin`, `-cashflows`, `+end`).
4. Check sign-change condition on `values`.
5. If sign change exists, solve `NPV(r)=0` with Brent.
6. On convergence, return XIRR outputs and `convergence.converged=true`.
7. On non-convergence/failure, append solver note, append `XIRR failed, falling back to Simple Dietz.`, and fall back to the Dietz path.

## Validation and Failure Behavior
- Request schema enforces required fields and types.
- Stateful mode rejects missing `stateful_input`, rejects stateless payloads in stateful mode, and
  fails through the retrieval or normalization stage when lotus-core source data cannot produce a
  valid resolved MWR input.
- Source fee rows are preserved as performance drag by the upstream analytics input and are not
  included as investor cash flows; unsupported or invalid source cash-flow rows are skipped during
  normalization rather than guessed.
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
- `calculation_supportability`, `meta`, `diagnostics`, and `audit`

## Worked Example
Inputs:
- `begin_mv = 1000`
- `cash_flows = [{date: 2026-01-31, amount: 100}]`
- `end_mv = 1150`
- `start_date = 2026-01-31`
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
