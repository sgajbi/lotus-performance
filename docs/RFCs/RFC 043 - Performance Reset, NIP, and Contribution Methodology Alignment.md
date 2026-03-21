# RFC 043 - Performance Reset, NIP, and Contribution Methodology Alignment

| Field | Value |
| --- | --- |
| Status | Partially Implemented |
| Created | 2026-03-21 |
| Last Updated | 2026-03-21 |
| Owners | lotus-performance |
| Depends On | RFC-001, RFC-004, RFC-014, RFC-017, RFC-018, RFC-020, RFC-029, RFC-042 |
| Related Standards | RFC-028 no-alias naming; lotus-platform cross-app validation workflows |
| Scope | In repo |

## Executive Summary

This RFC proposes a controlled methodology-alignment program for the performance engine family.

The current `lotus-performance` implementation is materially functional and already contains the
core daily return and long/short cumulative-return machinery. The formula review performed in
March 2026 does **not** indicate that the basic TWR engine must be rewritten.

The review does indicate a smaller set of concentrated methodology risks:

- reset semantics are likely incomplete relative to the intended domain model
- `NIP` semantics and `NIP` day counting likely differ from the intended model
- contribution average-weight methodology is simpler than the intended reset-aware model
- grouped contribution return orchestration may not fully inherit portfolio reset semantics
- smoothing is materially simpler than the richer reference framework

The quant conclusion from this review is:

1. keep the current daily RoR and long/short compounding foundation
2. do **not** blindly port every reference class or every orchestration object
3. first align reset semantics, `NIP` semantics, and contribution average-weight methodology
4. add stronger cross-surface reconciliation tests before changing more advanced contribution
   smoothing behavior
5. treat the richer smoothing and orchestration patterns as phase-2 work, not day-1 blockers

This RFC therefore defines a slice-based implementation plan that changes the system slowly,
validates each slice in isolation, and only proceeds when the prior slice has characterization and
cross-surface evidence.

## Original Requested Requirements (Preserved)

The original asks preserved from the review loop were:

- compare externally supplied reference formulas against current `lotus-performance`
- verify that required business conditions are not being lost, even when the implementation shape
  differs
- identify whether `NCTRL` controls are genuinely required or whether some are redundant
- ensure performance, returns-series, contribution, attribution, and benchmark-aware surfaces
  tell the same story through different lenses
- standardize semantic language where possible and avoid silent drift in units or contract meaning
- prepare a change RFC that implements learning gradually in slices, with verification after each
  slice before moving on

## Current Implementation Reality

### Implementation status by slice

| Slice | Current state | Evidence |
| --- | --- | --- |
| Slice 0: Characterization and visibility | Implemented | `engine/compute.py`, `engine/diagnostics.py`, `core/envelope.py`, `tests/unit/engine/test_compute.py`, `tests/integration/test_performance_api.py` |
| Slice 1: Canonical reset model | Deferred after characterization | Active reset remains current production model; canonical reset remains shadowed in `engine/compute.py` diagnostics |
| Slice 2: Canonical `NIP` semantics and valid-day accounting | Partially implemented | Reset-relative day accounting is active; stricter canonical `NIP` rule remains shadowed |
| Slice 3: Contribution average-weight methodology alignment | Implemented with controlled rollout | `app/services/contribution_service.py`, `app/models/contribution_responses.py`, `tests/integration/test_contribution_api.py`, `scripts/contribution_rollout_readiness_report.py` |
| Slice 4: Grouped-return and cross-surface tie-out alignment | Implemented for current reset-heavy characterization scope | `app/services/contribution_service.py`, `tests/e2e/test_workflow_journeys.py` |
| Slice 5: Attribution and benchmark-aware tie-out hardening | Deferred | No RFC-043-specific additional attribution/benchmark hardening beyond current baseline |
| Slice 6: Smoothing parity decision | Deferred | Carino remains active with explicit domain guardrails in `engine/contribution.py` |

### What appears fundamentally sound

Code and review evidence indicate that the following core behaviors are already materially present:

- daily rate-of-return calculation in [engine/ror.py](C:/Users/Sandeep/projects/lotus-performance/engine/ror.py)
- sign-aware long/short cumulative return compounding in
  [engine/ror.py](C:/Users/Sandeep/projects/lotus-performance/engine/ror.py)
- sign derivation from `begin_mv + bod_cf` with flip events in
  [engine/rules.py](C:/Users/Sandeep/projects/lotus-performance/engine/rules.py)
- reset controls `NCTRL_1`, `NCTRL_2`, `NCTRL_3`, `NCTRL_4` in
  [engine/rules.py](C:/Users/Sandeep/projects/lotus-performance/engine/rules.py)
- contribution calculation and Carino smoothing in
  [engine/contribution.py](C:/Users/Sandeep/projects/lotus-performance/engine/contribution.py)
- cross-surface consistency proofing in
  [tests/e2e/test_workflow_journeys.py](C:/Users/Sandeep/projects/lotus-performance/tests/e2e/test_workflow_journeys.py)

### What appears materially incomplete or simplified

The formula review and code inspection indicate likely methodology gaps in these areas:

- `performance_reset` currently aggregates `NCTRL_1..4`, but does not explicitly include
  `sod_reset` or `account_performance_reset`
- reset diagnostics already expose partial reason codes for `NCTRL_1..4` in
  [engine/compute.py](C:/Users/Sandeep/projects/lotus-performance/engine/compute.py), but not a
  canonical reset-reason model spanning all intended reset sources
- `NIP` has two rule variants, and the current default rule is looser than the stricter reference
  formulation
- `NIP` days in diagnostics are counted across the full reporting window, not only since the last
  performance reset boundary
- contribution average weights are currently simple arithmetic means of daily weights, not the
  reset-aware and `NIP`-adjusted denominator model suggested by the reference formulas
- grouped contribution return calculation is simpler than the reference grouped-return state model
- smoothing is currently Carino-based and materially simpler than the richer long/short log-based
  reference framework
- the sign model looks broadly correct, but the explicit `previous_sign == 0` recovery branch from
  the reference formulas is not modeled as explicitly and should be characterized before reset/NIP
  changes land
- richer reference orchestration includes `next_performance_reset`, `account_performance_reset`,
  and explicit tax-aware/grouped-return state propagation that are not yet clearly modeled in the
  contribution-side grouped return path

### What appears architectural rather than methodological

Some supplied formulas describe a richer reference architecture rather than a necessary functional
 requirement:

- `MetricFactory`
- `MetricCalculator`
- `RequestParameters`
- `PortfolioParameters`
- explicit intermediate archival model types such as `GroupDailyWeight -> DailyWeight`

These patterns may improve traceability and auditability, but they are not the highest-priority
drivers of output correctness.

## Requirement-to-Implementation Traceability

| Requirement / domain question | Current implementation evidence | Current assessment | RFC decision |
| --- | --- | --- | --- |
| Daily RoR formula should remain economically correct for NET/GROSS basis | [engine/ror.py](C:/Users/Sandeep/projects/lotus-performance/engine/ror.py) `calculate_daily_ror(...)` | Covered | Keep current base formula |
| Long/short cumulative return state should compound geometrically and remain sign-aware | [engine/ror.py](C:/Users/Sandeep/projects/lotus-performance/engine/ror.py) `_compound_ror(...)` | Covered | Keep current long/short engine foundation |
| Reset thresholds `NCTRL_1..3` should guard invalid cumulative return states | [engine/rules.py](C:/Users/Sandeep/projects/lotus-performance/engine/rules.py) `calculate_initial_resets(...)` | Mostly aligned | Retain concept; validate exact gating |
| Reset aggregation should include all intended reset sources | [engine/ror.py](C:/Users/Sandeep/projects/lotus-performance/engine/ror.py), [engine/rules.py](C:/Users/Sandeep/projects/lotus-performance/engine/rules.py) | Partially implemented | Add explicit canonical reset-reason model |
| `NCTRL_4` should be justified by boundary semantics, not historical accident | [engine/rules.py](C:/Users/Sandeep/projects/lotus-performance/engine/rules.py) `calculate_nctrl4_reset(...)` | Needs deeper review | Keep provisionally, then rebaseline by characterization |
| Sign propagation should remain stable around zero-sign and reset boundary transitions | [engine/rules.py](C:/Users/Sandeep/projects/lotus-performance/engine/rules.py) `calculate_sign(...)` | Mostly aligned | Characterize explicitly; change only if reset/NIP slices reveal a real mismatch |
| `NIP` should reflect true no-investment semantics | [engine/rules.py](C:/Users/Sandeep/projects/lotus-performance/engine/rules.py) `calculate_nip(...)` | Partially implemented | Move to stricter canonical rule after shadow validation |
| `NIP` days and valid days should be reset-aware | [engine/compute.py](C:/Users/Sandeep/projects/lotus-performance/engine/compute.py) diagnostics | Gap | Add reset-relative `nip_days_since_reset` / `valid_days` |
| Contribution average weight should respect reset boundaries and `NIP` days | [engine/contribution.py](C:/Users/Sandeep/projects/lotus-performance/engine/contribution.py), [app/services/contribution_service.py](C:/Users/Sandeep/projects/lotus-performance/app/services/contribution_service.py) | Gap | Implement phased methodology alignment |
| Contribution/group return should reconcile to performance using the same reset logic | [engine/contribution.py](C:/Users/Sandeep/projects/lotus-performance/engine/contribution.py), [tests/e2e/test_workflow_journeys.py](C:/Users/Sandeep/projects/lotus-performance/tests/e2e/test_workflow_journeys.py) | Partially implemented | Add grouped-return alignment slice with explicit account-reset / next-reset characterization |
| Smoothing should match the exact rich reference framework | [engine/contribution.py](C:/Users/Sandeep/projects/lotus-performance/engine/contribution.py) | Gap, but not first-order blocker | Defer until base methodology is aligned |

## Design Reasoning and Trade-offs

### 1. Not every reference class should be copied

The supplied formulas clearly describe a richer domain model than the current code. That does not
mean every class, dataclass, or orchestration object must be copied one-for-one.

The correct engineering goal is:

- preserve the intended business conditions
- preserve cross-surface reconciliation
- minimize unnecessary architectural churn

This RFC therefore separates:

- **methodology-critical gaps**
- from **architectural parity ideas**

### 2. `NCTRL` controls are still likely needed

The current review does **not** support removing `NCTRL` controls wholesale.

Quant reasoning:

- `NCTRL_1` and `NCTRL_2` protect against invalid cumulative states after crossing `-100%` or
  `+100%` style boundaries
- `NCTRL_3` protects a mixed-state boundary involving both long and short cumulative components
- `NCTRL_4` appears intended to govern transition behavior around investment/no-investment
  boundaries and cash-flow events

RFC decision:

- keep `NCTRL_1..3`
- keep `NCTRL_4` provisionally
- add reset-reason diagnostics and characterization before any attempt to delete or rewrite
  `NCTRL_4`

### 3. `NIP` and reset-relative day counting are likely higher value than smoothing parity

If the portfolio and contribution engines disagree about:

- when performance resets
- what counts as a no-investment day
- which days count in average-weight denominators

then the system can tell subtly different stories even if smoothing is mathematically elegant.

So the order of value is:

1. reset semantics
2. `NIP` semantics
3. valid-day counting
4. contribution average-weight methodology
5. grouped-return alignment
6. smoothing parity

### 4. Smoothing parity should be deferred until unsmoothed methodology ties

The richer smoothing formulas describe a more advanced reference model, but smoothing is not the
first place to spend risk budget. If the underlying unsmoothed contribution and grouped-return
methodology is not fully aligned, changing smoothing first would make the system harder to reason
about.

RFC decision:

- preserve current Carino smoothing for now
- revisit richer smoothing only after reset / `NIP` / average-weight alignment is complete

### 5. Cross-surface consistency is the acceptance standard

The final acceptance bar is not “this formula exists in code.”

The bar is:

- TWR, returns-series, contribution, attribution, and benchmark-aware surfaces tell the same
  portfolio story through different analytic lenses
- differences are explained by methodology, not by silent drift in state handling

### 5a. Promotion readiness must explain both candidates and blockers

For reset-aware `average_weight`, rollout telemetry is only useful if it answers two distinct
questions:

- which material-shadow periods are structurally clean enough to promote
- which material-shadow periods are still blocked, and why

The implementation now treats the following as first-class blocker reasons for shadow-only periods:

- weight residual: emitted position weights do not sum cleanly to `100%`
- flow balance: position-level stock and cash legs do not cancel cleanly
- reset alignment: portfolio and position reset boundaries do not line up
- timeseries reconciliation: emitted daily contribution series still drift from the residual-adjusted period total

This prevents rollout decisions from collapsing all “not promoted” periods into one opaque bucket.
The service now reports both:

- `average_weight_shadow_blocked_periods`: the union count of material-shadow periods that were not
  promotion-ready
- `average_weight_shadow_blocked_by_*_periods`: the reason-level breakdown for those blocked slices

### 6. Reset decisions must be justified by when geometric linking stops making economic sense

The governing principle for performance resets is:

- keep geometric linking when the portfolio still represents one continuous invested capital path
- reset when geometric linking becomes economically nonsensical even if it remains mathematically
  computable

Resets therefore exist to protect meaning, not just to satisfy a historical formula.

Implementation guardrail:

- do not preserve or introduce reset conditions merely because they existed in a reference engine
- every surviving branch must map to a reachable portfolio state and a defensible economic reason
  that geometric linking should stop or restart

## Reset Decision Matrix

| Real portfolio condition | Why geometric linking may fail or remain valid | Reset intent |
| --- | --- | --- |
| Healthy positive-capital portfolio with ordinary subscriptions or withdrawals | The capital path remains economically continuous even though cash flows must be neutralized in daily return calculation | Usually do **not** reset |
| Fee-only day in a healthy portfolio | Fees affect return, but do not by themselves break continuity of invested capital | Do **not** reset |
| Full liquidation to zero market value | The invested episode is effectively closed; continuing to link returns across that boundary overstates continuity | Reset is economically justified |
| Re-entry after a zero-capital day | A new investment episode begins; geometric linking to the prior closed episode is misleading | Reset is economically justified |
| Capital crosses through zero or effective capital becomes negative | Return interpretation becomes unstable or non-standard; a normal compounded path may no longer be meaningful | Reset is a strong candidate |
| Long-to-short or short-to-long transition with a real financing/capital event | The economic nature of the position changes and can invalidate a single compounded path | Reset is a strong candidate |
| Recapitalization after a broken cumulative-return state | New capital is restarting the invested experience rather than extending the old one | Reset is economically justified |
| Month-end or report-end boundary with no economic discontinuity | This is a reporting governance boundary, not necessarily an economic one | Reset only if explicitly intended by methodology/policy |

This matrix governs how later slices should evaluate `account_reset`, `sod_reset`, and `NCTRL_4`:

- if a control maps to a real economic discontinuity, it is a stronger candidate for the final
  canonical reset model
- if it maps only to technical convenience, it should stay shadow-only or be removed

## Current Characterization Decision Table

Based on the implemented scenario characterization and reset-overlap diagnostics as of
`2026-03-21`, the current working decision is:

| Reset reason | Current status | Evidence so far | Working decision |
| --- | --- | --- | --- |
| `NCTRL_1` | Active | Fires on collapse boundaries where the capital path already stopped behaving like a normal compounded stream | Keep active |
| `NCTRL_2` | Active | Still represents an extreme cumulative short-state breach; no characterization evidence suggests it is redundant | Keep active |
| `NCTRL_3` | Active | Still represents a mixed long/short broken-state boundary; no characterization evidence suggests it is redundant | Keep active |
| `NCTRL_4` | Active | Characterization now shows cases with `nctrl4_exclusive_reset_days > 0`, which means it is not merely duplicating shadow reasons in all tested scenarios | Keep active provisionally |
| `account_reset` | Shadow-only | Produces `shadow_only_candidate_reset_days` in healthy-flow scenarios without yet proving that live compounding should break there | Keep shadow-only for now |
| `sod_reset` | Shadow-only | Often explains candidate boundaries around recapitalizing opens, but can also overlap with active resets rather than adding distinct value | Keep shadow-only for now |

Interpretation:

- `NCTRL_1..3` remain the mathematically strongest reset reasons
- `NCTRL_4` still has enough unique signal to survive the current slice
- `account_reset` and `sod_reset` are useful characterization reasons, but not yet justified as
  active compounding inputs

Promotion criteria for shadow reasons:

- they must improve economic meaning in a reachable portfolio scenario
- they must not fragment ordinary subscription / fee-only paths
- they must improve cross-surface consistency after TWR, contribution, and grouped-return
  verification

## Current NIP Decision Table

Based on the implemented NIP shadow diagnostics as of `2026-03-21`, the current working decision
is:

| NIP concept | Current status | Evidence so far | Working decision |
| --- | --- | --- | --- |
| Legacy offsetting-flow rule (`nip_rule_v1`) | Active | Still drives production `nip`, and `nip_rule_delta_days` proves there are reporting-slice cases where it disagrees with the stricter rule | Keep active temporarily |
| Stricter zero-effective-capital rule (`nip_rule_v2`) | Shadow-only | Cleaner domain semantics for no-investment periods, but not yet promoted because the product still needs targeted regression and contribution-denominator validation | Keep shadow-only for now |
| Reset-relative day counts | Active diagnostics | `nip_days_since_last_reset` and `valid_days_since_last_reset` now make the post-reset denominator visible | Keep and use as the bridge into contribution average-weight alignment |

Promotion criteria for the stricter NIP rule:

- it must preserve or improve business meaning in zero-investment edge cases
- it must not create unexplained drift across TWR, contribution, and grouped-return stories
- it must be validated together with reset-relative valid-day counting, not in isolation

## Gap Assessment

### Methodology-critical gaps

1. `performance_reset` aggregation likely incomplete
2. `NIP` default rule likely too loose
3. `NIP` / valid-day counting not reset-relative
4. contribution average-weight denominator too simple
5. grouped contribution return likely under-propagates reset semantics
6. sign behavior around zero-sign transition is not obviously wrong, but is not explicit enough to
   leave uncharacterized while reset semantics change

### Important but second-order gaps

1. `NCTRL_4` exact semantics need explicit revalidation
2. reset gating currently includes next-day BOD cash flow in a way that may or may not match the
   intended domain rule
3. smoothing is simpler than the richer reference model
4. richer grouped-return orchestration includes tax- and next-reset-aware concepts that are not
   currently explicit in the engine

### Architectural gaps with lower immediate business impact

1. explicit `MetricCalculator` / `MetricFactory`
2. `RequestParameters` object boundary
3. `PortfolioParameters` packaging
4. richer intermediate archival object model

## Deviations and Evolution Since Original RFCs

This RFC extends and partially supersedes narrower enhancement expectations in earlier documents:

- RFC-004 expected contribution hardening; this RFC provides a more complete methodology basis for
  that work
- RFC-014 expected more consistent diagnostics and control semantics; this RFC makes reset/NIP
  semantics part of that consistency model
- RFC-017 implemented contribution enhancements, but not the richer reset-aware average-weight
  methodology implied by the reference formulas
- RFC-018 attribution reconciliation remains relevant and will benefit from upstream consistency in
  grouped-return semantics

## Proposed Changes

### Slice 0: Characterization and visibility

Goal:

- make reset and `NIP` behavior observable before changing logic

Changes:

- add internal diagnostics / trace columns for:
  - reset reasons
  - `NCTRL_1..4`
  - `sod_reset_shadow`
  - `account_reset_shadow`
  - `nip_rule_v1`
  - `nip_rule_v2`
  - `nip_days_since_last_reset`
  - `valid_days_since_last_reset`
- extend the existing reset-event diagnostic model in
  [engine/compute.py](C:/Users/Sandeep/projects/lotus-performance/engine/compute.py) rather than
  replacing it from scratch
- add scenario-based unit tests that characterize:
  - boundary returns
  - month-end resets
  - cash-flow-triggered resets
  - `NIP` days around zero-investment windows
  - zero-sign recovery / sign-stability scenarios

Decision rule:

- no behavior change yet
- this slice is observability and comparison only

### Slice 1: Canonical reset model

Goal:

- define and implement a canonical reset-reason framework

Changes:

- introduce explicit reset reasons:
  - `account_performance_reset`
  - `sod_reset`
  - `nctrl1`
  - `nctrl2`
  - `nctrl3`
  - `nctrl4`
- keep `NCTRL_1..3`
- keep `NCTRL_4` but recast it in a named, testable boundary rule
- compute `perf_reset` as the canonical OR over all enabled reasons

Decision rule:

- do not remove any `NCTRL` until characterization proves redundancy
- `NCTRL_4` can only be removed if:
  - shadow diagnostics show zero incremental reset value across characterized scenarios, and
  - cross-surface outputs remain stable

### Slice 2: Canonical `NIP` semantics and valid-day accounting

Goal:

- make no-investment semantics explicit and reset-relative

Changes:

- adopt the stricter canonical `NIP` rule after shadow validation
- remove the legacy offsetting-cash-flow default path once validated
- compute:
  - `nip_days_since_last_reset`
  - `valid_days_since_last_reset`

Decision rule:

- because the product is not yet live, backward compatibility is not required
- however, the switch should still be made only after characterization and targeted regression tests

### Slice 3: Contribution average-weight methodology alignment

Goal:

- align contribution weights with reset-aware performance methodology

Changes:

- replace simple arithmetic mean average-weight denominator with a reset-aware valid-day model
- exclude `NIP` days from valid-day denominator
- exclude pre-final-reset history from the averaging window
- explicitly decide whether to include a tiny acquisition-day fallback weight
  (`0.0001`) after characterization on synthetic and seeded real scenarios

Decision rule:

- implement only after Slices 1 and 2 are green
- verify contribution total still ties to portfolio return

## Current Contribution Average-Weight Decision Table

Based on the implemented shadow denominator characterization as of `2026-03-21`, the current
working decision is:

| Contribution weight concept | Current status | Evidence so far | Working decision |
| --- | --- | --- | --- |
| Simple arithmetic mean of `daily_weight` | Active | Still drives the public `average_weight` output and keeps the endpoint stable | Keep active temporarily |
| Reset-aware valid-day denominator | Shadow-only | Characterization now shows both zero-delta scenarios and scenarios where the shadow materially differs after resets or NIP days | Keep shadow-only for now |
| `average_weight_shadow_delta_positions` audit count | Active audit signal | Tells us how many position-period rows would change under the reset-aware denominator | Keep and expand |

Promotion criteria for the reset-aware denominator:

- it must improve business meaning in reset-heavy or NIP-heavy periods
- it must preserve contribution-to-TWR tie-out
- it must be rolled out together with grouped-return validation, not as an isolated formatting change

Current grouped-return characterization signal:

- contribution now records when `portfolio_reset_days` and `position_reset_days` diverge
- that audit signal is intentionally non-invasive: it does not change contribution outputs yet
- it exists to tell us whether grouped return state is already aligned enough for a denominator
  cutover, or whether reset propagation needs to be tightened first

Working grouped-return interpretation:

- if `portfolio_reset_without_position_reset_days = 0` and
  `position_reset_without_portfolio_reset_days = 0`, grouped return state is behaving consistently
  for that scenario
- if either counter is non-zero, contribution may still reconcile numerically while carrying a
  different reset story than portfolio TWR

Latest characterization result:

- the reset-heavy end-to-end scenario initially proved that zero reset-day divergence did not
  guarantee contribution-to-TWR tie-out
- that top-line gap is now closed by using a reset-aware period portfolio return in contribution
- the daily-series gap is now also closed for the characterized reset-heavy path by allocating each
  position's residual-adjusted period contribution back across its daily series
- the same scenario also confirms a separate guardrail now implemented in code:
  Carino smoothing stops being valid once a linked gross return factor leaves the positive log
  domain, so the contribution engine now falls back to raw daily contribution arithmetic and emits
  `carino_invalid_domain_days` as an audit signal

RFC implication:

- reset-day alignment remains necessary, but not sufficient
- reset-aware top-line period-return alignment is now active and no longer just a characterization
  target
- residual-aware daily-series linking is now active for the characterized reset-heavy path as well
- the newer multi-position reset-heavy characterization also preserves top-line and daily-series
  tie-out, which means the remaining gap now looks less like basic reset semantics and more like
  whether the chosen residual allocation rule remains the best business explanation in richer
  multi-position episodes
- the new asymmetric multi-position characterization strengthens that same conclusion: once one
  position clearly drives the break while another mostly rides through it, the system still ties
  out, but the main remaining pressure shows up in `average_weight_shadow_delta_positions` rather
  than in reset counters or daily-series reconciliation
- the contribution audit layer now quantifies that pressure with
  `average_weight_shadow_delta_max_bp` and `average_weight_shadow_delta_sum_bp`, so future cutover
  decisions can be based on magnitude, not just on whether any delta exists
- the contribution audit layer now also reports `average_weight_sum_residual_bp` so the service can
  prove that emitted position average weights still add to 100% apart from tiny residual drift
- a companion invariant should be carried into the next contribution hardening slice: position-level
  internal cash flows should net to zero when both offsetting legs sit inside the visible scope, so
  any persistent non-zero residual at the summed position-flow level should be treated as a
  non-flow-neutral scoped slice rather than silently normalized away
- the business reason is straightforward: for internal reallocations, the stock leg and the cash
  leg should cancel each other across positions. That cancellation is part of what lets summed
  position contribution still reconcile to the portfolio return instead of drifting away from it
- that invariant is now characterized through `position_flow_residual_days`, which keeps flow-book
  completeness visible without yet turning the condition into a hard validation failure
- the audit layer now also reports `position_flow_residual_max_bp` and
  `position_flow_residual_sum_bp` so we can distinguish rounding dust from a materially
  non-flow-neutral scoped slice before deciding whether this should become a harder rollout fence
- Slice 4 therefore remains mandatory before any claim that reset-aware contribution methodology is
  production-ready

#### Flow Residual Interpretation Table

| Signal | Working interpretation | Recommended action |
| --- | --- | --- |
| `position_flow_residual_days = 0` and `position_flow_residual_max_bp = 0` | Stock leg and cash leg cancellation is intact across positions | Treat as healthy flow bookkeeping |
| `position_flow_residual_max_bp <= 1` | Likely rounding dust | Keep diagnostic-only unless it persists broadly |
| `position_flow_residual_max_bp` between `2` and `10` | Mildly non-flow-neutral scoped slice | Review whether offsetting legs sit outside the requested grouping before tightening policy |
| `position_flow_residual_max_bp > 10` | Materially non-flow-neutral scoped slice | Keep calculation active, surface diagnostics, and block denominator promotion for those slices |
| Large `position_flow_residual_sum_bp` with small single-day max | Repeated small net-flow pressure across the slice | Investigate whether the scoped book routinely excludes offsetting legs rather than treating it as one-off noise |

This table reflects the current domain view:

- position-level internal flows are expected to cancel because the stock leg and cash leg of an
  internal rebalance should offset across positions
- that cancellation helps summed position contribution continue to reconcile to the portfolio return
- once the cancellation breaks materially inside the visible scope, contribution may stop telling
  the same economic story as the portfolio path even if individual position rows still look locally
  reasonable

#### Average-Weight Shadow Interpretation Table

| Signal | Working interpretation | Recommended action |
| --- | --- | --- |
| `average_weight_shadow_delta_positions = 0` | Active and reset-aware denominator stories agree for the slice | Keep current active output |
| `average_weight_shadow_delta_max_bp <= 100` | Small characterization noise | Keep diagnostic-only unless repeated in critical workflows |
| `average_weight_shadow_delta_max_bp` between `101` and `499` | Meaningful methodology pressure, but not yet enough to justify immediate cutover | Gather more scenario evidence and keep shadow-only |
| `average_weight_shadow_delta_max_bp >= 500` | Material mismatch between active and reset-aware weight story | Treat as strong evidence for future cutover planning |
| Large `average_weight_shadow_delta_sum_bp` with smaller max | Drift spread across multiple positions rather than one dominant outlier | Investigate whether the active denominator is systematically flattening the episode story |

Current evidence level:

- unit characterization now covers both non-material and material shadow severities
- end-to-end coverage is currently strongest for material reset-heavy cases
- a clean non-material end-to-end case has not yet been locked in, so the softer threshold should
  still be treated as characterization guidance rather than settled production policy
- the contribution audit layer now also reports
  `average_weight_shadow_noise_periods`,
  `average_weight_shadow_warning_periods`, and
  `average_weight_shadow_material_periods` so rollout decisions can be informed by bucket counts
  across real traffic rather than one-off examples alone
- a further readiness signal now exists as
  `average_weight_shadow_cutover_candidate_periods`: these are periods with material shadow
  pressure where weight sums, flow balance, reset alignment, and daily-series reconciliation are
  otherwise clean enough that a future denominator cutover would be analytically credible
- when this count is non-zero, contribution now emits a plain diagnostics note so business users do
  not need to inspect raw audit counters to understand that the slice is a serious rollout
  candidate
- a guarded rollout mechanism now exists at runtime through
  `CONTRIBUTION_RESET_AWARE_AVERAGE_WEIGHT_MODE`
  with:
  - `OFF` as the stable default
  - `CANDIDATE_PERIODS` as the controlled promotion mode for analytically clean candidate periods
- the audit layer now also reports `average_weight_shadow_promoted_periods` so rollout impact can
  be measured separately from shadow-only evidence
- the audit layer now also reports `average_weight_shadow_blocked_periods` together with the
  `average_weight_shadow_blocked_by_*_periods` breakdown so rollout decisions can distinguish
  “material but blocked” from “material and promotion-ready”
- the audit layer now also reports `average_weight_shadow_promotion_ready_rate_bp`, which compresses
  candidate readiness into one observational summary: the share of material-shadow periods that are
  currently promotion-ready under the existing guardrails
- each resolved contribution period now also carries a compact
  `average_weight_methodology_status` response block so period-level rollout state can be read
  directly without reconstructing it from aggregate audit counts

#### Reset-Aware Average-Weight Rollout Policy

| Rollout signal mix | Working meaning | Rollout decision |
| --- | --- | --- |
| `average_weight_shadow_cutover_candidate_periods > 0`, `average_weight_shadow_blocked_periods = 0`, and `average_weight_shadow_promoted_periods = 0` | Material shadow pressure exists and the surrounding bookkeeping is clean, but runtime promotion is still disabled | Safe candidate for limited staged rollout |
| `average_weight_shadow_promoted_periods > 0` and blocker counts remain `0` | Controlled promotion is active on analytically clean slices | Allow continued limited rollout and measure impact |
| `average_weight_shadow_blocked_by_weight_residual_periods > 0` | Position weights do not add cleanly to `100%`, so denominator evidence is mixed with a coverage/integrity defect | Hard-stop promotion for those slices until weight residual is fixed |
| `average_weight_shadow_blocked_by_flow_balance_periods > 0` | The scoped position set is not flow-neutral, so denominator promotion would be layered on top of a partial flow story | Hard-stop promotion for those slices while keeping calculation and diagnostics active |
| `average_weight_shadow_blocked_by_reset_alignment_periods > 0` | Portfolio and position engines disagree on reset boundaries, so denominator promotion would be layered on top of inconsistent state propagation | Keep shadow-only and fix reset alignment first |
| `average_weight_shadow_blocked_by_timeseries_delta_periods > 0` | Emitted daily series still drift from the residual-adjusted period total | Keep shadow-only and fix timeseries reconciliation first |
| `average_weight_shadow_material_periods > 0` with both candidate and blocked counts at `0` | Material shadow pressure exists, but the currently observed slices are either not promotion-eligible or are not yet fully characterized | Stay shadow-only and gather more scenario evidence |

Working rollout rule:

1. only promote on periods counted in `average_weight_shadow_cutover_candidate_periods`
2. treat weight-residual and flow-balance blockers as stronger stop-signs than the others because
   they undermine economic integrity directly
3. treat reset-alignment and timeseries-delta blockers as methodology stop-signs because they mean
   the denominator cannot yet be evaluated in isolation
4. do not broaden beyond `CANDIDATE_PERIODS` until real traffic shows that blocked-period counts
   stay low and promoted slices continue to reconcile cleanly

Operational reading:

- `average_weight_shadow_promotion_ready_rate_bp = 10000` means every observed material-shadow
  period is currently promotion-ready
- `average_weight_shadow_promotion_ready_rate_bp = 0` means none of the observed material-shadow
  periods are currently promotion-ready
- values in between describe mixed traffic and should be reviewed together with the blocker
  breakdown before any broader rollout decision

Worked rollout-status examples:

| Example | Signal mix | Interpretation |
| --- | --- | --- |
| Fully ready material traffic | `material=3`, `candidate=3`, `blocked=0`, `promotion_ready_rate_bp=10000` | All observed material-shadow periods are analytically clean enough for controlled promotion |
| Fully blocked material traffic | `material=2`, `candidate=0`, `blocked=2`, `blocked_by_flow_balance=2`, `promotion_ready_rate_bp=0` | Denominator pressure exists, but every material slice is blocked by non-flow-neutral scoped slices |
| Mixed traffic | `material=5`, `candidate=2`, `blocked=3`, `blocked_by_reset_alignment=2`, `blocked_by_timeseries_delta=1`, `promotion_ready_rate_bp=4000` | Some slices are ready, but the blocker mix is still too large for a broader default rollout |

Operational artifact:

- `scripts/contribution_rollout_readiness_report.py` aggregates saved contribution response payloads
  into `artifacts/contribution-rollout-readiness/latest.json`
- `scripts/generate_seeded_contribution_rollout_artifacts.py` generates a deterministic seeded
  bundle and then emits `artifacts/contribution-rollout-readiness/seeded/latest.json`
- `scripts/contribution_rollout_decision_check.py` evaluates a readiness artifact against explicit
  rollout thresholds and returns `READY` or `HOLD`
- the decision checker now also labels the hold cause so rollout review can distinguish:
  - insufficient evidence
  - economic-integrity blockers
  - methodology-guardrail blockers
  - blocked periods without stronger category signals
  - below-threshold readiness
- when multiple blocker families coexist, the decision checker also emits
  `secondary_hold_categories` so the primary hold can stay stable without hiding the rest of the
  blocker stack
- the checker also emits `recommended_next_action` so the rollout artifact can directly support a
  governance review or handoff without extra interpretation
- the seeded bundle now includes:
  - `no_material_shadow.json`
  - `ready_candidate_shadow_only.json`
  - `promoted_candidate.json`
  - `blocked_flow_balance.json`
  - `blocked_reset_alignment.json`
- this artifact is intended for seeded validation runs and controlled non-prod rollout review, not
  for client-facing runtime response use
- the artifact recommendation is a governance aid; it does not itself change engine behavior
- the readiness artifact now also separates:
  - `blocked_economic_periods` for weight/flow integrity stop-signs
  - `blocked_methodology_periods` for reset-alignment/timeseries stop-signs
  - `blocker_category_counts` so rollout reviews can see whether the remaining hold is mostly
    economic-integrity debt or methodology-guardrail debt

### Slice 4: Grouped-return and cross-surface tie-out alignment

Goal:

- ensure contribution grouped returns inherit reset behavior consistently with portfolio TWR

Changes:

- propagate canonical reset state into grouped return calculation
- characterize and then decide the required role of:
  - `account_performance_reset`
  - `next_performance_reset`
  - any explicit grouped-return tax handling that materially affects reconciliation
- add stronger local proofs that:
  - contribution total = portfolio TWR
  - returns-series cumulative active = TWR relative performance
  - attribution active return = benchmark-aware TWR relative performance where methodology should
    reconcile

Decision rule:

- move only after portfolio reset and contribution weight methodology are stable

### Slice 5: Attribution and benchmark-aware tie-out hardening

Goal:

- strengthen the “same story, different lens” acceptance model

Changes:

- extend cross-surface tests to:
  - benchmark-aware TWR
  - returns-series
  - contribution
  - attribution
- add scenario documentation for each validator in lotus-platform
- use seeded cross-app validation as release evidence, not only local tests

Decision rule:

- no attribution formula rewrite is implied by this RFC
- attribution changes should be made only where upstream performance-state alignment demands them

### Slice 6: Smoothing parity decision

Goal:

- decide whether richer smoothing parity is worth implementing

Changes:

- compare current Carino smoothing against the richer reference smoothing framework
- decide one of:
  - retain current Carino smoothing and document intentional deviation
  - add advanced smoothing as an optional method
  - replace current smoothing if business acceptance requires parity

Decision rule:

- this is explicitly deferred behind Slices 1 through 5

## Test and Validation Evidence

Current evidence reviewed for this RFC:

- [docs/technical/formula-mapping-review-notes.md](C:/Users/Sandeep/projects/lotus-performance/docs/technical/formula-mapping-review-notes.md)
- [engine/rules.py](C:/Users/Sandeep/projects/lotus-performance/engine/rules.py)
- [engine/ror.py](C:/Users/Sandeep/projects/lotus-performance/engine/ror.py)
- [engine/contribution.py](C:/Users/Sandeep/projects/lotus-performance/engine/contribution.py)
- [app/services/contribution_service.py](C:/Users/Sandeep/projects/lotus-performance/app/services/contribution_service.py)
- [tests/e2e/test_workflow_journeys.py](C:/Users/Sandeep/projects/lotus-performance/tests/e2e/test_workflow_journeys.py)
- platform-level cross-app validators in `lotus-platform/automation/`

Required new validation evidence by slice:

- synthetic unit tests for reset boundaries and `NIP`
- contribution methodology tests for average-weight denominator behavior
- cross-surface e2e reconciliation tests
- lotus-platform seeded cross-app validations for:
  - TWR + benchmark
  - returns-series
  - contribution
  - attribution

## Original Acceptance Criteria Alignment

This RFC will be considered aligned when:

1. the system preserves economically correct daily RoR and cumulative TWR behavior
2. reset behavior is explicit, testable, and explainable by named reset reasons
3. `NIP` behavior is canonical, deterministic, and reset-relative
4. contribution weights and totals reconcile to portfolio TWR through reset boundaries
5. cross-surface outputs tell the same story through distinct analytic lenses
6. any intentional deviation from the richer reference formulas is documented and justified

## Rollout and Backward Compatibility

The service is not yet live, so public backward compatibility is not the governing concern.

However, methodology changes still need staged rollout because:

- they affect multiple engine families
- they can silently shift outputs
- they need cross-surface and cross-app validation

Rollout rule:

- each slice must land with characterization first, then behavior change, then cross-surface proof
- do not combine reset, `NIP`, contribution weighting, and smoothing changes in one merge

## Open Questions

1. Should the stricter `NIP` rule become the only rule, or remain behind a temporary internal flag
   during rollout?
2. Does `NCTRL_4` have enduring incremental value once canonical reset reasons are fully modeled?
3. Should acquisition-day fallback weight remain part of the contribution methodology?
4. Should richer smoothing be introduced as an alternative method instead of replacing Carino?
5. Should reset-reason diagnostics be emitted only in lineage / internal traces, or surfaced in
   response diagnostics as well?
6. Does grouped return calculation need explicit tax propagation, or is current tax treatment
   intentionally outside the contribution reconciliation contract?

## Intentional Deferred Decisions

The following items are intentionally **not** being forced to closure yet. They are deferred by
design, not left vague accidentally.

### 1. Canonical reset cutover

Current posture:

- active production compounding still uses the existing reset path
- canonical reset remains observable through shadow diagnostics

Why this is deferred:

- direct promotion of the candidate canonical reset model changed TWR behavior materially before we
  had enough cross-surface evidence
- the current characterization signals are strong enough to measure the delta, but not yet strong
  enough to justify broad promotion

Decision trigger to revisit:

- broader non-prod evidence shows the canonical reset model is economically better
- cross-surface tie-out stays stable
- candidate reset deltas are understood, not just observed

### 2. Canonical stricter `NIP` cutover

Current posture:

- reset-relative valid-day accounting is active
- stricter `NIP` remains shadowed

Why this is deferred:

- `NIP` affects contribution denominators, reset-relative day counts, and potentially grouped-return
  interpretation
- promoting it before reset posture is finalized would stack two methodology changes at once

Decision trigger to revisit:

- canonical reset posture is decided
- `nip_rule_delta_days` evidence remains stable across broader validation
- no new cross-surface reconciliation drift appears when the stricter rule is trialed

### 3. Richer smoothing parity

Current posture:

- Carino remains the active smoothing model
- invalid log-domain cases now fall back safely and visibly

Why this is deferred:

- smoothing is no longer the main source of unexplained drift
- richer smoothing would add complexity without first-order evidence that it is required for the
  current business rollout

Decision trigger to revisit:

- business acceptance requires closer parity to the richer reference framework
- or future validation shows Carino-safe behavior is still not sufficient for explanation quality

## RFC Closure Bar

RFC-043 should be moved from `Partially Implemented` to final implemented/accepted closure only
when all of the following are true:

1. broader validation continues to pass for the reset/NIP/contribution methodology pack
2. rollout evidence is available beyond the deterministic seeded bundle
3. the final production posture for canonical reset is explicitly documented:
   - remain shadowed
   - or promote to active
4. the final production posture for stricter `NIP` is explicitly documented:
   - remain shadowed
   - or promote to active
5. reset-aware `average_weight` rollout policy is explicit and stable:
   - remain `OFF` by default
   - or widen controlled rollout
   - or become broader default
6. any intentional deviations from the richer reference framework remain documented, especially for
   smoothing

This means RFC closure is a policy-and-evidence milestone now, not a major engineering-build
milestone.

## Next Actions

### P0

- run broader non-prod validation using `CONTRIBUTION_RESET_AWARE_AVERAGE_WEIGHT_MODE=CANDIDATE_PERIODS`
- collect readiness artifacts from realistic slices and verify blocker mix stays low outside known non-flow-neutral cases
- decide whether canonical reset and stricter canonical `NIP` should remain shadowed or move to active cutover

### P1

- close RFC status from `Partially Implemented` only after rollout evidence supports the remaining active/deferred decisions
- add any targeted attribution / benchmark tie-out proofs only if rollout evidence shows a real cross-surface mismatch

### P2

- revisit richer smoothing only if business acceptance requires parity beyond domain-safe Carino
- document final production posture for canonical reset/NIP once rollout evidence is sufficient
