# Contribution Guide

`POST /performance/contribution` decomposes portfolio return into position-level or hierarchy-level
contributors.

## Current request contract

The current request shape is:

- `input_mode: "stateless" | "stateful"`
- `portfolio_id`
- `report_start_date`
- `report_end_date`
- `analyses`
- stateless:
  - legacy top-level `portfolio_data`
  - legacy top-level `positions_data`
  - or `stateless_input.portfolio_data`
  - or `stateless_input.positions_data`
- stateful:
  - `stateful_input`
  - optional `stateful_input.metric_basis`
  - optional `stateful_input.dimensions`
  - optional `stateful_input.include_cash_flows`
  - optional `stateful_input.filters`

The stateful envelope is intentionally lightweight. lotus-performance stamps the
source consumer identity server-side instead of requiring an explicit consumer field.

Optional controls include:

- `hierarchy`
- `weighting_scheme`
- `smoothing`
- `emit`
- `lookthrough` compatibility fields
- multi-currency controls

Inside the current contract:

- stateless `portfolio_data` contains `metric_basis` and `valuation_points`
- each stateless entry in `positions_data` contains `position_id`, optional `meta`, and `valuation_points`
- stateful mode sources canonical portfolio and position timeseries from lotus-core and normalizes them into the same stateless engine inputs used by direct requests
- stateful position rows preserve the source position grain through `source_position_key`; when
  lotus-core supplies account, custody, book, sleeve, strategy, mandate, or tax-lot discriminators,
  Lotus treats those rows as distinct engine positions while preserving the original
  `position_id` as `business_position_id` metadata
- stateful mode preserves source-economics posture in `source_economics_evidence`, including
  source contracts, cash-flow type counts, available economics, unsupported component-P&L families,
  and upstream snapshot posture
- stateful mode consumes `lotus-core:PerformanceComponentEconomics:v1` when available to enrich
  source-economics evidence for source-authored cashflow, fee, income, tax, realized P&L, and
  FX-context component families without moving contribution methodology out of `lotus-performance`
- stateful `currency_mode="BOTH"` requires `report_ccy`, source position currencies, and
  `fx.rates` when any sourced position currency differs from `report_ccy`; missing FX coverage is
  rejected with HTTP `422` before contribution calculation starts
- `lookthrough` is accepted as a compatibility request block only; lotus-performance does not
  decompose fund or structured-product holdings and expects lotus-core to provide already-visible
  position rows for the requested scope

Older examples using nested `daily_data` or request-level `period_type` are not current.

Key `emit` controls:

- `timeseries=true` returns the residual-adjusted daily total contribution ladder
- `by_position_timeseries=true` returns residual-adjusted daily contribution ladders for each
  position
- `top_n_per_level` limits explicit hierarchy rows per level
- `threshold_weight` rolls small hierarchy rows into `Other` when `include_other=true`
- `include_unclassified=true` keeps rows with missing hierarchy metadata under `Unclassified`

When `hierarchy` is supplied, hierarchy level output remains enabled for existing clients even if
`emit.by_level` is omitted. The hierarchy rows are built from the same residual-adjusted daily
position contribution series used for position output, so position rows, daily series, and hierarchy
rows tell the same contribution story. In reset-aware average-weight rollout mode, hierarchy
`levels[].rows[].weight_avg` uses the same selected denominator as
`position_contributions[].average_weight`.

## Async execution

Contribution can run synchronously or asynchronously.

Stateful and stateless requests follow the same execution pattern. The endpoint stays synchronous
for smaller stateless sets and smaller stateful windows, and returns `202 Accepted` when the
workload is offloaded to the compute executor.

When the request is offloaded, the API returns `202 Accepted` with:

- `calculation_id`
- `poll_path`
- `result_path`

Use:

- `GET /performance/executions/{calculation_id}`
- `GET /performance/contribution/results/{calculation_id}`

## Core methodology

### 1. Position return and weight

For each position and day, the engine computes:

- position return
- position weight relative to the total portfolio under the selected weighting scheme

### 2. Single-period contribution

Daily raw contribution is the position weight multiplied by position return.

### 3. Multi-period linking

The default smoothing method is `CARINO`, which is used so that multi-period contribution results
reconcile to the total geometric portfolio return.

For a valid linked return path, Lotus applies the industry Carino factor directly to raw daily
contribution:

- `k_t = log1p(R_P,t) / R_P,t`
- `K = log1p(R_P) / R_P`
- `F_t = k_t / K`
- `smoothed_contribution_i,t = raw_contribution_i,t * F_t`

This matters because raw arithmetic contribution can sum to a different value from linked portfolio
return. For example, `+10%` followed by `-10%` sums to `0%` arithmetically, but geometrically links
to `-1%`; Carino maps the raw daily contributions to that linked return when the logarithmic domain
is valid.

### 4. Hierarchical aggregation

When `hierarchy` is supplied, the engine aggregates bottom-up from the most granular rows to each
parent level so that every level reconciles to its parent and ultimately to total portfolio return.
This is still a per-period calculation: when `analyses` requests multiple resolved periods, the API
returns one hierarchy result under each `results_by_period.<period>` key.

### 5. Residual and event consistency

Residual handling and event treatment are aligned with the underlying portfolio return engine:

- no-investment periods do not create artificial contribution
- reset behavior remains consistent with portfolio-level return logic
- small residuals are tracked and distributed so the final result reconciles
- in `currency_mode="BOTH"`, residual allocation preserves the invariant that local contribution
  plus FX contribution reconciles to total contribution; when the pre-allocation contribution
  denominator is zero or effectively zero, the residual split falls back to absolute local/FX
  component activity rather than silently leaving the decomposition unreconciled

### 6. Average-weight methodology characterization

By default, public `average_weight` output uses the simple arithmetic mean of `daily_weight` across
the period slice. When `CONTRIBUTION_RESET_AWARE_AVERAGE_WEIGHT_MODE=CANDIDATE_PERIODS`, clean
cutover-candidate periods promote the reset-aware denominator into emitted
`position_contributions[].average_weight` and hierarchy `levels[].rows[].weight_avg`.

At the same time, the service now computes a reset-aware shadow denominator for characterization:

- pre-final-active-reset history is excluded
- post-reset no-investment days do not count as valid invested days
- missing position rows on valid portfolio days are treated as zero weight rather than shrinking the
  denominator

When a period is not promoted, the shadow method remains characterization evidence. The response can
surface:

- diagnostic notes when the reset-aware shadow differs from the active `average_weight`
- audit counts for how many position-period rows would change under the reset-aware denominator
- audit counts for whether position-level reset days and portfolio-level reset days diverge

This keeps default contribution behavior stable while allowing explicitly controlled promotion for
periods whose residual, flow-balance, reset-alignment, and emitted-series checks are clean.

Current working decision:

- keep the simple mean active by default
- promote the reset-aware denominator only in `CANDIDATE_PERIODS` mode and only for clean candidate
  periods
- use the shadow delta note and audit count to identify where a future cutover would actually
  change the contribution story

Grouped-return alignment is also still under characterization:

- contribution now records when portfolio reset days and position reset days do not line up
- that does not change contribution output yet, but it gives us evidence for the later
  grouped-return alignment slice

### 7. Carino validity guardrail

The current contribution engine still offers `CARINO` smoothing, but it now applies a domain
guardrail before using the logarithmic adjustment.

Business meaning:

- Carino relies on `log(1 + r)`
- that is only defined while each linked portfolio gross return factor remains positive
- once a reset-heavy day reaches `-100%` return or worse, Carino is no longer a valid smoothing
  model for that episode

Current behavior:

- healthy paths continue to use Carino smoothing
- broken-capital paths fall back to raw daily contribution arithmetic for the affected slice
- the response surfaces this through:
  - `audit.counts.carino_invalid_domain_days`
  - a diagnostics note explaining that logarithmic smoothing was not valid on those days

The reset-heavy contribution path now has three aligned layers:

- reset-day alignment between portfolio and position engines
- reset-aware top-line period return taken from the portfolio engine
- residual-adjusted emitted daily series that sum to the same period total

The response keeps `audit.counts.timeseries_total_delta_periods` so we can detect any future slice
where emitted daily series drift away from the residual-adjusted period result again.

In richer multi-position reset-heavy stories, the current characterized behavior is:

- top-line contribution still ties to TWR
- emitted daily series still tie to the residual-adjusted period total
- reset alignment stays visible through the existing reset-day counters
- the most important remaining methodology signal tends to move to
  `average_weight_shadow_delta_positions`, which tells us where the simple active average-weight
  method and the reset-aware shadow denominator still disagree across positions

The audit block now also quantifies the size of that disagreement:

- `average_weight_shadow_delta_max_bp`: largest single-position shadow delta in basis points
- `average_weight_shadow_delta_sum_bp`: sum of absolute shadow deltas across impacted positions
- `average_weight_shadow_noise_periods`: reporting periods where shadow drift exists but stays at
  `<= 100 bp`
- `average_weight_shadow_warning_periods`: reporting periods where shadow drift is between `101`
  and `499 bp`
- `average_weight_shadow_material_periods`: reporting periods where shadow drift reaches `>= 500 bp`
- `average_weight_shadow_cutover_candidate_periods`: material-shadow periods where the surrounding
  bookkeeping signals are otherwise clean enough that future denominator promotion is plausible
- `average_weight_shadow_promotion_ready_rate_bp`: share of material-shadow periods that are
  currently promotion-ready, expressed in basis points of the material-shadow population
- `average_weight_shadow_promoted_periods`: periods where the controlled rollout actually promoted
  the reset-aware denominator into emitted position `average_weight` and hierarchy `weight_avg`
  output
- `average_weight_shadow_blocked_periods`: material-shadow periods that stayed shadow-only because
  one or more rollout guardrails were not yet clean
- `average_weight_shadow_blocked_by_weight_residual_periods`: material-shadow periods that stayed
  shadow-only because emitted position weights did not sum cleanly to 100%
- `average_weight_shadow_blocked_by_flow_balance_periods`: material-shadow periods that stayed
  shadow-only because the scoped position set was not flow-neutral
- `average_weight_shadow_blocked_by_reset_alignment_periods`: material-shadow periods that stayed
  shadow-only because portfolio and position reset boundaries were not aligned
- `average_weight_shadow_blocked_by_timeseries_delta_periods`: material-shadow periods that stayed
  shadow-only because emitted daily series still drifted from the residual-adjusted period total
- `average_weight_sum_residual_bp`: residual basis-point gap between the emitted position average
  weights and a full 100% total
- `position_flow_residual_days`: count of dates where summed position-level cash flows fail to net
  to zero
- `position_flow_residual_max_bp`: largest single-day position-flow residual measured against the
  portfolio capital base for that date
- `position_flow_residual_sum_bp`: sum of those daily flow-residual magnitudes across the reporting
  slice

Each resolved period now also includes a compact response block at:

- `results_by_period.<period>.smoothing_evidence`

Use this block when explaining raw versus linked contribution:

- `smoothing_method`: requested method, such as `CARINO` or `NONE`
- `status`: resolved posture, such as `APPLIED`, `NOT_REQUESTED`, or
  `INVALID_DOMAIN_FALLBACK`
- `reason_codes`: machine-readable status and residual reasons
- `linked_return`: source portfolio linked return in percentage-point units
- `raw_contribution`: raw daily contribution sum before smoothing in percentage-point units
- `smoothed_contribution`: smoothed contribution sum before residual allocation in
  percentage-point units
- `final_contribution`: final period contribution after any residual allocation in
  percentage-point units
- `raw_residual`: linked return minus raw contribution
- `smoothing_residual`: linked return minus smoothed contribution before residual allocation
- `post_allocation_residual`: linked return minus final contribution
- `residual_allocation_applied` and `residual_allocation_basis`: whether and how final residual
  allocation was needed
- `carino_factor_min` and `carino_factor_max`: factor range when Carino factor evidence exists
- `invalid_domain_days`: count of days where Carino was not mathematically valid

This is the first place support teams should look before recomputing contribution internals.

The top-level response also includes:

- `source_economics_evidence`

Use this block to understand what the contribution result was actually sourced from:

- `source_owner`: `lotus-core` for stateful analytics inputs, `caller` for stateless payloads
- `status`: `SOURCE_BACKED`, `SOURCE_LIMITED`, or `CALLER_SUPPLIED`
- `source_contracts`: source contracts used, such as `PortfolioTimeseriesInput:v1` and
  `PositionTimeseriesInput:v1`; stateful contribution also includes
  `PerformanceComponentEconomics:v1` when the Core component-economics source product was
  retrieved for evidence enrichment
- `available_economics`: source-backed inputs such as market values, external flows, internal
  trade flows, fees, FX rates, classification dimensions, and observed
  `PerformanceComponentEconomics:v1` component families such as source component income, fees,
  tax, realized capital P&L, realized FX P&L, realized total P&L, cashflows, and FX context
- `unsupported_economics`: component-P&L families that are not source-authored in the current
  contract; observed `PerformanceComponentEconomics:v1` fee, income, and tax families remove the
  corresponding `fee_pnl`, `income_pnl`, and `tax_pnl` unsupported flags only when every requested
  Core component-economics chunk is `READY`, while broader price, FX attribution,
  corporate-action, derivative, cash, and residual P&L buckets remain unsupported unless a precise
  source contract supplies them
- `degraded_economics`: degraded signals such as unsupported source cash-flow types, missing
  classification, unavailable or partial component-economics enrichment, or execution-only upstream
  snapshot lineage
- `cash_flow_type_counts`: source cash-flow labels observed on stateful position rows
- `source_snapshot_count` and `source_snapshot_endpoints`: execution-registry lineage coverage

Lotus does not guess unavailable income, tax, FX P&L, corporate-action, derivative, loan, cash, or
liability economics. Core-authored component evidence is consumed when
`PerformanceComponentEconomics:v1` publishes it, but Lotus still avoids overclaiming broader P&L or
attribution buckets that the source product does not explicitly support.

## Source-Document Edge Semantics

RFC-047 adds implementation-backed QA coverage for contribution economics that commonly create
front-office and audit confusion:

- external deposits and withdrawals are cash-flow events, not portfolio performance;
- balanced internal trade flows do not become portfolio external flow;
- income can remain assigned to the generating asset when source metadata supplies `income_pnl`;
- net fee drag can be represented through an explicit fee bucket when source metadata supplies
  `fee_pnl`;
- missing hierarchy classification is emitted as `Unclassified` rather than dropped or guessed;
- short positions preserve signed average weight and inverse contribution sign behavior;
- hierarchy rows, position rows, daily totals, and by-position series reconcile to the
  source-owned period total.

These semantics are product behavior, not documentation examples. They are covered by
`tests/integration/test_contribution_api.py` and `tests/e2e/test_workflow_journeys.py` and are
summarized for product audiences in `wiki/Contribution-Analytics.md`.

- `results_by_period.<period>.average_weight_methodology_status`

This per-period block summarizes:

- `status`: `NO_MATERIAL_SHADOW`, `PROMOTION_READY`, `PROMOTED`, `BLOCKED`, or `UNDER_REVIEW`
- `max_shadow_delta_bp`
- `is_material_shadow`
- `is_cutover_candidate`
- `is_promoted`
- `blocker_reason_codes`

This is the fastest way to understand the rollout state for one specific period without rebuilding
it from aggregate audit counters.

That helps separate:

- small methodology noise
- from cases where the active average-weight output is materially understating the economics of the
  reset-heavy episode

Suggested interpretation for average-weight shadow pressure:

- `average_weight_shadow_delta_max_bp <= 100`: keep as characterization noise unless it repeats in
  an important workflow
- `average_weight_shadow_delta_max_bp` between `101` and `499`: treat as meaningful methodology
  pressure that still needs more scenario evidence before cutover
- `average_weight_shadow_delta_max_bp >= 500`: treat as material evidence that the active
  `average_weight` output may be under-describing the economic story after resets or NIP days
- large `average_weight_shadow_delta_sum_bp` with a smaller single-position max usually means the
  active methodology is drifting across several positions, not just one obvious outlier
- when `average_weight_shadow_cutover_candidate_periods > 0`, the response now also emits a plain
  diagnostics note calling those periods out as strong candidates for a future denominator cutover
  study
- when one of the `average_weight_shadow_blocked_by_*_periods` counters is non-zero, the service is
  saying the shadow delta may be real but the slice is still not clean enough for rollout because
  another bookkeeping invariant is failing
- `average_weight_shadow_blocked_periods` is the union count for those blocked slices; the
  per-reason `average_weight_shadow_blocked_by_*_periods` counters explain which guardrails failed
- `average_weight_shadow_promotion_ready_rate_bp` is the compact rollout summary: `10000` means
  every observed material-shadow period is currently promotion-ready, while `0` means none of them
  are
- a controlled runtime rollout mode now exists for future adoption work:
  `CONTRIBUTION_RESET_AWARE_AVERAGE_WEIGHT_MODE=CANDIDATE_PERIODS`
- the default remains `OFF`, so current clients keep the existing active mean-weight output unless
  that rollout mode is deliberately enabled

Current rollout reading:

- `average_weight_shadow_cutover_candidate_periods > 0` and `average_weight_shadow_blocked_periods = 0`
  means the slice is analytically clean enough for controlled promotion
- `average_weight_shadow_blocked_periods > 0` means keep the slice shadow-only even if the shadow
  delta is material
- `average_weight_shadow_promoted_periods > 0` means the runtime rollout mode actually changed the
  emitted `average_weight` output for those clean candidate periods
- blocker reasons should be read as rollout stop-signs, not as optional warnings:
  weight residual and flow-balance blockers are strongest because they undermine the integrity of
  the economic story for the current scoped slice, while reset-alignment and timeseries-delta
  blockers mean the bookkeeping still is not clean enough to treat the denominator change as
  isolated

Rollout-status examples:

- Fully ready material traffic:
  - `average_weight_shadow_material_periods = 3`
  - `average_weight_shadow_cutover_candidate_periods = 3`
  - `average_weight_shadow_blocked_periods = 0`
  - `average_weight_shadow_promotion_ready_rate_bp = 10000`
  - reading: every observed material-shadow period is analytically clean enough for controlled
    promotion

- Fully blocked material traffic:
  - `average_weight_shadow_material_periods = 2`
  - `average_weight_shadow_cutover_candidate_periods = 0`
  - `average_weight_shadow_blocked_periods = 2`
  - `average_weight_shadow_blocked_by_flow_balance_periods = 2`
  - `average_weight_shadow_promotion_ready_rate_bp = 0`
  - reading: denominator pressure may be real, but none of the material slices are safe to promote
    until we understand or fence the non-flow-neutral scoped slices

- Mixed traffic:
  - `average_weight_shadow_material_periods = 5`
  - `average_weight_shadow_cutover_candidate_periods = 2`
  - `average_weight_shadow_blocked_periods = 3`
  - `average_weight_shadow_blocked_by_reset_alignment_periods = 2`
  - `average_weight_shadow_blocked_by_timeseries_delta_periods = 1`
  - `average_weight_shadow_promotion_ready_rate_bp = 4000`
  - reading: some material slices are rollout-ready, but the blocker mix is still too large to
    justify a broader default cutover

Rollout-readiness report artifact:

- `python scripts/contribution_rollout_readiness_report.py <response-a.json> <response-b.json>`
- default output:
  - `artifacts/contribution-rollout-readiness/latest.json`

The report aggregates per-period `average_weight_methodology_status` blocks across saved
contribution response payloads and emits:

- total material periods
- promotion-ready periods
- promoted periods
- blocked periods
- blocked economic-integrity periods
- blocked methodology-guardrail periods
- blocker-reason counts
- blocker-category counts
- `promotion_ready_rate_bp`
- a top-level recommendation such as:
  - `READY_FOR_CONTROLLED_ROLLOUT`
  - `HOLD_BLOCKERS_PRESENT`
  - `MIXED_READYNESS_KEEP_CANDIDATE_ONLY`
- `KEEP_SHADOW_ONLY_GATHER_MORE_EVIDENCE`

Seeded artifact generator:

- `python scripts/generate_seeded_contribution_rollout_artifacts.py`
- default output:
  - `artifacts/contribution-rollout-readiness/seeded/`

This seeded bundle currently writes:

- `no_material_shadow.json`
- `ready_candidate_shadow_only.json`
- `promoted_candidate.json`
- `blocked_flow_balance.json`
- `blocked_reset_alignment.json`
- `latest.json`

It is meant as a deterministic local validation pack for rollout review, not as production traffic
evidence.

Rollout decision checker:

- `python scripts/contribution_rollout_decision_check.py --report artifacts/contribution-rollout-readiness/seeded/latest.json`

Current decision policy:

- return `READY` only when:
  - material periods exist
  - no `weight_residual` or `flow_balance` blockers are present
  - no blocked material periods remain
  - `promotion_ready_rate_bp` meets the configured threshold
- otherwise return `HOLD`

The decision checker now also classifies the hold reason:

- `insufficient_evidence`
- `economic_integrity`
- `methodology_guardrail`
- `blocked_periods`
- `below_threshold`

When more than one blocker family is present, the checker now also emits
`secondary_hold_categories` so rollout review can see the full stack without losing the primary
decision reason.

The checker also emits `recommended_next_action` so the decision artifact can be used directly in
rollout review without translating categories into follow-up steps by hand.

The checker is a governance tool. It does not change engine behavior; it only turns the readiness
artifact into an explicit rollout decision.

Current practical rollout posture:

- reset-aware `average_weight` infrastructure is implemented
- controlled promotion for clean candidate periods is implemented
- seeded rollout governance currently still returns `HOLD`
- broader rollout therefore remains a policy decision pending more non-prod evidence, not a missing
  code-path problem

Useful reading shortcut:

- `blocked_economic_periods` tells us how many blocked slices are stopped by weight/flow integrity
  problems
- `blocked_methodology_periods` tells us how many blocked slices are stopped by reset-alignment or
  timeseries-reconciliation guardrails
- that split makes it easier to see whether rollout is mostly waiting on economic integrity or on
  methodology cleanup

Current expectation:

- emitted position average weights should sum to 100%
- a non-zero `average_weight_sum_residual_bp` should be very small and treated as residual drift to
  explain, not as a normal state
- position-level internal cash flows should net to zero across the set of positions for a period;
  the stock leg and the cash leg of an internal rebalance should cancel each other across positions.
  If they do not, the current scoped slice is carrying net flow pressure rather than a fully
  self-cancelling internal reallocation story, and it increases the risk that summed position
  contribution will stop telling the same story as portfolio return

Example:

- if one position has `bod_cf = -100` and another has `bod_cf = +100` on the same date, that is a
  balanced internal reallocation: the stock leg and cash leg cancel inside the visible scope, so
  `position_flow_residual_days` should stay at `0`
- if the same book reports `-100` on one position and only `+90` on the offsetting leg, the
  residual `10` means the visible scope is not fully flow-neutral on that date, so it should be
  surfaced rather than silently treated as normal

Suggested interpretation:

- `position_flow_residual_max_bp <= 1`: treat as rounding dust unless it persists across many dates
- `position_flow_residual_max_bp` between `2` and `10`: interpret as a mildly non-flow-neutral
  scoped slice and review whether the offsetting leg sits outside the requested grouping
- `position_flow_residual_max_bp > 10`: treat as a materially non-flow-neutral scoped slice
- large `position_flow_residual_sum_bp` with small single-day maxima usually means repeated small
  net-flow pressure rather than one-off noise

Business reading:

- when the residual is tiny, the stock leg and cash leg are still effectively cancelling and
  contribution tie-out risk is low
- when the residual is persistent or material, the cancellation has broken down and the position set
  is no longer behaving like a clean internal reallocation story within the visible scope
- once that happens, summed position contribution can still look numerically plausible while drifting
  away from the portfolio-return story we want the engine to preserve

An especially useful asymmetry case is when one position causes most of the break and recapitalized
recovery while another position mostly rides through the episode:

- the current engine still keeps period and daily tie-out
- but the active `average_weight` can under-describe which position really carried the broken-capital
  episode economics
- that is why `average_weight_shadow_delta_positions` remains a first-class methodology signal even
  after the reset-heavy tie-out slices are green

## Current response shape

The response contains:

- `calculation_id`
- `portfolio_id`
- `results_by_period`
- `meta`
- `diagnostics`
- `audit`

Depending on the request, each period result can include:

- `position_contributions`
- `summary`
- `levels`
- `timeseries`
- `total_contribution`

Weight-unit contract:

- `position_contributions[].average_weight` is emitted in percentage units
- `levels[].rows[].weight_avg` is also emitted in percentage units and uses the same active or
  promoted denominator as position average weight
- both surfaces therefore use the same public unit convention: `25.0` means `25%`, not `0.25`

For front-office ranking surfaces, `position_contributions` remains the first-class output because
it provides direct position-level contribution and average-weight rows without requiring consumers to
reconstruct them from grouped hierarchy output.

When `hierarchy` is present:

- `summary.portfolio_contribution` is the hierarchy-mode top-line contribution for that resolved period
- `levels[]` contains the bottom-up rollup for that same resolved period
- multi-period requests return separate hierarchy summaries for `MTD`, `YTD`, `ITD`, and so on, when those periods resolve

Required reconciliation:

- summed `position_contributions[].total_contribution` equals `total_contribution`
- summed `timeseries[].total_contribution` equals `total_contribution` when daily totals are emitted
- summed `by_position_timeseries[].series[].contribution` equals `total_contribution` when
  by-position series are emitted
- `summary.portfolio_contribution` equals `total_contribution` when hierarchy is requested
- summed first-level `levels[].rows[].contribution` equals `total_contribution`
- summed first-level `levels[].rows[].weight_avg` equals 100% when the requested visible scope covers
  the full portfolio

Endpoint certification details are maintained in
[`docs/technical/contribution-endpoint-certification.md`](../technical/contribution-endpoint-certification.md).

## Example request

```json
{
  "portfolio_id": "CONTRIB_EXAMPLE_01",
  "report_start_date": "2025-01-01",
  "report_end_date": "2025-01-02",
  "analyses": [
    {
      "period": "ITD",
      "frequencies": ["daily"]
    }
  ],
  "hierarchy": ["sector", "position_id"],
  "portfolio_data": {
    "metric_basis": "NET",
    "valuation_points": [
      { "perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1020 },
      { "perf_date": "2025-01-02", "begin_mv": 1020, "bod_cf": 50, "end_mv": 1080 }
    ]
  },
  "positions_data": [
    {
      "position_id": "Stock_A",
      "meta": { "sector": "Technology" },
      "valuation_points": [
        { "perf_date": "2025-01-01", "begin_mv": 600, "end_mv": 612 },
        { "perf_date": "2025-01-02", "begin_mv": 612, "bod_cf": 50, "end_mv": 670 }
      ]
    },
    {
      "position_id": "Stock_B",
      "meta": { "sector": "Healthcare" },
      "valuation_points": [
        { "perf_date": "2025-01-01", "begin_mv": 400, "end_mv": 408 },
        { "perf_date": "2025-01-02", "begin_mv": 408, "end_mv": 410 }
      ]
    }
  ]
}
```

## Example response excerpt

```json
{
  "calculation_id": "2f4f3e0e-6e0e-4e0e-8e0e-2f4f3e0e6e0e",
  "portfolio_id": "CONTRIB_EXAMPLE_01",
  "results_by_period": {
    "ITD": {
      "summary": {
        "portfolio_contribution": 2.95327
      },
      "levels": []
    }
  },
  "meta": {},
  "diagnostics": {},
  "audit": {}
}
```

Use `/docs` for exact response schemas, enum values, and examples.
