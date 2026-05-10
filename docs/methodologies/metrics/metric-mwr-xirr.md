## Metric
Money-Weighted Return via XIRR (`money_weighted_return` when method resolves to `XIRR`)

## Endpoint and Mode Coverage
- Endpoint: `POST /performance/mwr`
- Request modes:
  - stateless payload (`stateless_input.begin_mv`, `stateless_input.end_mv`, `stateless_input.cash_flows[]`)
  - legacy stateless top-level `begin_mv`, `end_mv`, and `cash_flows[]`
  - stateful payload (`stateful_input.window_start_date`) resolved from lotus-core portfolio timeseries
- Path coverage: applies when `mwr_method="XIRR"` and exactly one dated XIRR root is detected

## Inputs
- `begin_mv`
- `end_mv`
- `cash_flows[]` (`date`, `amount`)
- `start_date` when supplied directly or resolved from stateful normalization
- `as_of` (terminal valuation date)
- `mwr_method` (`XIRR`)
- `annualization.basis` and optional `annualization.periods_per_year`
- `solver.rate_lower_bound`, `solver.rate_upper_bound`, `solver.root_scan_steps`, `solver.tolerance`, and `solver.max_iter`

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
- `money_weighted_return`, `mwr_annualized`, and `holding_period_return` are percentage points.
- XIRR uses a decimal annual rate internally, then multiplies by 100 for response fields.
- Successful XIRR returns an annualized primary value; `holding_period_return` gives the measured-period equivalent.

## Variable Dictionary
- `BV`: `begin_mv`
- `EV`: `end_mv`
- `CF_i`: cash flow amount on date `d_i`
- `S`: resolved start date (`stateful_input.window_start_date`, explicit `start_date`, or the
  earliest cash-flow date when no start date is supplied)
- `T`: terminal valuation date `as_of`
- `r`: XIRR annualized decimal rate
- `D`: day-count denominator (`annualization.periods_per_year`, else `365.25` for `ACT/ACT`, else `365.0`)
- `tau_j`: year fraction from anchor date using `(date_j - anchor).days / D`
- `V_j`: signed value at position `j` in the solver vector after same-day netting
- `NPV(r)`: discounted cash-flow sum used for root solving

## Methodology and Formulas
1. Cash-flow vector construction (`calculate_money_weighted_return`):
- `S` is the resolved measurement start date. In stateful mode it is the requested
  `stateful_input.window_start_date`; in stateless mode it is explicit `start_date`, the earliest
  cash-flow date, or `as_of` when no cash flows exist.
- `dates = [S] + [d_i] + [T]`
- `values = [-BV] + [-CF_i] + [EV]`
- This means the engine treats a positive external contribution as a negative solver cash flow,
  because it is a cash outflow from the investor to the portfolio.

2. Same-day normalization:
- Solver inputs are netted by date after sign normalization.
- Zero net same-day rows are removed from the solver vector.
- The endpoint can still echo original `cashflows_used` for source evidence when
  `emit_cashflows_used=true`.

3. XIRR solve (`_xirr`):
- Define `NPV(r) = sum_j V_j / (1 + r)^(tau_j)`.
- The implementation scans the configured log-rate interval, brackets all sign-changing roots, and
  refines each candidate with bisection.
- If exactly one root is detected, the engine returns it.
- If zero roots or multiple roots are detected, the engine does not choose an arbitrary rate.

4. Response mapping on convergence:
- `money_weighted_return = 100 * r`
- `mwr_annualized = 100 * r`
- `holding_period_return = 100 * ((1 + r)^(period_days / D) - 1)`
- `method = "XIRR"`
- `status = "CALCULATED"`
- `is_annualized_primary = true`
- `is_approximation = false`

## Step-by-Step Computation
1. Resolve mode-specific inputs. In stateful mode retrieve lotus-core portfolio timeseries and
   normalize it into `begin_mv`, `end_mv`, signed `cash_flows[]`, and `start_date`.
2. Determine `start_date`/`end_date` from the resolved request (`end_date = as_of`).
3. Build signed cash-flow schedule for XIRR solve (`-begin`, `-cashflows`, `+end`).
4. Net same-day solver flows and remove zero net rows.
5. Reject empty/no-economic-content vectors and vectors without both positive and negative values.
6. Scan the configured log-rate interval, refine roots by bisection, and count unique roots.
7. Return XIRR only when exactly one root exists; otherwise enter the labeled Modified Dietz
   fallback branch.

## Validation and Failure Behavior
- Request schema enforces required fields and types.
- Stateful mode rejects missing `stateful_input`, rejects stateless payloads in stateful mode, and
  fails through the retrieval or normalization stage when lotus-core source data cannot produce a
  valid resolved MWR input.
- Source fee rows are preserved as performance drag by the upstream analytics input and are not
  included as investor cash flows; unsupported or invalid source cash-flow rows are skipped during
  normalization rather than guessed.
- `NO_ECONOMIC_CONTENT` returns `status="NOT_APPLICABLE"`.
- `NO_POSITIVE_AND_NEGATIVE_CASH_FLOW`, `NO_ROOT_FOUND`, `MULTIPLE_IRR_ROOTS_DETECTED`, and
  `INVALID_SOLVER_BOUNDS` enter a labeled Modified Dietz fallback unless no economic content exists.
- Labeled fallback responses set `status="FALLBACK_USED"`, include `DIETZ_FALLBACK_USED` in
  `reason_codes`, set `fallback_from="XIRR"`, set `fallback_reason`, and set
  `is_approximation=true`.
- `convergence` includes algorithm, searched bounds, day-count basis, anchor date, normalized flow
  count, gross cash-flow scale, root count, residual NPV, and converged state when applicable.
- Endpoint-level unexpected error handling: HTTP 500.

## Configuration Options
- `mwr_method`: must be `XIRR` to attempt this path.
- `annualization.basis`: controls dated year fractions (`ACT/365` default behavior for current
  MWR examples; `ACT/ACT` uses `365.25`).
- `annualization.periods_per_year`: overrides day-count denominator when supplied.
- `solver.rate_lower_bound` and `solver.rate_upper_bound`: searched annual-rate bounds.
- `solver.root_scan_steps`: number of log-rate scan points before bisection.
- `solver.tolerance` and `solver.max_iter`: bisection termination controls.

## Outputs
Primary fields for this metric when XIRR succeeds:
- `money_weighted_return`
- `mwr_annualized`
- `holding_period_return`
- `method` (`XIRR`)
- `status`
- `reason_codes`
- `warnings`
- `is_annualized_primary`
- `is_approximation`
- `convergence.converged`
- `convergence.root_count_detected`
- `convergence.residual_npv`
- `convergence.day_count_basis`
- `cashflows_used` when `emit_cashflows_used=true`
- `start_date`, `end_date`, `notes`
- `calculation_supportability`, `meta`, `diagnostics`, and `audit`

## Worked Example
Inputs:
- `begin_mv = 100000`
- `cash_flows = [{date: 2026-07-01, amount: 100000}]`
- `end_mv = 230000`
- `start_date = 2026-01-01`
- `as_of = 2027-01-01`
- `annualization.basis = ACT/365`

Constructed schedule for solver:

| j | date | `V_j` | `tau_j` (years from 2026-01-01) |
|---|---|---:|---:|
| 0 | 2026-01-01 | -100000 | 0.0000 |
| 1 | 2026-07-01 | -100000 | 0.4959 |
| 2 | 2027-01-01 | +230000 | 1.0000 |

Equation:
- `-100000 - 100000 / (1+r)^0.4959 + 230000 / (1+r)^1.0000 = 0`
- `r = 0.2025568893`

Output mapping:
- `money_weighted_return = 20.25568893`
- `mwr_annualized = 20.25568893`
- `holding_period_return = 20.25568893`
- `method = "XIRR"`
- `status = "CALCULATED"`
- `convergence.root_count_detected = 1`
- `convergence.residual_npv` is approximately `0.0`
