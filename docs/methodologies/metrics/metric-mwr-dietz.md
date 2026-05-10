## Metric
Money-Weighted Return via Dietz family (`money_weighted_return` when method resolves to `DIETZ`
or `MODIFIED_DIETZ`)

## Endpoint and Mode Coverage
- Endpoint: `POST /performance/mwr`
- Request modes:
  - stateless payload (`stateless_input.begin_mv`, `stateless_input.end_mv`, `stateless_input.cash_flows[]`)
  - legacy stateless top-level `begin_mv`, `end_mv`, and `cash_flows[]`
  - stateful payload (`stateful_input.window_start_date`) resolved from lotus-core portfolio timeseries
- Path coverage:
  - explicit request `mwr_method="DIETZ"` or `"MODIFIED_DIETZ"`
  - labeled fallback when `mwr_method="XIRR"` cannot produce one unambiguous root
- Current implementation returns `method="MODIFIED_DIETZ"` for weighted cash-flow capital and
  `method="DIETZ"` for the midpoint Simple Dietz path.

## Inputs
- `begin_mv`
- `end_mv`
- `cash_flows[]` (`amount`, `date`)
- `start_date` when supplied directly or resolved from stateful normalization
- `as_of`
- `annualization.enabled`
- `annualization.basis` (`ACT/ACT` or other -> 365.0)

## Upstream Data Sources
- Stateless mode has no runtime upstream dependency; all required values are supplied by the caller.
- Stateful mode resolves source input from `lotus-core`
  `POST /integration/portfolios/{portfolio_id}/analytics/portfolio-timeseries` through
  `CORE_CONTROL_PLANE_BASE_URL`.
- Stateful normalization uses first and last valid source observations for beginning and ending
  market value, includes explicit external or missing-classified source cash-flow rows, adds
  cross-observation carry-forward capital adjustments where beginning market value differs from the
  prior valid ending market value, and excludes operational fee-classified rows from the investor
  capital-flow schedule.

## Unit Conventions
- Amount fields are currency amounts.
- `begin_mv`, `end_mv`, and `cash_flows[].amount` must be in one reporting currency before the
  Dietz-family calculation runs; current `cashflows_used` output is schedule evidence, not FX
  conversion provenance.
- `money_weighted_return`, `mwr_annualized`, and `holding_period_return` are percentage points.
- Internal periodic Dietz rate is decimal and multiplied by 100 for output.

## Variable Dictionary
- `BV`: `begin_mv`
- `EV`: `end_mv`
- `CF_sum`: `sum(cash_flows.amount)`
- `Den`: Dietz denominator
- `w_i`: Modified Dietz cash-flow weight for flow `i`
- `Num`: Dietz numerator
- `r_D`: Dietz periodic return (decimal)
- `r_A`: annualized return (decimal)
- `S`: resolved start date (`stateful_input.window_start_date`, explicit `start_date`, or the
  earliest cash-flow date when no start date is supplied)
- `days`: `(as_of - start_date).days`
- `ppy`: annualization factor (`365.25` for `ACT/ACT`, else `365.0`)

## Methodology and Formulas
1. Modified Dietz periodic return:
- `CF_sum = sum_i CF_i`
- `w_i = (as_of - CF_i.date).days / (as_of - S).days`
- `Den = BV + sum_i(CF_i * w_i)`
- `Num = EV - BV - CF_sum`
- `r_D = Num / Den`

2. Simple Dietz periodic return:
- `CF_sum = sum_i CF_i`
- `Den = BV + CF_sum / 2`
- `Num = EV - BV - CF_sum`
- `r_D = Num / Den`

3. Zero denominator handling:
- If `Den == 0`, engine returns `status="NOT_CALCULABLE"`, `reason_codes=["ZERO_DENOMINATOR"]`,
  and note `Calculation resulted in a zero denominator.`

4. Optional annualization:
- If `annualization.enabled` and `days > 0`:
- `scale = ppy / days`
- `r_A = (1 + r_D)^scale - 1`
- Else `mwr_annualized = null`

5. Response mapping:
- `money_weighted_return = 100 * r_D`
- `holding_period_return = 100 * r_D`
- `mwr_annualized = 100 * r_A` when annualized else null
- `is_annualized_primary = false`
- `is_approximation = true`

## Step-by-Step Computation
1. Resolve mode-specific inputs. In stateful mode retrieve lotus-core portfolio timeseries and
   normalize it into `begin_mv`, `end_mv`, signed `cash_flows[]`, and `start_date`.
2. Determine `start_date` from the resolved request; set `end_date = as_of`.
3. Compute `CF_sum` from `cash_flows[]`.
4. Compute `Den` with dated cash-flow weights for `MODIFIED_DIETZ` and midpoint weighting for
   `DIETZ`; if zero, return the not-calculable branch.
5. Compute `Num` and periodic Dietz return `r_D`.
6. If annualization requested and period length positive, compute `r_A`.
7. Return response with `method="MODIFIED_DIETZ"` or `method="DIETZ"` and notes, including
   fallback notes when entering from a failed or ambiguous XIRR attempt.

## Validation and Failure Behavior
- Schema-level validation enforces required inputs.
- Stateful mode rejects missing `stateful_input`, rejects stateless payloads in stateful mode, and
  fails through the retrieval or normalization stage when lotus-core source data cannot produce a
  valid resolved MWR input.
- Source fee rows are preserved as performance drag by the upstream analytics input and are not
  included as investor cash flows; unsupported or invalid source cash-flow rows are skipped during
  normalization rather than guessed.
- Mixed source-currency schedules are not converted by the current Dietz-family path. FX-aware MWR
  remains gated by `docs/technical/mwr-fx-contract-design.md` and must fail closed in any future
  implementation when conversion evidence is incomplete.
- Explicit `MODIFIED_DIETZ` and `DIETZ` requests return `status="CALCULATED"` when the denominator
  is non-zero.
- XIRR fallback responses return `status="FALLBACK_USED"`, include the XIRR failure reason and
  `DIETZ_FALLBACK_USED` in `reason_codes`, set `fallback_from="XIRR"`, set `fallback_reason`, and
  emit `method="MODIFIED_DIETZ"`.
- Zero denominator is non-fatal but not reported as a normal zero return; it returns
  `status="NOT_CALCULABLE"` with `ZERO_DENOMINATOR`.
- If `annualization.enabled=true` and `days<=0`, annualized output remains null.
- Endpoint unexpected failures map to HTTP 500.

## Configuration Options
- `mwr_method`:
  - `MODIFIED_DIETZ` uses dated cash-flow weights.
  - `DIETZ` uses midpoint cash-flow weighting.
  - `XIRR` can route to `MODIFIED_DIETZ` via labeled fallback.
- `annualization.enabled`
- `annualization.basis`

## Outputs
Primary fields:
- `money_weighted_return`
- `mwr_annualized` (optional)
- `holding_period_return`
- `method`
- `status`
- `reason_codes`
- `warnings`
- `fallback_from`
- `fallback_reason`
- `is_annualized_primary`
- `is_approximation`
- `start_date`, `end_date`, `notes`
- `calculation_supportability`, `meta`, `diagnostics`, and `audit`

## Worked Example
Inputs:
- `begin_mv = 100`
- `cash_flows = [{date: 2026-03-01, amount: 10}]`
- `end_mv = 112`
- `start_date = 2026-03-01`
- `as_of = 2026-03-31`
- `annualization.enabled = true`, `basis = ACT/ACT`

Intermediate calculations:

| Quantity | Formula | Value |
|---|---|---:|
| `CF_sum` | `10` | 10.0000 |
| `Den` | `100 + 10/2` | 105.0000 |
| `Num` | `112 - 100 - 10` | 2.0000 |
| `r_D` | `Num / Den` | 0.0190476 |
| `days` | `2026-03-31 - 2026-03-01` | 30 |
| `ppy` | `ACT/ACT` | 365.25 |
| `r_A` | `(1 + r_D)^(365.25/30) - 1` | 0.2582 |

Output mapping:
- `money_weighted_return = 1.90476`
- `holding_period_return = 1.90476`
- `mwr_annualized = 25.82`
- `method = "DIETZ"`
- `status = "CALCULATED"`
- `is_annualized_primary = false`
- `is_approximation = true`
