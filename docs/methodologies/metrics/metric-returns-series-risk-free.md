## Metric
Canonical Risk-Free Return Series (`series.risk_free_returns`)

## Endpoint and Mode Coverage
- Endpoint: `POST /integration/returns/series`
- Inclusion condition: `series_selection.include_risk_free=true`
- Modes:
  - `stateless`: request supplies `risk_free_returns`
  - `stateful`: lotus-core risk-free return series is sourced by reporting currency

## Inputs
- Shared controls: `window`, `frequency`, `data_policy`, `as_of_date`
- Stateless input: `stateless_input.risk_free_returns[]`
- Stateful inputs:
  - `reporting_currency` (required)
  - stateful source request with `series_mode="return_series"`

## Upstream Data Sources
- Stateless: request payload.
- Stateful: `get_risk_free_series(currency, ..., series_mode="return_series")`.

## Unit Conventions
- Risk-free series values are decimal returns.
- Frequency aggregation uses geometric linking in decimal form.

## Variable Dictionary
- `rf_t`: daily risk-free return (decimal)
- `RF_k`: aggregated risk-free return for bucket `k`
- `W`: resolved window

## Methodology and Formulas
1. Normalize risk-free points:
- stateless: from `ReturnPoint`
- stateful: upstream fields (`series_date`, `value`)

2. Filter to window and sort.

3. Resample:
- `DAILY`: unchanged
- `WEEKLY`/`MONTHLY`: `RF_k = prod_{t in k}(1 + rf_t) - 1`

4. Apply optional alignment/fill relative to portfolio date set:
- strict intersection
- forward-fill / zero-fill according to `data_policy.fill_method`

## Step-by-Step Computation
1. Validate request and resolve window.
2. Retrieve risk-free source data (stateless or stateful).
3. Normalize to canonical return points and window-filter.
4. Resample to requested frequency.
5. Apply data-policy alignment/fill.
6. Emit `series.risk_free_returns`.

## Validation and Failure Behavior
- `include_risk_free=true` with missing stateless risk-free input: validation error.
- Stateful mode without `reporting_currency`: HTTP 400.
- Stateful risk-free source not found: HTTP 404.
- Stateful source unavailable: HTTP 503.
- Upstream payload missing points list: HTTP 422 (`CONTRACT_VIOLATION_UPSTREAM`).
- No observations in resolved window: HTTP 422 (`INSUFFICIENT_DATA`).

## Configuration Options
- `series_selection.include_risk_free`
- `reporting_currency` (stateful)
- `window.*`, `frequency`
- `data_policy.missing_data_policy`, `fill_method`, `calendar_policy`

## Outputs
Primary metric field:
- `series.risk_free_returns[]` (`date`, `return_value` decimal)

Diagnostics impact:
- risk-free gaps contribute to `diagnostics.gaps[]`
- fill/alignment policies can change returned points

## Worked Example
Daily risk-free points:

| date | `rf_t` |
|---|---:|
| 2026-02-25 | 0.0001 |
| 2026-02-26 | 0.0001 |
| 2026-02-27 | 0.0001 |

Linked 3-day return:
- `RF = (1.0001^3) - 1 = 0.00030003`

Output mapping:
- `series.risk_free_returns[0].return_value = 0.00030003` (if aggregated into one bucket)
