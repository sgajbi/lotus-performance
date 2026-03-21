# Formula Mapping Review Notes

## Scope

This document captures formula-by-formula semantic mapping between externally supplied
reference formulas and the current `lotus-performance` implementation. The goal is to
identify whether any business condition is being lost, even when the code structure is
different.

## Review Conventions

- `Covered`: the same business condition is implemented, even if the code shape differs.
- `Indirectly Covered`: the condition is enforced through an upstream/precomputed field.
- `Needs Verification`: likely covered, but a critical semantic dependency still needs inspection.
- `Gap`: condition does not appear to be represented faithfully in current code.

## Formula 1: TempLongCumRoR

### Reference intent

Short summary from supplied formula:

- On a long day at period start, initialize temp long cumulative return with daily return.
- On a long day with zero daily return, carry prior temp long cumulative return.
- On a non-long day, compound prior return using:
  - `1 + previous_long_cum_ror`
  - `1 + daily_ror * sign(begin_mv + bod_cf)`
- On a non-long day at period start, zero out.
- Otherwise negate prior cumulative return.

### Current lotus-performance mapping

Primary engine path:

- [engine/ror.py](C:/Users/Sandeep/projects/lotus-performance/engine/ror.py)
  - `calculate_cumulative_ror(...)`
  - `_compound_ror(..., leg="long")`

Related consumption paths:

- [app/services/twr_service.py](C:/Users/Sandeep/projects/lotus-performance/app/services/twr_service.py)
- [app/services/returns_series_service.py](C:/Users/Sandeep/projects/lotus-performance/app/services/returns_series_service.py)
- [engine/contribution.py](C:/Users/Sandeep/projects/lotus-performance/engine/contribution.py)

### Assessment

- Long-leg geometric compounding: `Covered`
- First active long-day initialization: `Covered`
- Zero-return carry behavior: `Covered`
- Non-active-day carry/reset semantics: `Covered`
- Explicit use of `sign(begin_mv + bod_cf)`: `Needs Verification`

### Notes

- The supplied formula appears to contain unreachable branch ordering.
- `lotus-performance` does not implement this exact method literally; it implements the
  same long/short cumulative-return concept in a vectorized two-leg engine.
- The main semantic dependency still to verify is whether `PortfolioColumns.SIGN`
  is derived from the same economic rule as `sign(begin_mv + bod_cf)`.

## Formula 2: TempShortCumRoR

### Reference intent

Short summary from supplied formula:

- On a non-long day at period start, initialize temp short cumulative return with daily return.
- On a non-long day with zero daily return, carry prior temp short cumulative return.
- On a non-long day generally, compound prior short return using:
  - `1 - previous_short_cum_ror`
  - `1 + daily_ror * sign(begin_mv + bod_cf)`
  - negate final compounded value back into short-return space
- On a long day at period start, short cumulative should be zero.
- On later long days, carry prior short cumulative return.

### Current lotus-performance mapping

Primary engine path:

- [engine/ror.py](C:/Users/Sandeep/projects/lotus-performance/engine/ror.py)
  - `calculate_cumulative_ror(...)`
  - `_compound_ror(..., leg="short")`

Related consumption paths:

- [app/services/twr_service.py](C:/Users/Sandeep/projects/lotus-performance/app/services/twr_service.py)
- [app/services/returns_series_service.py](C:/Users/Sandeep/projects/lotus-performance/app/services/returns_series_service.py)
- [engine/contribution.py](C:/Users/Sandeep/projects/lotus-performance/engine/contribution.py)

### Assessment

- First active short-day initialization: `Covered`
- Zero-return carry behavior: `Covered`
- Geometric short-leg compounding: `Covered`
- Zeroing inactive short leg at period start: `Covered`
- Carrying short cumulative across long-leg days: `Covered`
- Explicit use of `sign(begin_mv + bod_cf)`: `Needs Verification`

### Notes

- The supplied formula maps more cleanly to the current two-leg engine than the long example.
- The key semantic dependency is again whether the engine’s precomputed `SIGN` column
  represents `sign(begin_mv + bod_cf)` exactly.

## Open Cross-Cutting Verification

- Inspect how `PortfolioColumns.SIGN` is derived in the engine prep path.
- Confirm whether it is exactly equivalent to `sign(begin_mv + bod_cf)` or a different rule.

## Formula 3: NCtrl1

### Reference intent

Short summary from supplied formula:

- `NCtrl1` is `true` when:
  - `temp_long_cum_ror` exists
  - `temp_long_cum_ror < -1`
  - `NCtrl.will_reset_performance(...)` is `true`

In percentage terms, this means:

- trigger reset when temporary long cumulative return is below `-100%`
- but only when the reset-permission condition is satisfied for the day

### Current lotus-performance mapping

Primary engine path:

- [engine/rules.py](C:/Users/Sandeep/projects/lotus-performance/engine/rules.py)
  - `calculate_initial_resets(...)`
- [engine/ror.py](C:/Users/Sandeep/projects/lotus-performance/engine/ror.py)
  - `calculate_cumulative_ror(...)`

Relevant fields:

- `PortfolioColumns.TEMP_LONG_CUM_ROR`
- `PortfolioColumns.NCTRL_1`
- `PortfolioColumns.PERF_RESET`

### Assessment

- `temp_long_cum_ror < -100%` threshold: `Covered`
- dedicated `NCTRL_1` flag: `Covered`
- `will_reset_performance(...)` style gating condition: `Covered`
- exact same implementation shape: `No`

### Notes

The current implementation is:

- `cond_nctrl1 = df[temp_long_col] < -100`
- then gated through `cond_common`

`cond_common` currently allows reset when any of these are true:

- same-day BOD cash flow exists
- next-day BOD cash flow exists
- same-day EOD cash flow exists
- date is month-end
- next date falls after report end

So semantically, `cond_common` is the current engine equivalent of
`NCtrl.will_reset_performance(...)`.

### Potential semantic difference to review later

`will_reset_performance(...)` in the supplied formula is abstract, while
`lotus-performance` hardcodes the gating rule into `cond_common`.

That means:

- threshold behavior is aligned
- reset gating definitely exists
- but exact equivalence depends on whether the intended business definition of
  `will_reset_performance(...)` is exactly:
  - BOD cash flow today
  - BOD cash flow tomorrow
  - EOD cash flow today
  - month-end
  - end-of-report

Current status: `Needs Verification`, but no obvious missing reset condition from this formula alone.

## Formula 21: MetricCalculator

### Reference intent

Short summary from supplied formula:

- contribution calculation is orchestrated through a dedicated `MetricCalculator`
- the pipeline explicitly computes:
  - portfolio parameters
  - smoothing factors
  - grouped cash-flow views
  - daily group returns
  - metric-by-metric results through a metric factory
  - residual rows where requested
- the work is chunked and parallelized for large grouped result sets
- intermediate archives and audit events are first-class parts of the workflow

### Current lotus-performance mapping

Primary engine / service paths:

- [engine/contribution.py](C:/Users/Sandeep/projects/lotus-performance/engine/contribution.py)
- [app/services/contribution_service.py](C:/Users/Sandeep/projects/lotus-performance/app/services/contribution_service.py)
- [app/services/stateful_contribution_input_service.py](C:/Users/Sandeep/projects/lotus-performance/app/services/stateful_contribution_input_service.py)

Related supporting paths:

- contribution request / response models
- current grouping and residual handling inside the contribution engine

### Assessment

- contribution metrics are calculated over grouped cash-flow inputs: `Covered`
- residual behavior exists: `Covered`
- smoothing support exists: `Partially Covered`
- explicit metric-factory orchestration: `Not Covered`
- explicit chunked async processing model: `Not Covered`
- audit / archive / contribution-store workflow parity: `Not Covered`

### Notes

This is mainly an orchestration and architecture comparison, not a direct formula comparison.

The current implementation does produce contribution outputs, smoothing-aware metrics, and
residual handling, but it does so through a simpler service/engine flow.

Important differences from the supplied design:

- no explicit `MetricCalculator` coordinator class
- no explicit `MetricFactory`-driven per-metric dispatch in this form
- no chunked `asyncio` / `to_thread` grouped execution path
- no first-class audit-event lifecycle around contribution calculation
- no explicit archive/store workflow matching the supplied model
- no reusable `ContributionStore` flushing pattern in the same shape

### Practical conclusion

If the requirement is output parity only, this is not automatically a blocker.

If the requirement is full methodological and operational parity with the supplied design,
then this is an `Architectural Gap`, with some functional implications on:

- smoothing traceability
- residual traceability
- intermediate-result archival
- reset-aware contribution workflow transparency

Current status: `Architectural Gap`.

## Formula 24: IndividualTimeWeightedReturn

### Reference intent

Short summary from supplied formula:

- the contribution engine computes per-group time-weighted return using the same daily and
  cumulative long/short machinery as portfolio performance
- the grouped return path is reset-aware and NIP-aware
- it uses:
  - previous and next day data
  - `next_performance_reset`
  - account-level performance reset from portfolio returns
- the final metric result is the group’s final cumulative return

### Current lotus-performance mapping

Primary contribution / performance paths:

- [engine/contribution.py](C:/Users/Sandeep/projects/lotus-performance/engine/contribution.py)
- [engine/ror.py](C:/Users/Sandeep/projects/lotus-performance/engine/ror.py)
- [engine/rules.py](C:/Users/Sandeep/projects/lotus-performance/engine/rules.py)

### Assessment

- per-group return metric exists: `Covered`
- shared TWR-style math intent exists: `Covered`
- exact reuse of the richer `DailyAndCumulativeRoR` orchestration: `Partially Covered`
- explicit account-level performance-reset input into grouped return calculation: `Not Covered`
- exact previous/next-day orchestration parity: `Not Covered`

### Notes

This is a meaningful comparison formula because it describes how contribution-side instrument or
group return should stay tied to the core performance engine.

The current code does produce group return metrics and contribution outputs that are intended to
reconcile with portfolio TWR, but it does not appear to use this exact richer grouped-return
orchestration shape.

Important differences from the supplied design:

- no explicit `IndividualTimeWeightedReturn` metric class in this same form
- no explicit `next_performance_reset` input
- no explicit `account_performance_reset` feed from portfolio returns into the grouped-return
  calculation in this shape
- simpler current contribution metric workflow

### Practical conclusion

This is not a total gap because the grouped TWR idea clearly exists.

But if the supplied design is the intended source of truth, then current contribution return
calculation likely needs review around:

- reset propagation
- grouped-return orchestration parity
- intermediate daily return traceability

Current status: `Partially Covered`.

## Formula 25: DailyAndCumulativeRoR.calculate_daily_and_cumulative_ror

### Reference intent

Short summary from supplied formula:

- this is the core orchestration point for daily performance state
- it computes, in order:
  - `sign`
  - `daily_ror`
  - temporary long cumulative return
  - temporary short cumulative return
  - `sod_reset`
  - `nctrl1..4`
  - aggregated `performance_reset`
  - final long cumulative return
  - final short cumulative return
  - final combined cumulative return
- the full state machine is explicitly driven by:
  - previous long/short cumulative return
  - previous sign
  - previous performance reset
  - `nips`
  - `next_performance_reset`
  - `account_performance_reset`

### Current lotus-performance mapping

Primary engine paths:

- [engine/ror.py](C:/Users/Sandeep/projects/lotus-performance/engine/ror.py)
- [engine/rules.py](C:/Users/Sandeep/projects/lotus-performance/engine/rules.py)
- [engine/compute.py](C:/Users/Sandeep/projects/lotus-performance/engine/compute.py)

### Assessment

- daily return orchestration exists: `Covered`
- sign / temporary long-short / cumulative long-short concepts exist: `Covered`
- explicit state-machine parity for all supplied inputs: `Partially Covered`
- `sod_reset` integration: `Not Covered`
- `account_performance_reset` integration: `Not Covered`
- exact combined orchestration shape: `Not Covered`

### Notes

This formula is important because it combines many earlier formulas into one intended flow.

The current engine definitely implements a daily/cumulative return state machine, but in a more
vectorized and compressed way than the supplied model.

What appears aligned:

- sign-based long/short handling
- daily RoR calculation
- temporary and final cumulative long/short concepts
- reset controls `nctrl1..4` in some form

What still looks materially incomplete versus the supplied model:

- no explicit `sod_reset` concept carried into `performance_reset`
- no explicit `account_performance_reset` path in the current engine reset aggregation
- simpler reset and NIP propagation than the supplied combined orchestration

### Practical conclusion

This is not a total gap because the current performance engine clearly exists and works.

But if the supplied formula set is intended to be the authoritative business design, this is one
of the strongest indicators that our current performance engine likely needs refinement around:

- reset aggregation completeness
- reset-aware cumulative return transitions
- NIP handling after reset boundaries

Current status: `Partially Covered`, with meaningful sub-gaps.

## Formula 26: DailyGroupRoRCalculator.daily_group_ror

### Reference intent

Short summary from supplied formula:

- group-level daily return state is calculated day by day across the requested date range
- each group day is driven by:
  - today, previous-day, and next-day cash-flow context
  - NIP state for previous, current, and next day
  - previous long/short cumulative return state
  - account-level performance reset input
- output is a per-date `PortfolioRoR` dictionary for the group

### Current lotus-performance mapping

Primary contribution / grouped-return paths:

- [engine/contribution.py](C:/Users/Sandeep/projects/lotus-performance/engine/contribution.py)
- supporting TWR paths in:
  - [engine/ror.py](C:/Users/Sandeep/projects/lotus-performance/engine/ror.py)
  - [engine/rules.py](C:/Users/Sandeep/projects/lotus-performance/engine/rules.py)

### Assessment

- grouped daily return concept exists: `Covered`
- grouped contribution return path is intended to reconcile to portfolio TWR: `Covered`
- exact reset-aware daily group state-machine in this shape: `Partially Covered`
- explicit `account_performance_reset_data` feed: `Not Covered`
- exact previous/current/next NIP orchestration parity: `Not Covered`

### Notes

This is another important bridge formula between portfolio performance and contribution.

Together with the supplied `IndividualTimeWeightedReturn` and `DailyAndCumulativeRoR`
formulas, it points toward a richer grouped-return framework than the current simpler
contribution implementation.

The main likely missing areas versus the supplied model are:

- account-level reset propagation into group-level daily return calculation
- next-day aware NIP/reset orchestration
- explicit daily group state traceability

### Practical conclusion

This is not a total gap because grouped daily return behavior clearly exists in the current
contribution engine.

But if the supplied model is authoritative, this is another `Partially Covered` area that likely
needs refinement to fully align contribution with the main performance reset model.

Current status: `Partially Covered`.

## Formula 23: GroupDailyWeight.from_list

### Reference intent

Short summary from supplied formula:

- a `GroupDailyWeight` carries:
  - `date`
  - `nip`
  - `weight`
- there is an explicit transformation to archived / stored `DailyWeight` rows using:
  - the daily weight date
  - the grouping key
  - the scalar weight value

### Current lotus-performance mapping

Primary contribution-related paths:

- [engine/contribution.py](C:/Users/Sandeep/projects/lotus-performance/engine/contribution.py)
- [app/services/contribution_service.py](C:/Users/Sandeep/projects/lotus-performance/app/services/contribution_service.py)

### Assessment

- daily-weight concept exists: `Covered`
- stored intermediate daily-weight rows in this exact model shape: `Partially Covered`
- explicit `GroupDailyWeight -> DailyWeight[]` adapter in this form: `Not Covered`

### Notes

This is another support-structure / traceability check rather than a core formula gap.

The bigger related issue is not this conversion method by itself. It is whether the contribution
workflow retains and stores reset-aware, NIP-aware daily-weight intermediates in a reusable,
auditable shape.

### Practical conclusion

By itself this is low priority.

If we decide to move toward the richer reference contribution architecture, this becomes part of
that same implementation family.

Current status: `Architectural Gap`.

## Formula 22: RequestParameters

### Reference intent

Short summary from supplied formula:

- contribution / metric calculation receives a single request-parameter object
- that object carries:
  - request context
  - portfolio resolver
  - date range
  - basis
  - archive/store intermediate-result switches
  - optional archive suffix
- `request_id` is exposed as a derived property from `request_context`

### Current lotus-performance mapping

Primary service / model paths:

- [app/services/contribution_service.py](C:/Users/Sandeep/projects/lotus-performance/app/services/contribution_service.py)
- contribution request models in [app/models/contribution_requests.py](C:/Users/Sandeep/projects/lotus-performance/app/models/contribution_requests.py)
- request routing / endpoint handling

### Assessment

- equivalent operational inputs exist: `Covered`
- single packaged `RequestParameters` object in this exact shape: `Not Covered`
- derived `request_id` access pattern: `Partially Covered`

### Notes

This is not a math gap.

The current system does carry equivalent information through service calls and request models,
but not via one explicit `RequestParameters` dataclass with this exact boundary.

This matters mainly for:

- orchestration clarity
- audit / archive workflow consistency
- parity with the reference implementation shape

### Practical conclusion

If output behavior is the target, this is low priority.

If design parity with the supplied orchestration model is important, this is another
`Architectural Gap`.

Current status: `Architectural Gap`.

## Formula 6: NCtrl4

### Reference intent

Short summary from supplied formula:

- `NCTRL4` depends on:
  - previous long cumulative return boundary: `prev_long_cum_ror == -1`
  - or previous short cumulative return boundary: `prev_short_cum_ror == 1`
- and it behaves differently depending on whether the current day is `NIP`

Detailed intent:

- If current day is `NIP`:
  - trigger reset when:
    - next day is not `NIP`
    - next day BOD cash flow is non-zero
    - prior cumulative return is exactly on the reset boundary

- If current day is not `NIP`:
  - trigger reset when:
    - previous day was `NIP`
    - current day BOD cash flow is zero
    - prior cumulative return is exactly on the reset boundary

### Current lotus-performance mapping

Primary engine path:

- [engine/rules.py](C:/Users/Sandeep/projects/lotus-performance/engine/rules.py)
  - `calculate_nctrl4_reset(...)`
- [engine/ror.py](C:/Users/Sandeep/projects/lotus-performance/engine/ror.py)
  - `calculate_cumulative_ror(...)`

Relevant fields:

- `PortfolioColumns.NIP`
- `PortfolioColumns.NCTRL_4`
- `PortfolioColumns.PERF_RESET`
- `PortfolioColumns.LONG_CUM_ROR`
- `PortfolioColumns.SHORT_CUM_ROR`

### Assessment

- reset-boundary concept exists: `Covered`
- `NCTRL_4` flag exists explicitly: `Covered`
- use of previous cumulative returns: `Covered`
- NIP-aware branch logic: `Partially Covered`
- exact equality boundary (`== -1`, `== 1`): `Not Exact`
- exact cash-flow gating semantics: `Not Exact`

### Notes

Current implementation:

- `prev_long_ror <= -100`
- or `prev_short_ror >= 100`
- and:
  - current-day BOD cash flow is non-zero
  - or previous-day EOD cash flow is non-zero

So the current engine compresses several business conditions into a broader rule:

- it does not explicitly branch on:
  - current `NIP`
  - next `NIP`
  - previous `NIP`
- it does not require exact equality to the reset boundary
- it uses inequality thresholds instead of exact-boundary tests
- it uses:
  - current BOD cash flow
  - previous EOD cash flow
  rather than the supplied:
  - next BOD cash flow in the `NIP` branch
  - current BOD cash flow zero in the non-`NIP` branch

### Current status

This is the first formula in the set that looks like a genuine semantic compression.

Status: `Needs Deeper Review`

Not enough evidence yet to call it a definite bug, but this is a real candidate for change once
the full formula set is reviewed.

## Formula 7: NonInvestPeriod (NIP)

### Reference intent

Short summary from supplied formula:

- `NIP` is `true` when:
  - `sod_value + sod_cash_flow + eod_value + eod_cash_flow == 0`
  - and `sod_cash_flow == 0`
  - and `eod_cash_flow == 0`

This is a strict zero-capital / zero-cash-flow rule.

### Current lotus-performance mapping

Primary engine path:

- [engine/rules.py](C:/Users/Sandeep/projects/lotus-performance/engine/rules.py)
  - `calculate_nip(...)`
- [engine/config.py](C:/Users/Sandeep/projects/lotus-performance/engine/config.py)
  - `FeatureFlags.use_nip_v2_rule`

Relevant field:

- `PortfolioColumns.NIP`

### Assessment

- strict zero-capital requirement: `Covered`
- strict zero cash-flow requirement: `Covered in v2`, `Not Exact in default rule`
- exact formula parity: `Feature-Flag Dependent`

### Notes

Current implementation has two variants:

1. `use_nip_v2_rule = True`

Current logic:

- `(begin_mv + bod_cf == 0)`
- and `(end_mv + eod_cf == 0)`

This is close to the supplied formula, but still not identical in shape.

2. Default rule (`use_nip_v2_rule = False`)

Current logic:

- total zero-value check:
  - `begin_mv + bod_cf + end_mv + eod_cf == 0`
- plus an offsetting cash-flow rule:
  - `eod_cf == -sign(bod_cf)`

This is not the same as the supplied formula.

### Interpretation

Compared with the supplied formula:

- the `v2` rule is much closer semantically
- the default rule is materially different because it allows an offsetting cash-flow pattern
  instead of requiring both BOD and EOD cash flows to be exactly zero

### Current status

Status: `Needs Deeper Review`

This is a plausible change candidate, depending on which NIP definition is the intended business rule.

## Formula 8: NCtrl.will_reset_performance

### Reference intent

The supplied implementation makes `will_reset_performance(...)` explicitly:

- `sod_cash_flow != 0`
- or `eod_cash_flow != 0`
- or `target_date` is last day of month
- or `target_date == end_date`

### Current lotus-performance mapping

Primary engine path:

- [engine/rules.py](C:/Users/Sandeep/projects/lotus-performance/engine/rules.py)
  - `calculate_initial_resets(...)`

Current engine equivalent:

- `cond_common`

### Assessment

- same-day BOD cash flow condition: `Covered`
- same-day EOD cash flow condition: `Covered`
- month-end condition: `Covered`
- report-end condition: `Covered`
- exact parity: `Not Exact`

### Notes

Current engine `cond_common` is:

- current BOD cash flow is non-zero
- or next-day BOD cash flow is non-zero
- or current EOD cash flow is non-zero
- or current date is month-end
- or next date is after report end

Compared with the supplied formula, the current engine adds one extra condition:

- next-day BOD cash flow is non-zero

And it expresses report-end slightly differently:

- supplied rule: `target_date == end_date`
- current engine: `next_date_is_after_end`

Those are usually equivalent for regular daily rows, but they are not identical in shape.

### Interpretation

This resolves an earlier open question from `NCtrl1/2/3`:

- `lotus-performance` does implement the intended reset gating family
- but it is slightly broader because it also treats next-day BOD cash flow as a reset boundary trigger

### Current status

Status: `Mostly Covered with Extra Condition`

This does not yet prove a defect, but it does mean the current reset gating is broader than the supplied rule.

## Formula 9: NonInvestPeriodDays

### Reference intent

Short summary from supplied formula:

- Count `nip` days only from the most recent performance reset boundary onward
- More precisely:
  - walk backward through `group_daily_weights`
  - stop once dates fall before `last_performance_reset_date`
  - count only `group_daily_weight.nip == true` in that trailing window

### Current lotus-performance mapping

Primary engine path:

- [engine/compute.py](C:/Users/Sandeep/projects/lotus-performance/engine/compute.py)
  - `run_calculations(...)`

Current diagnostics output:

- `nip_days = int(final_df[PortfolioColumns.NIP.value].sum())`
- `reset_days = int(final_df[PortfolioColumns.PERF_RESET.value].sum())`

### Assessment

- `nip_days` counting exists: `Covered`
- reset-aware trailing-window logic: `Not Covered`
- exact formula parity: `Gap`

### Notes

Current implementation counts all `NIP` rows in the filtered reporting window:

- no filtering by `last_performance_reset_date`
- no backward scan from the latest row
- no “count only since latest reset” behavior

So if the intended business meaning of `nip_days` is:

- “NIP days since last performance reset”

then the current engine diagnostics are too broad.

### Current status

Status: `Gap`

This is a real candidate for change if the supplied formula reflects the intended diagnostic definition.

## Formula 14: Contribution AverageWeight / DailyWeight / Residual

### Reference intent

This supplied implementation defines contribution average weight using several linked rules:

1. Daily weight

- default:
  - `(instrument_sod_mv + instrument_sod_cf) / (portfolio_sod_mv + portfolio_sod_cf)`
- if portfolio denominator is zero:
  - daily weight = `0`
- special acquisition-day fallback:
  - if instrument `sod_market_value == 0`
  - and `(sod_cash_flow + eod_cash_flow) == 0`
  - and `eod_value != 0`
  - then weight = `0.0001`
- scaled by `100`

2. Reset-aware averaging window

- iterate day by day
- when `performance_reset` is true:
  - set `last_performance_reset_date = current_date`
  - clear the active accumulator
- only accumulated post-reset daily weights are used for final averaging

3. NIP-aware denominator

- `valid_days` subtracts `nip_days`
- and if a reset exists, valid days are measured only since last reset

4. Final average weight

- `sum(weight values in active window) / valid_days`

5. Residual helper

- `100 - sum(metric_result)`

### Current lotus-performance mapping

Primary engine path:

- [engine/contribution.py](C:/Users/Sandeep/projects/lotus-performance/engine/contribution.py)
  - `_calculate_daily_instrument_contributions(...)`
  - `build_hierarchical_contribution_result(...)`
- [app/services/contribution_service.py](C:/Users/Sandeep/projects/lotus-performance/app/services/contribution_service.py)

Relevant response fields:

- `average_weight`
- `weight_avg`
- `residual_bp`

### Assessment

#### Daily weight core formula

- `(begin_mv + bod_cf) / (portfolio_begin_mv + portfolio_bod_cf)`: `Covered`
- zero portfolio denominator -> zero weight: `Covered`
- acquisition-day fallback weight `0.0001`: `Not Covered`

#### Reset-aware averaging window

- explicit clearing of averaging accumulator on reset: `Not Covered`
- explicit tracking of `last_performance_reset_date`: `Not Covered`

#### NIP-aware denominator

- valid-days denominator reduced by NIP days: `Not Covered`
- valid-days denominator measured since last reset: `Not Covered`

#### Final average weight

- current implementation uses simple arithmetic mean of `daily_weight`: `Not Exact`

#### Residual helper

- current contribution residual handling is different:
  - it allocates residual contribution across rows under `CARINO`
  - it does not expose a standalone `100 - sum(metric_result)` average-weight residual rule

### Notes

Current implementation differences:

1. Daily weight

Current engine:

- `daily_weight = capital_inst / capital_port`
- zero/invalid division -> `0`

This matches the base formula, but the special `0.0001` acquisition-day fallback does not exist.

2. Average weight

Current engine:

- `weight_avg = mean(daily_weight)`

This is simpler than the supplied logic and does not account for:

- resets truncating the averaging window
- valid-day calculation
- NIP-day exclusion from denominator

3. Residual

Current engine residual logic is contribution-oriented, not average-weight oriented:

- residual = portfolio total return - sum of contributions
- when smoothing is `CARINO`, residual is allocated back by average-weight proportion

That is not the same as the supplied `100 - sum(metric_result)` helper.

### Current status

Status: `Gap`

This is one of the stronger change candidates in the current review set, especially if contribution average weight
is expected to be reset-aware and NIP-aware under the supplied business model.

## Formula 15: SmoothingFactors

### Reference intent

The supplied implementation defines a richer smoothing-factor framework with:

- daily smoothing-factor records
- period-level long/short cumulative return inputs
- logarithmic return intermediates:
  - `ln_ror_daily`
  - `ln_ror_period`
- derived intermediates:
  - `ratio_of_ln_long_short`
  - `r_ratio`
- final `smoothing_factor`
- optional archival of intermediate smoothing data

This is more than a simple “on/off smoothing”; it is a governed smoothing-data model.

### Current lotus-performance mapping

Primary engine path:

- [engine/contribution.py](C:/Users/Sandeep/projects/lotus-performance/engine/contribution.py)

Relevant current behavior:

- supports smoothing methods:
  - `CARINO`
  - `NONE`
- computes:
  - `k_daily = log(1 + r_t) / r_t`
  - `K_total = log(1 + R_total) / R_total`
- applies adjustment:
  - `daily_weight * (R_port_t * ((K_total / k_t) - 1))`

### Assessment

- smoothing exists: `Covered`
- Carino-style factor exists: `Covered`
- explicit per-date smoothing-factor map object: `Not Covered`
- long/short log-ratio framework: `Not Covered`
- archival of smoothing intermediates: `Not Covered`
- exact formula parity: `Not Exact`

### Notes

Current `lotus-performance` contribution smoothing is simpler than the supplied framework:

- it uses a standard Carino-style adjustment
- it does not expose:
  - `SmoothingData`
  - `ratio_of_ln_long_short`
  - `r_ratio`
  - archival of smoothing-factor intermediates
- it does not appear to use complex-number intermediate types

So the current implementation likely captures the broad smoothing intent for contribution,
but not the full supplied smoothing model.

### Current status

Status: `Partially Covered`

This is only a change candidate if the supplied smoothing data model, not just the smoothing outcome,
is part of the intended business requirement.

## Formula 16: Smoothed

### Reference intent

This supplied implementation defines the smoothed contribution metric as:

- per-date smoothing based on:
  - smoothing factor
  - daily return
  - daily weight
- cumulative smoothed values are built day by day
- when `portfolio_ror.performance_reset.value` is true:
  - clear the active smoothed accumulator
- final metric result:
  - latest active smoothed value real-part times `100`
- residual:
  - `100 * final_cum_ror - sum(metric_result)`

It also archives intermediate daily smoothing data.

### Current lotus-performance mapping

Primary engine path:

- [engine/contribution.py](C:/Users/Sandeep/projects/lotus-performance/engine/contribution.py)
- [app/services/contribution_service.py](C:/Users/Sandeep/projects/lotus-performance/app/services/contribution_service.py)

### Assessment

- smoothed contribution metric exists: `Covered`
- weight-based daily smoothing adjustment exists: `Covered`
- explicit reset-aware clearing of smoothed accumulator: `Not Covered`
- final “latest active smoothed value” model: `Not Exact`
- residual formula against `100 * final_cum_ror`: `Partially Covered`
- archival of smoothing intermediates: `Not Covered`

### Notes

Current contribution implementation is simpler:

- computes daily `smoothed_contribution` values directly
- zeros contribution rows on dates where portfolio is `NIP` or `PERF_RESET`
- then aggregates by summing smoothed daily contributions

This differs from the supplied model in a few important ways:

1. Reset handling

Supplied model:

- clear the smoothed accumulator when `performance_reset` occurs

Current model:

- zero daily contribution values on reset/NIP dates
- but does not maintain a separate rolling smoothed accumulator that is explicitly cleared

2. Final smoothed metric

Supplied model:

- final result is the last active cumulative smoothed value

Current model:

- final result is sum of smoothed daily contributions over the period slice

Those can align in some cases, but they are not the same implementation model.

3. Residual

Supplied model:

- residual = `100 * final_cum_ror - sum(metric_result)`

Current model:

- residual contribution = portfolio total return - summed contribution
- under `CARINO`, residual is reallocated back by average-weight proportion

That is related, but not identical.

### Current status

Status: `Gap`

This is a meaningful difference candidate if the supplied smoothed-metric semantics are the intended contribution model.

## Formula 17: SmoothedUtils

### Reference intent

This supplied utility layer defines the mathematical internals for smoothing:

- log-return transformations for:
  - daily returns
  - period long/short cumulative returns
- explicit long/short handling based on sign
- long/short weighting of period returns
- final compounding portions
- `r_ratio`
- smoothing factor
- daily smoothed contribution:
  - `smoothing_factor * daily_ror * abs(weight_daily)`
- support for complex-number intermediate values

This is a full smoothing math framework, not just a generic Carino adjustment.

### Current lotus-performance mapping

Primary engine path:

- [engine/contribution.py](C:/Users/Sandeep/projects/lotus-performance/engine/contribution.py)

Current smoothing implementation:

- `k_daily = log(1 + r_t) / r_t`
- `K_total = log(1 + R_total) / R_total`
- adjustment:
  - `daily_weight * (R_port_t * ((K_total / k_t) - 1))`

### Assessment

- use of logarithmic smoothing concepts: `Covered in simplified form`
- explicit long/short period decomposition in smoothing math: `Not Covered`
- explicit `r_ratio` construct: `Not Covered`
- explicit final compounding portions long/short: `Not Covered`
- complex-number intermediate support: `Not Covered`
- exact daily smoothing formula:
  - `smoothing_factor * daily_ror * abs(weight_daily)`: `Not Covered`

### Notes

Current contribution smoothing in `lotus-performance` is materially simpler than the supplied utility model.

What is similar:

- both are log-based smoothing families
- both produce a daily smoothing adjustment applied to contribution

What is different:

- current implementation uses a direct Carino-style factor
- current implementation does not expose or compute:
  - `ln_ror_period`
  - long/short smoothing branches
  - `r_ratio`
  - compounding portions
  - complex-valued intermediates
- current implementation uses signed `daily_weight`, not `abs(weight_daily)` in a standalone smoothing formula

### Current status

Status: `Gap`

This strengthens the earlier smoothing finding: `lotus-performance` currently implements a simpler Carino smoothing model,
not the richer supplied long/short smoothing framework.

## Formula 18: MetricFactory

### Reference intent

The supplied design defines a metric-selection abstraction with three named contribution metrics:

- `AVERAGE_WEIGHT`
- `ROR`
- `SMOOTHED`

and a factory that resolves each metric name to its implementation class.

### Current lotus-performance mapping

Primary current implementation paths:

- [engine/contribution.py](C:/Users/Sandeep/projects/lotus-performance/engine/contribution.py)
- [app/services/contribution_service.py](C:/Users/Sandeep/projects/lotus-performance/app/services/contribution_service.py)

### Assessment

- support for average-weight style output: `Partially Covered`
- support for return/contribution style output: `Covered in effect`
- support for smoothed contribution output: `Covered in effect`
- explicit metric-factory abstraction: `Not Covered`
- explicit metric-by-metric pluggable engine design: `Not Covered`

### Notes

Current `lotus-performance` contribution implementation is more direct:

- daily weights are computed inline
- smoothed contribution is computed inline
- contribution aggregation is computed inline

There is no explicit factory or class-per-metric selection layer matching:

- `AverageWeight`
- `IndividualTimeWeightedReturn`
- `Smoothed`

So this is mainly an architectural difference:

- the current implementation can produce related outputs
- but it does not use the same metric abstraction model

### Current status

Status: `Architectural Gap`

This is only a change candidate if the metric-factory structure itself is required, not just the resulting analytics.

## Formula 19: PortfolioRoRCalculator

### Reference intent

The supplied implementation is a richer portfolio return orchestration model with:

- explicit day-by-day object construction
- use of prior-day and next-day context
- first pass to build temporary portfolio ROR objects
- second pass to rebuild final results with:
  - previous-day result
  - next-day result
  - `next_performance_reset`
  - rich `CashFlows`
  - rich `MarketValues`
- explicit account-level filtering and extra fields such as:
  - taxes
  - management-fee carry fields
  - performance-start / performance-end market values
  - account-level reset hooks

### Current lotus-performance mapping

Primary current engine paths:

- [engine/compute.py](C:/Users/Sandeep/projects/lotus-performance/engine/compute.py)
- [engine/ror.py](C:/Users/Sandeep/projects/lotus-performance/engine/ror.py)
- [engine/rules.py](C:/Users/Sandeep/projects/lotus-performance/engine/rules.py)
- [engine/runtime.py](C:/Users/Sandeep/projects/lotus-performance/engine/runtime.py)

### Assessment

- portfolio daily return calculation exists: `Covered`
- sign / NIP / reset aware cumulative-return calculation exists: `Covered`
- explicit two-pass object graph orchestration: `Not Covered`
- use of `next_performance_reset` as explicit input: `Not Covered`
- account-level reset hook: `Not Covered`
- taxes as explicit return input: `Not Covered`
- performance-start / performance-end market value fields: `Not Covered`

### Notes

Current `lotus-performance` engine is more vectorized and dataframe-driven:

- prepare dataframe
- calculate daily return
- calculate sign
- calculate NIP
- calculate cumulative return / reset flags
- emit diagnostics

This means the broad return engine is present, but not the same orchestration model.

Most importantly, the supplied design suggests some forward-looking or second-pass dependencies:

- `next_performance_reset`
- richer next-day market/cash-flow context

The current engine does not expose that style of staged object orchestration explicitly.

### Current status

Status: `Partially Covered`

Core performance behavior exists, but the supplied orchestration model is materially richer than the current implementation.

## Formula 20: PortfolioParameters

### Reference intent

This supplied implementation defines a portfolio-level parameter bundle used by smoothing logic:

- `final_compounding_component`
- `ror_weight_long`
- `ror_weight_short`
- `final_compounding_portion_long`
- `final_compounding_portion_short`
- `portfolio_values` by date, capturing:
  - `sod_value`
  - `sod_cash_flow`

This is a reusable portfolio-parameter object, not just a local intermediate.

### Current lotus-performance mapping

Primary current related paths:

- [engine/contribution.py](C:/Users/Sandeep/projects/lotus-performance/engine/contribution.py)
- [engine/ror.py](C:/Users/Sandeep/projects/lotus-performance/engine/ror.py)

### Assessment

- portfolio daily valuation context exists: `Covered`
- period long/short cumulative returns exist: `Covered`
- explicit reusable `PortfolioParameters` object: `Not Covered`
- final compounding component/portion calculations as named artifacts: `Not Covered`
- long/short return weights as named artifacts: `Not Covered`

### Notes

Current `lotus-performance` has the underlying ingredients:

- portfolio daily results
- long/short cumulative return series
- BOD market values and cash flows

But it does not package them into a portfolio-parameter abstraction like the supplied model.

This mostly reinforces the earlier smoothing-framework gap:

- the current system computes simpler contribution smoothing
- it does not expose the richer portfolio-parameter model that the supplied formulas expect

### Current status

Status: `Architectural Gap`

This becomes a functional change candidate only if the supplied smoothing parameterization is required, not merely equivalent output.

## Formula 10: PerformanceReset

### Reference intent

Short summary from supplied formula:

- `performance_reset =`
  - `account_performance_reset`
  - or `sod_reset`
  - or `nctrl1`
  - or `nctrl2`
  - or `nctrl3`
  - or `nctrl4`
- if `account_performance_reset` is `None`, ignore it and evaluate the rest

So this is the master reset aggregator.

### Current lotus-performance mapping

Primary engine paths:

- [engine/ror.py](C:/Users/Sandeep/projects/lotus-performance/engine/ror.py)
  - initializes `PERF_RESET` from initial reset controls
  - then overlays `NCTRL_4`
- [engine/compute.py](C:/Users/Sandeep/projects/lotus-performance/engine/compute.py)
  - emits diagnostics and reset events from `PERF_RESET`

Current implementation shape:

- `PERF_RESET = nctrl1 | nctrl2 | nctrl3`
- then:
  - `PERF_RESET = PERF_RESET | nctrl4`

### Assessment

- `nctrl1`: `Covered`
- `nctrl2`: `Covered`
- `nctrl3`: `Covered`
- `nctrl4`: `Covered`
- `account_performance_reset`: `Not Covered`
- `sod_reset`: `Not Covered`
- exact master reset aggregation: `Gap`

### Notes

The current engine has a narrower reset aggregator than the supplied formula.

What it clearly includes:

- `NCTRL_1`
- `NCTRL_2`
- `NCTRL_3`
- `NCTRL_4`

What it does not currently expose as separate upstream contributors:

- `account_performance_reset`
- `sod_reset`

There may be related business effects represented elsewhere, but they are not currently visible as explicit
contributors to the `PERF_RESET` flag in the engine code.

### Current status

Status: `Gap`

If the supplied formula is the intended business definition, current reset aggregation is incomplete.

## Formula 11: RoR

### Reference intent

Short summary from supplied formula:

- For `NET`, include management fee in the return numerator
- For `GROSS`, zero out management fee contribution
- If `sod_value + sod_cash_flow == 0`, return `0`
- Otherwise:
  - `initial_value = sod_value + sod_cash_flow`
  - `current_value = eod_value - eod_cash_flow - initial_value + management_fee_if_net`
  - `ror = current_value / abs(initial_value)`

### Current lotus-performance mapping

Primary engine path:

- [engine/ror.py](C:/Users/Sandeep/projects/lotus-performance/engine/ror.py)
  - `calculate_daily_ror(...)`

### Assessment

- `NET` basis fee inclusion: `Covered`
- `GROSS` basis fee exclusion: `Covered`
- zero initial-capital guard: `Covered`
- denominator uses `abs(begin_mv + bod_cf)`: `Covered`
- numerator shape: `Covered`
- exact formula parity: `Covered`

### Notes

Current implementation in `calculate_daily_ror(...)` is semantically the same:

- numerator:
  - `end_mv - bod_cf - begin_mv - eod_cf`
  - plus `mgmt_fees` when `metric_basis == "NET"`
- denominator:
  - `abs(begin_mv + bod_cf)`
- zero-denominator and pre-start dates are forced to zero through `safe_division_mask`

This is a strong match to the supplied formula.

### Current status

Status: `Covered`

## Formula 12: Sign

### Reference intent

Short summary from supplied formula:

- `start_sign = sign(sod_value + sod_cash_flow)`
- sign should update to `start_sign` when any of these are true:
  - first day of period
  - `previous_sign == start_sign`
  - current BOD cash flow is non-zero
  - previous EOD cash flow is non-zero
  - previous sign is zero
  - previous performance reset is true
- otherwise carry `previous_sign`

### Current lotus-performance mapping

Primary engine path:

- [engine/rules.py](C:/Users/Sandeep/projects/lotus-performance/engine/rules.py)
  - `calculate_sign(...)`

### Assessment

- `start_sign = sign(begin_mv + bod_cf)`: `Covered`
- first-day behavior: `Covered`
- current BOD cash flow flip trigger: `Covered`
- previous EOD cash flow flip trigger: `Covered`
- previous performance reset flip trigger: `Covered`
- carry previous sign otherwise: `Covered`
- explicit `previous_sign == start_sign` branch: `Implicitly Covered`
- explicit `previous_sign == 0` branch: `Partially Covered`

### Notes

Current engine implementation:

- computes `initial_sign = sign(begin_mv + bod_cf)`
- defines `is_flip_event` when:
  - current BOD cash flow is non-zero
  - or previous EOD cash flow is non-zero
  - or previous performance reset is true
- forces first row to be a flip event
- then forward-fills event signs across non-flip rows

This is very close semantically to the supplied formula.

Two nuances:

1. `previous_sign == start_sign`

- supplied formula explicitly sets current sign to `start_sign`
- current engine gets the same practical result because the forward-filled event sign
  remains unchanged when there is no flip boundary

2. `previous_sign == 0`

- supplied formula explicitly resets to `start_sign`
- current engine does not have a separate explicit zero-sign branch
- it may still behave equivalently depending on how `initial_sign` and event grouping play out
- but this is not as explicit as the supplied rule

### Current status

Status: `Mostly Covered`

This looks aligned enough for most scenarios, but the `previous_sign == 0` behavior is worth keeping in view.

## Formula 13: SodReset

### Reference intent

Short summary from supplied formula:

- `sod_reset =`
  - next-day BOD cash flow is non-zero
  - and next-day performance reset is true

So this is a specific forward-looking reset contributor.

### Current lotus-performance mapping

Primary engine paths inspected:

- [engine/rules.py](C:/Users/Sandeep/projects/lotus-performance/engine/rules.py)
- [engine/ror.py](C:/Users/Sandeep/projects/lotus-performance/engine/ror.py)
- [engine/compute.py](C:/Users/Sandeep/projects/lotus-performance/engine/compute.py)

### Assessment

- explicit `sod_reset` concept: `Not Covered`
- next-day cash-flow and next-day reset conjunction: `Not Covered`
- indirect approximation through broader reset logic: `Partially Covered`

### Notes

The current engine does not expose a standalone `sod_reset` flag.

There are broader rules that involve:

- next-day BOD cash flow in `cond_common`
- previous performance reset in `calculate_sign(...)`

But none of the inspected code represents the exact formula:

- `next_sod_cash_flow != 0`
- and `next_performance_reset is True`

as its own named or logically isolated reset input.

### Current status

Status: `Gap`

This reinforces the earlier finding that current `PERF_RESET` aggregation appears narrower than the supplied business model.

## Formula 5: NCtrl3

### Reference intent

Short summary from supplied formula:

- `NCtrl3` is `true` when:
  - `temp_long_cum_ror` exists
  - `temp_long_cum_ror != 0`
  - `temp_short_cum_ror` exists
  - `temp_short_cum_ror < -1`
  - `NCtrl.will_reset_performance(...)` is `true`

In percentage terms, this means:

- trigger reset when temporary short cumulative return is below `-100%`
- but only if long temporary cumulative return is not zero
- and only when the reset-permission condition is satisfied for the day

### Current lotus-performance mapping

Primary engine path:

- [engine/rules.py](C:/Users/Sandeep/projects/lotus-performance/engine/rules.py)
  - `calculate_initial_resets(...)`
- [engine/ror.py](C:/Users/Sandeep/projects/lotus-performance/engine/ror.py)
  - `calculate_cumulative_ror(...)`

Relevant fields:

- `PortfolioColumns.TEMP_LONG_CUM_ROR`
- `PortfolioColumns.TEMP_SHORT_CUM_ROR`
- `PortfolioColumns.NCTRL_3`
- `PortfolioColumns.PERF_RESET`

### Assessment

- `temp_short_cum_ror < -100%` threshold: `Covered`
- `temp_long_cum_ror != 0` companion condition: `Covered`
- dedicated `NCTRL_3` flag: `Covered`
- `will_reset_performance(...)` style gating condition: `Covered`
- exact same implementation shape: `No`

### Notes

The current implementation is:

- `cond_nctrl3 = (df[temp_short_col] < -100) & (df[temp_long_col] != 0)`
- then gated through the same `cond_common` used by `NCTRL_1` and `NCTRL_2`

So this is a strong semantic match to the supplied formula.

### Potential semantic difference to review later

As with `NCtrl1` and `NCtrl2`, the main remaining verification point is whether the engine’s
hardcoded `cond_common` exactly matches the intended business definition of
`NCtrl.will_reset_performance(...)`.

Current status: `Needs Verification`, but no obvious missing reset condition from this formula alone.

## Formula 4: NCtrl2

### Reference intent

Short summary from supplied formula:

- `NCtrl2` is `true` when:
  - `temp_short_cum_ror` exists
  - `temp_short_cum_ror > 1`
  - `NCtrl.will_reset_performance(...)` is `true`

In percentage terms, this means:

- trigger reset when temporary short cumulative return is above `100%`
- but only when the reset-permission condition is satisfied for the day

### Current lotus-performance mapping

Primary engine path:

- [engine/rules.py](C:/Users/Sandeep/projects/lotus-performance/engine/rules.py)
  - `calculate_initial_resets(...)`
- [engine/ror.py](C:/Users/Sandeep/projects/lotus-performance/engine/ror.py)
  - `calculate_cumulative_ror(...)`

Relevant fields:

- `PortfolioColumns.TEMP_SHORT_CUM_ROR`
- `PortfolioColumns.NCTRL_2`
- `PortfolioColumns.PERF_RESET`

### Assessment

- `temp_short_cum_ror > 100%` threshold: `Covered`
- dedicated `NCTRL_2` flag: `Covered`
- `will_reset_performance(...)` style gating condition: `Covered`
- exact same implementation shape: `No`

### Notes

The current implementation is:

- `cond_nctrl2 = df[temp_short_col] > 100`
- then gated through the same `cond_common` used by `NCTRL_1`

So semantically, this is the short-side sibling of the current `NCTRL_1` implementation.

### Potential semantic difference to review later

As with `NCtrl1`, the threshold is clearly aligned, but exact equivalence depends on whether
the intended business definition of `NCtrl.will_reset_performance(...)` is exactly the same
as the engine’s current `cond_common` rule.

Current status: `Needs Verification`, but no obvious missing reset condition from this formula alone.
