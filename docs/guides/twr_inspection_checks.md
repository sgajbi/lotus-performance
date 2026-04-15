# TWR Inspection Checks

This guide explains the current `lotus-performance` TWR inspector checks in operator language.

Use it when:

- support needs to explain why a TWR result is or is not supportable
- front office needs to understand what the inspector is validating
- engineering needs a quick map from finding code to owning repository and evidence artifact

The TWR inspector is a separate contract from `POST /performance/twr`.

The engine answers:

- what the return is

The inspector answers:

- whether that result is operationally supportable
- which defect pattern was detected
- which repository most likely owns the defect
- which evidence artifact backs that conclusion

## Surfaces

Primary endpoints:

- `POST /performance/inspections/twr`
- `GET /performance/inspections/{inspection_id}`
- `GET /performance/inspections/{inspection_id}/artifacts/{artifact_name}`

Primary artifacts:

- `inspection_summary.json`
- `findings.json`
- `source_quality_summary.json` when source-quality checks run
- `reconciliation_summary.json` when stateful reconciliation runs
- `source_economics_summary.json` when stateful source-economics checks run

## Verdicts

- `supportable`: no active finding undermines operational trust
- `supportable_with_warnings`: the result is usable but caveats exist or some check families are still pending
- `not_supportable`: at least one high-severity or critical finding is present
- `inspection_failed`: the inspection process could not complete truthfully

## Check Families

Current completed families:

- `calculation_consistency`
- `source_quality`
- `economic_plausibility`
- `reconciliation`
- `cashflow_classification`

## Finding Inventory

### Calculation Consistency

These findings are owned by `lotus-performance` and point to served-response arithmetic or linking defects.

| Code | Meaning | Typical Evidence |
| --- | --- | --- |
| `RELATIVE_PERFORMANCE_SUMMARY_MISMATCH` | relative summary return does not equal portfolio minus benchmark | expected vs actual return components |
| `RELATIVE_PERFORMANCE_CUMULATIVE_MISMATCH` | cumulative relative return does not equal cumulative portfolio minus benchmark | expected vs actual cumulative components |
| `RELATIVE_BREAKDOWN_CARDINALITY_MISMATCH` | relative breakdown rows do not line up with portfolio and benchmark rows | row counts by block |
| `RELATIVE_BREAKDOWN_PERIOD_MISMATCH` | relative breakdown period return does not equal portfolio minus benchmark for the same bucket | expected vs actual bucket values |
| `RELATIVE_BREAKDOWN_CUMULATIVE_MISMATCH` | relative breakdown cumulative return does not equal portfolio minus benchmark for the same bucket | expected vs actual bucket values |
| `PORTFOLIO_BREAKDOWN_LINK_MISMATCH` | portfolio breakdown buckets do not geometrically link to the served summary | linked return vs served summary |
| `BENCHMARK_BREAKDOWN_LINK_MISMATCH` | benchmark breakdown buckets do not geometrically link to the served summary | linked return vs served summary |

Primary evidence surface:

- `findings.json`

### Source Quality And Plausibility

These findings are currently owned by `lotus-performance` because they evaluate the resolved input series that the service is using.

| Code | Meaning | Typical Evidence |
| --- | --- | --- |
| `WEEKEND_OBSERVATIONS_PRESENT` | resolved valuation inputs include weekend dates | weekend date list and count |
| `BUSINESS_DATE_GAPS_PRESENT` | business-day sequence has gaps between first and last observation | missing business dates and count |
| `STALE_VALUATION_SERIES_DETECTED` | unchanged valuation state repeats across multiple observations with zero cash-flow and fee activity | stale run start/end dates, run length, repeated begin/end market values |
| `NONPOSITIVE_DAILY_CAPITAL_BASE_DETECTED` | one or more observations have `begin_mv + bod_cf <= 0`, so daily move plausibility cannot be interpreted normally | affected dates, `begin_mv`, `bod_cf`, effective capital base |
| `EXTREME_DAILY_MOVE_DETECTED` | one or more daily moves exceed the profile threshold | threshold percent and sampled extreme dates |

Primary evidence surfaces:

- `source_quality_summary.json`
- `inspection_summary.json`
- `findings.json`

### Reconciliation

These findings are currently routed to `lotus-core` because they compare portfolio and position source-state coherence.

| Code | Meaning | Typical Evidence |
| --- | --- | --- |
| `MIXED_POSITION_EPOCH_SNAPSHOT` | multiple position snapshot epochs are served for the same valuation date | affected dates and count |
| `DUPLICATE_POSITION_SNAPSHOT_ROW_PRESENT` | duplicate rows are served for the same valuation date, position id, and snapshot epoch | affected dates, positions, epochs, duplicate counts |
| `INVALID_POSITION_EPOCH_PRESENT` | one or more position rows use missing or non-numeric snapshot epoch labels | affected dates, positions, epoch field, raw epoch value |
| `INVALID_POSITION_END_VALUE_PRESENT` | latest selected position rows include missing, blank, or non-numeric ending market values | affected dates, positions, raw values, epochs |
| `PORTFOLIO_POSITION_RECONCILIATION_GAP` | served portfolio end value does not tie to the latest coherent position-state total | gap dates, samples, max gap amount |
| `POSITION_BEGIN_VALUE_CARRY_FORWARD_BREAK` | a position's current beginning market value does not carry forward from its prior selected ending market value and no source activity explains the transition | position id, prior date, current date, prior end value, current begin value, gap amount |

Primary evidence surfaces:

- `reconciliation_summary.json`
- `findings.json`

### Cash-Flow Classification And Source Economics

These findings evaluate whether raw source cash and fee economics tie to the served TWR valuation points.

#### Fee findings

| Code | Owner | Meaning | Typical Evidence |
| --- | --- | --- | --- |
| `FEE_CASHFLOW_CLASSIFICATION_NOT_PRESERVED` | `lotus-performance` | upstream fee economics do not tie to served `mgmt_fees` | expected fee amount, source kind, normalized `mgmt_fees` |
| `DUPLICATE_FEE_SOURCE_SIGNAL` | `lotus-core` | detailed fee rows and explicit fee total repeat the same fee economics | explicit fee amount and detailed fee amount |
| `FEE_SOURCE_TOTAL_MISMATCH` | `lotus-core` | detailed fee rows and explicit fee total disagree | explicit fee amount and detailed fee amount |
| `POSITIVE_FEE_SOURCE_SIGNAL` | `lotus-core` | fee economics are served with a positive sign | positive fee sample and date |

#### External cash-flow findings

| Code | Owner | Meaning | Typical Evidence |
| --- | --- | --- | --- |
| `EXTERNAL_CASHFLOW_NORMALIZATION_MISMATCH` | `lotus-performance` | upstream external cash-flow economics do not tie to served `bod_cf` or `eod_cf` | expected bod/eod amount, source kind, normalized bod/eod values |
| `DUPLICATE_EXTERNAL_CASHFLOW_SOURCE_SIGNAL` | `lotus-core` | detailed external rows and explicit bod/eod aggregate repeat the same economics | explicit amount, detailed amount, timing |
| `EXTERNAL_CASHFLOW_SOURCE_TOTAL_MISMATCH` | `lotus-core` | detailed external rows and explicit bod/eod aggregate disagree | explicit amount, detailed amount, timing |
| `EXTERNAL_CASHFLOW_TIMING_BUCKET_CONTRADICTION` | `lotus-core` | explicit external cash-flow total is served in one timing bucket while detailed rows exist only in the opposite timing bucket | explicit timing, opposite detailed timing, sampled amounts |
| `CONFLICTING_EXPLICIT_SOURCE_TOTAL_PRESENT` | `lotus-core` | raw source serves conflicting numeric alias fields for the same explicit fee or bod/eod total | valuation dates, alias field names, resolved and conflicting values |
| `INVALID_EXPLICIT_SOURCE_AMOUNT_PRESENT` | `lotus-core` | raw source serves malformed explicit fee or bod/eod cash-flow totals | valuation dates, explicit field names, raw field values |
| `INVALID_CASHFLOW_AMOUNT_PRESENT` | `lotus-core` | raw source serves one or more detailed cash-flow rows with unusable amount values | valuation dates, raw row amounts, row timings, row cash-flow types |
| `INVALID_CASHFLOW_TIMING_PRESENT` | `lotus-core` | raw source serves one or more detailed cash-flow rows with unusable timing labels | valuation dates, row timings, row amounts, row cash-flow types |
| `MISSING_CASHFLOW_TYPE_PRESENT` | `lotus-core` | raw source serves one or more detailed cash-flow rows without a usable `cash_flow_type` label | valuation dates, row timings, row amounts |
| `NONCANONICAL_CASHFLOW_TYPE_PRESENT` | `lotus-core` | raw source serves a `cash_flow_type` outside the current governed inspection vocabulary | valuation dates and unsupported cash-flow type labels |
| `GOVERNED_ALIAS_CASHFLOW_TYPE_PRESENT` | `lotus-core` | raw source serves a mappable cash-flow alias such as `management_fee`, `deposit`, or `withdrawal` instead of the canonical analytics-input labels | valuation dates, alias labels, mapped rows |
| `UNSUPPORTED_CASHFLOW_TYPE_PRESENT` | `lotus-core` | raw source serves labels such as `dividend`, `coupon`, `interest`, `tax`, or another value whose TWR source-economics role is not yet governed | valuation dates, unsupported labels, preserved rows |

Primary evidence surfaces:

- `source_economics_summary.json`
- `findings.json`

## How To Read The Artifacts

### `inspection_summary.json`

Use for:

- verdict
- top-level evidence summary
- completed and pending check families
- artifact inventory

### `findings.json`

Use for:

- full finding list
- finding severity
- owning repository
- recommended action
- sampled structured evidence

### `reconciliation_summary.json`

Use for:

- mixed-epoch date counts
- duplicate snapshot counts and sampled rows
- invalid epoch counts and sampled rows
- invalid selected-position value counts and sampled rows
- portfolio-versus-position gap counts
- max gap amounts
- sampled gap rows
- position begin-value carry-forward break counts and sampled rows

### `source_economics_summary.json`

Use for:

- fee and external cash-flow date counts
- normalization mismatch counts
- duplicate source-signal counts
- source-total mismatch counts
- timing-bucket contradiction counts
- conflicting explicit-source amount date counts
- invalid explicit-source amount date counts
- invalid cash-flow amount date counts
- invalid cash-flow timing date counts
- missing cash-flow type date counts
- non-canonical cash-flow type date counts
- governed alias cash-flow type date counts
- unsupported cash-flow type date counts
- sampled fee and external source-economics anomalies

Key support-facing sample fields:

- `external_cashflow_timing_contradiction_samples[*].explicit_timing`
- `external_cashflow_timing_contradiction_samples[*].opposite_detailed_timing`
- `external_cashflow_timing_contradiction_samples[*].explicit_cashflow_amount`
- `external_cashflow_timing_contradiction_samples[*].opposite_detailed_cashflow_amount`
- `noncanonical_cashflow_type_samples[*].cash_flow_types`
- `noncanonical_cashflow_types`
- `governed_alias_cashflow_type_samples[*].cash_flow_types`
- `unsupported_cashflow_type_samples[*].cash_flow_types`

Taxonomy handling:

- canonical source labels remain `fee` and `external_flow`
- governed aliases such as `management_fee`, `deposit`, `withdrawal`, and `subscription` are mapped to fee-like or external-flow economics by stateful valuation normalization and by inspection, but still produce alias-governance evidence
- unsupported labels such as `dividend`, `coupon`, `interest`, `tax`, and `distribution` are preserved as source-taxonomy evidence and excluded from fee or external normalization until their TWR economics are explicitly governed
- operational expenses must be emitted by `lotus-core` as canonical `cash_flow_type="fee"` with `flow_scope="operational"` and source lineage such as `source_classification="EXPENSE"`; `cash_flow_type="expense"` is not a governed analytics-input label

Bounded stale-series rule:

- the current stale-series finding triggers only when at least three observations repeat the same `begin_mv`, `end_mv`, `bod_cf`, `eod_cf`, and `mgmt_fees`
- the repeated run must also have zero cash-flow and fee activity
- this is intentionally a stale-source signal, not a claim that flat economics are impossible

### `source_quality_summary.json`

Use for:

- weekend date lists and counts
- missing business-date lists and counts
- stale-series run counts, run details, and observation counts
- nonpositive daily capital-base counts and sampled dates
- extreme daily move threshold and sampled dates

## Operator Notes

- A mathematically coherent TWR result can still be `not_supportable`.
- `lotus-performance` findings usually point to response construction or normalization defects inside this repository.
- `lotus-core` findings usually point to raw stateful source semantics, aggregation, timing, or reconciliation defects upstream.
- `POSITION_BEGIN_VALUE_CARRY_FORWARD_BREAK` is the main check for the defect pattern where a position's prior
  ending market value disappears from the next beginning market value without a cash-flow, trade, or quantity
  transition explaining the move. This pattern can create implausible TWR even when end-of-day portfolio and
  position totals still reconcile.
- The absence of a finding is not the same thing as a universal clean bill of health. Check `completed_check_families` and `pending_check_families` in `inspection_summary.json`.

## Current Scope Boundary

The current inspector does not yet cover every possible source taxonomy or every production anomaly pattern.

The present check inventory is intentionally bounded and biased toward:

- deterministic arithmetic checks
- supportable source-quality signals
- explicit stateful reconciliation evidence
- raw source-economics contradictions that can be explained clearly to operators
