## Metric
Composite Time-Weighted Return (`cumulative_return` and `periods[].return_value`)

## Endpoint and Mode Coverage
- Endpoint: `POST /performance/composites/twr`
- Inspector endpoint: `POST /performance/composites/inspect`
- Implemented mode: persisted member-return facts only
- Methodology identifier: `persisted_member_return_asset_weighted_twr_v1`
- Current calculation method: `ASSET_WEIGHTED`
- Current return views: `GROSS`, `NET_ACTUAL`, and `NET_MODEL_FEE`, with one return view per
  composite result
- Current reporting-currency policy: one reporting currency per calculable period
- Current storage posture: composite definitions, memberships, and member-return facts are stored in
  the composite metadata store; the calculator consumes already-materialized facts and does not run
  hidden request-time portfolio TWR fan-out

## Inputs
- `CompositeDefinition.composite_id`
- `CompositeDefinition.reporting_currency`
- `CompositeDefinition.calculation_method`
- `CompositeDefinition.source_authority`
- `CompositeMemberReturnFact.composite_id`
- `CompositeMemberReturnFact.portfolio_id`
- `CompositeMemberReturnFact.period_start`
- `CompositeMemberReturnFact.period_end`
- `CompositeMemberReturnFact.return_value`
- `CompositeMemberReturnFact.return_view`
- `CompositeMemberReturnFact.beginning_market_value`
- `CompositeMemberReturnFact.ending_market_value`
- `CompositeMemberReturnFact.reporting_currency`
- `CompositeMemberReturnFact.calculation_id`
- `CompositeMemberReturnFact.source_snapshot_id`
- `CompositeMemberReturnFact.source_fingerprint`
- `CompositeMemberReturnFact.restatement_version`
- `CompositeMemberReturnFact.status`
- `CompositeMemberReturnFact.reason_codes`
- Request window: `period_start` and `period_end`

## Upstream Data Sources
- `lotus-manage` owns composite definitions and effective-dated composite membership policy.
- `lotus-performance` owns the persisted member-return facts used by the composite calculator.
- `lotus-core` owns the source asset and portfolio valuation facts used upstream to produce member
  portfolio returns and beginning/ending market values.
- Benchmark assignment is recorded as a source-authority field, but benchmark active-return
  calculation is not part of the current composite TWR endpoint.
- The current endpoint reads persisted member-return facts from the composite metadata store. It
  intentionally does not calculate portfolio member returns on the fly, because composite audit,
  restatement, and support workflows require stable source fingerprints and restatement versions.

## Unit Conventions
- Return values are decimal ratios. Example: `0.0125` means `1.25%`.
- Beginning and ending market values are monetary amounts in the member fact reporting currency.
- `beginning_asset_weight` is a decimal ratio. Example: `0.25` means `25%`.
- `contribution` is a decimal ratio equal to `return_value * beginning_asset_weight`.
- `dispersion_equal_weight` is a decimal ratio sample standard deviation of ready member returns.
- The engine quantizes returns, weights, contributions, cumulative returns, and dispersion to
  `0.000000000001`.
- The engine quantizes composite beginning and ending market values to `0.000001`.

## Variable Dictionary
- `C`: requested composite identifier
- `p`: one composite calculation period
- `i`: one member portfolio with a persisted member-return fact for period `p`
- `F_p`: all persisted member-return facts for composite `C` in period `p`
- `R_p`: ready member-return facts in `F_p`
- `E_p`: non-ready member-return facts in `F_p`
- `B_i,p`: member beginning market value
- `E_i,p`: member ending market value
- `r_i,p`: persisted member return in decimal ratio
- `w_i,p`: member beginning-asset weight
- `c_i,p`: member contribution to composite period return
- `R_C,p`: asset-weighted composite period return
- `G_k`: cumulative growth factor through the `k`th calculable period
- `CR_k`: cumulative composite return through the `k`th calculable period
- `n_p`: ready member count for period `p`
- `s_p`: equal-weight sample standard deviation of ready member returns
- `view_p`: shared return view among ready facts for period `p`
- `ccy_p`: shared reporting currency among ready facts for period `p`

## Methodology and Formulas
1. Ready member fact filter:
- `R_p = { fact in F_p where fact.status == READY }`
- `E_p = { fact in F_p where fact.status != READY }`

2. Beginning and ending composite assets:
- `B_C,p = sum_i(B_i,p for i in R_p)`
- `E_C,p = sum_i(E_i,p for i in R_p)`

3. Beginning-asset weight:
- `w_i,p = B_i,p / B_C,p`

4. Member contribution:
- `c_i,p = r_i,p * w_i,p`

5. Composite period return:
- `R_C,p = sum_i(c_i,p for i in R_p)`

6. Geometric linking:
- For each calculable period in date order, `G_k = G_(k-1) * (1 + R_C,p)`
- Initial `G_0 = 1`
- `CR_k = G_k - 1`
- Blocked periods do not change `G_k` and do not fabricate a zero return.

7. Equal-weight dispersion:
- If `n_p < 2`, `s_p = null`
- If `n_p >= 2`, `mean_p = sum_i(r_i,p) / n_p`
- `s_p = sqrt(sum_i((r_i,p - mean_p)^2) / (n_p - 1))`

8. Calculation status:
- Period status is `READY` when all period facts are ready and all validation guards pass.
- Period status is `DEGRADED` when at least one ready fact can calculate and at least one non-ready
  fact is excluded.
- Period status is `BLOCKED` when no ready fact is available, beginning assets are not positive, or
  ready facts mix return views or reporting currencies.
- Calculation status is `READY` when every period is ready, `DEGRADED` when at least one period is
  ready or degraded and not every period is ready, and `BLOCKED` when no period can calculate.

## Step-by-Step Computation
1. Validate `CompositeTWRRequest.period_end >= period_start`.
2. Look up the composite definition by `composite_id`; return 404 if not found.
3. Read persisted member-return facts where `period_start` and `period_end` fall inside the request
   window.
4. Group facts by `(period_start, period_end)` and sort periods ascending.
5. For each period, split ready facts from non-ready facts.
6. If there are no ready facts, emit a blocked period with reason
   `no_ready_member_return_facts` or the upstream non-ready reason codes.
7. Sum beginning and ending market values across ready facts.
8. If beginning market value is less than or equal to zero, emit a blocked period with reason
   `nonpositive_composite_beginning_assets`.
9. If ready facts contain multiple `return_view` values, emit a blocked period with reason
   `mixed_member_return_views`.
10. If ready facts contain multiple `reporting_currency` values, emit a blocked period with reason
   `mixed_member_reporting_currencies`.
11. Sort ready facts by `portfolio_id`, calculate beginning-asset weights and member
    contributions, and emit `member_contributions[]`.
12. Calculate period return, cumulative return, dispersion, included source fingerprints,
    restatement versions, ready member count, excluded member count, and period reason codes.
13. Return calculation-level status, terminal cumulative return from the latest calculable period,
    period evidence, methodology identifier, and aggregate reason codes.

## Validation and Failure Behavior
- Request period with `period_end < period_start`: HTTP 422 request validation error.
- Missing composite definition: HTTP 404 with `COMPOSITE_DEFINITION_NOT_FOUND`.
- No persisted member-return facts in the requested window: HTTP 422 with
  `NO_MEMBER_RETURN_FACTS`; the service does not return a fake zero composite return.
- Non-ready member facts must carry `reason_codes`.
- No ready facts in a period: blocked period; calculation is blocked unless another period can
  calculate.
- Nonpositive ready beginning assets: blocked period with
  `nonpositive_composite_beginning_assets`.
- Mixed return views among ready facts: blocked period with `mixed_member_return_views`.
- Mixed reporting currencies among ready facts: blocked period with
  `mixed_member_reporting_currencies`.
- One ready member: period return equals that member return; `dispersion_equal_weight=null`.
- Inactive or blocked gaps do not erase later calculable history; later periods can still carry the
  geometric cumulative return from calculable periods.
- Restated facts replace the previous composite, portfolio, and period fact in the metadata store;
  the emitted response carries the used `source_fingerprint`, `restatement_version`, and
  `calculation_id`.

## Configuration Options
- `calculation_id`: caller-provided or generated UUID for support and idempotency correlation.
- `composite_id`: composite to calculate.
- `period_start` and `period_end`: inclusive persisted fact window.
- The calculation method, source authority, reporting currency, and membership policy are
  source-owned composite metadata, not ad hoc request switches.
- Gross, net actual, and model-fee returns are represented by separate persisted member-return
  facts and must not be mixed in one calculated result.
- Significant cash-flow, minimum asset, grace-period, termination, and manual override policies are
  source-authority decisions upstream of the persisted member-return fact. The current calculator
  consumes materialized facts and reports their status and reason codes.
- Advanced analytics such as composite contribution, attribution, MWR, sleeves, carve-outs, and
  special structures are outside this methodology.

## Outputs
Primary response fields:
- `calculation_id`
- `composite_id`
- `status`
- `period_start`
- `period_end`
- `cumulative_return`
- `reason_codes`
- `methodology`
- `periods[]`

Period evidence fields:
- `periods[].status`
- `periods[].return_value`
- `periods[].cumulative_return`
- `periods[].beginning_market_value`
- `periods[].ending_market_value`
- `periods[].member_count`
- `periods[].excluded_member_count`
- `periods[].dispersion_equal_weight`
- `periods[].return_view`
- `periods[].reporting_currency`
- `periods[].source_fingerprints`
- `periods[].restatement_versions`
- `periods[].reason_codes`
- `periods[].member_contributions[]`

Member evidence fields:
- `member_contributions[].portfolio_id`
- `member_contributions[].return_value`
- `member_contributions[].beginning_market_value`
- `member_contributions[].beginning_asset_weight`
- `member_contributions[].contribution`
- `member_contributions[].source_snapshot_id`
- `member_contributions[].source_fingerprint`
- `member_contributions[].restatement_version`
- `member_contributions[].calculation_id`

Inspector fields:
- `verdict`
- `findings[]`
- `evidence_summary`
- `artifacts[]`, including `member_inputs.csv`, `period_weights.csv`, `composite_returns.csv`,
  `lineage_manifest.json`, and `support_brief.md`

## Worked Example
Two-member, two-period asset-weighted composite:

| period | member | `B_i,p` | `r_i,p` | `w_i,p` | `c_i,p = r_i,p * w_i,p` |
|---|---:|---:|---:|---:|---:|
| 2026-01 | A | 100.00 | 0.010000 | 0.250000 | 0.002500 |
| 2026-01 | B | 300.00 | 0.020000 | 0.750000 | 0.015000 |
| 2026-02 | A | 110.00 | -0.010000 | 0.250000 | -0.002500 |
| 2026-02 | B | 330.00 | 0.030000 | 0.750000 | 0.022500 |

Aggregation:
- January period return: `R_C,Jan = 0.002500 + 0.015000 = 0.017500`
- February period return: `R_C,Feb = -0.002500 + 0.022500 = 0.020000`
- Cumulative return after January: `(1 + 0.017500) - 1 = 0.017500`
- Cumulative return after February: `(1.017500 * 1.020000) - 1 = 0.037850`
- January dispersion uses sample standard deviation of `[0.010000, 0.020000]`:
  `0.007071067812`

Output mapping:
- `periods[0].return_value = 0.017500000000`
- `periods[0].cumulative_return = 0.017500000000`
- `periods[0].member_contributions[0].beginning_asset_weight = 0.250000000000`
- `periods[0].member_contributions[1].contribution = 0.015000000000`
- `periods[0].dispersion_equal_weight = 0.007071067812`
- `periods[1].return_value = 0.020000000000`
- `cumulative_return = 0.037850000000`
