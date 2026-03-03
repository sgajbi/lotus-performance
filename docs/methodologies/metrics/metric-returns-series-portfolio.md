## Metric
Canonical Portfolio Return Series (`series.portfolio_returns`)

## Endpoint and Mode Coverage
- Endpoint: `POST /integration/returns/series`
- Modes:
  - `input_mode="stateless"`: portfolio returns are request-supplied
  - `input_mode="stateful"`: portfolio valuation timeseries is sourced from lotus-core and converted to daily returns by lotus-performance TWR engine

## Inputs
- Shared request controls:
  - `portfolio_id`, `as_of_date`, `window`, `frequency`, `metric_basis`, `data_policy`
- Stateless path:
  - `stateless_input.portfolio_returns[]` (`date`, `return_value` decimal)
- Stateful path:
  - `stateful_input.consumer_system`
  - upstream `observations[]` with `valuation_date`, `beginning_market_value`, `ending_market_value`, optional `cash_flows[]` (`timing` in `bod|eod`, `amount`)
  - upstream `portfolio_open_date`

## Upstream Data Sources
- Stateless: caller payload only.
- Stateful: lotus-core portfolio analytics timeseries via `CoreIntegrationService.get_portfolio_analytics_timeseries`.

## Unit Conventions
- Output return points are decimals, not percentage points (`0.0012 = 12 bps`).
- Stateful conversion computes TWR daily return in pp first, then divides by 100 into decimal output contract.

## Variable Dictionary
- `r_t`: daily portfolio return in decimal output form
- `r_t_pp`: daily portfolio return in pp from engine (`daily_ror`)
- `W`: resolved date window `[start_date, end_date]`
- `f`: requested frequency (`DAILY|WEEKLY|MONTHLY`)
- `R_k`: aggregated return for bucket `k`

## Methodology and Formulas
1. Window resolution:
- explicit mode: use `window.from_date` to `window.to_date`
- relative mode: derive start from `as_of_date` and `window.period`

2. Stateless portfolio series normalization:
- require non-empty list
- reject duplicate dates
- sort by date and filter to `W`

3. Stateful portfolio series derivation:
- normalize valuation observations to internal valuation points (`begin_mv`, `end_mv`, `bod_cf`, `eod_cf`)
- run daily TWR engine (`metric_basis` respected)
- map `daily_ror` pp to decimal: `r_t = r_t_pp / 100`
- filter/sort into `W`

4. Frequency aggregation:
- `DAILY`: no aggregation
- `WEEKLY` (`W-FRI`) and `MONTHLY` (`ME`):
- `R_k = prod_{t in bucket k}(1 + r_t) - 1`

## Step-by-Step Computation
1. Validate request contract and resolve window.
2. Build portfolio DataFrame from stateless points or stateful upstream observations.
3. Filter observations to resolved window.
4. Resample to requested frequency using geometric linking when needed.
5. Apply missing-data and fill policy interactions with optional benchmark/risk-free series.
6. Compute coverage and gap diagnostics.
7. Emit `series.portfolio_returns` in decimal format.

## Validation and Failure Behavior
- Empty/duplicate portfolio series (stateless): HTTP 422/400.
- No rows in resolved window: HTTP 422 (`INSUFFICIENT_DATA`).
- Stateful upstream unavailable: HTTP 503 (`SOURCE_UNAVAILABLE`).
- Stateful upstream returns no valid observations or invalid `portfolio_open_date`: HTTP 422.
- `FAIL_FAST` missing-data policy with missing required points: HTTP 422.
- `STRICT_INTERSECTION` with no overlap across selected series: HTTP 422.

## Configuration Options
- `window.mode`, `window.period`, `window.from_date`, `window.to_date`, `window.year`
- `frequency`
- `metric_basis` (stateful path daily return derivation)
- `data_policy.missing_data_policy`
- `data_policy.fill_method`
- `data_policy.calendar_policy`
- `input_mode` with `stateless_input` / `stateful_input`

## Outputs
Primary metric field:
- `series.portfolio_returns[]` (`date`, `return_value` decimal)

Supporting diagnostics:
- `diagnostics.coverage.*`
- `diagnostics.gaps[]`
- `diagnostics.policy_applied`

## Worked Example
Stateless input (`frequency=WEEKLY`):

| date | daily return `r_t` |
|---|---:|
| 2026-02-23 | 0.0100 |
| 2026-02-24 | 0.0050 |
| 2026-02-25 | -0.0025 |
| 2026-02-26 | 0.0030 |
| 2026-02-27 | 0.0015 |

Weekly bucket return:
- `R_week = (1.01 * 1.005 * 0.9975 * 1.003 * 1.0015) - 1 = 0.017063`

Output mapping:
- `series.portfolio_returns[0].date = 2026-02-27`
- `series.portfolio_returns[0].return_value = 0.017063`
