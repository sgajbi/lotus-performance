# Performance Reset Scenarios

This note explains when the TWR engine treats a portfolio path as one continuous compounding
experience and when it treats the path as a new performance episode.

The guiding principle is simple:

- geometric linking is valid while returns are being earned on a meaningful invested capital base
- resets are justified when that capital path becomes economically discontinuous or nonsensical

This is why performance resets exist at all. They are not there to mirror legacy code structure.
They are there to stop the engine from chaining returns across states that no longer represent one
coherent investment experience.

## Why Geometric Linking Can Break

Time-weighted return compounds sub-period returns geometrically. That only remains meaningful while:

- the portfolio still has a usable capital base
- the portfolio has not been economically liquidated and restarted
- the path has not crossed into a collapsed long/short state that no longer behaves like an
  ordinary linked return stream

When those assumptions fail, the engine should prefer a reset to a mathematically precise but
economically misleading answer.

## Scenario Matrix

| Scenario | Example state path | Economic interpretation | Should reset? | Current engine signal |
| --- | --- | --- | --- | --- |
| Ordinary subscription into a healthy portfolio | `begin_mv > 0`, `bod_cf > 0`, `end_mv > 0` | New capital entered, but the portfolio never stopped being a valid invested path | No | No active reset expected |
| Fee-only day | `begin_mv > 0`, `mgmt_fees != 0`, no material cash flow, `end_mv > 0` | Fees reduce performance, but they do not create a new investment episode | No | No active reset expected |
| No-investment period | `begin_mv = 0`, `end_mv = 0`, no cash flow | No capital was invested for that day | Not a reset by itself, but the day is excluded from ordinary compounding semantics | NIP flag expected |
| Portfolio wipeout / collapse boundary | capital falls through zero or a long/short cumulative path breaches a collapse threshold | Continuing to link returns through the same path becomes economically unstable | Yes | `NCTRL_1`, `NCTRL_2`, or `NCTRL_3` may fire |
| Liquidation followed by recapitalization | portfolio reaches a broken state, then a new `bod_cf` recapitalizes it | The second path is a new investment episode, not a continuation of the old one | Yes | `NCTRL_4` often appears on the recapitalization boundary after the break |
| Account-directed reset | upstream account-level reset flag is present | Operationally, the account owner is saying the performance episode should restart here | Candidate yes, but still in shadow characterization in the current engine | `account_reset` shadow only today |
| Start-of-day reset carry | next day starts with a significant `bod_cf` after a reset boundary | Used to characterize whether the previous day should close one performance episode cleanly | Candidate yes, but still in shadow characterization in the current engine | `sod_reset` shadow only today |

## Reachability Guardrail

This engine is not trying to preserve every historical branch from a reference implementation.

A reset condition should survive only if it satisfies both tests:

- it is reachable from a real portfolio state we can describe clearly
- that state gives a defensible reason that geometric linking should stop or restart

That is why the current methodology work keeps some controls as shadow-only diagnostics:

- `account_reset` is visible so we can measure where an upstream account instruction would change
  the reset story
- `sod_reset` is visible so we can measure whether the day before a reset-and-recapitalization open
  should close the prior episode

If a branch cannot be tied back to a meaningful portfolio story, it is a cleanup candidate rather
than something to preserve automatically.

The diagnostics block now exposes separate characterization counts so we can discuss these stories
with evidence:

- `nip_rule_delta_days`
- `nctrl4_reset_days`
- `nctrl4_exclusive_reset_days`
- `account_reset_shadow_days`
- `sod_reset_shadow_days`
- `shadow_reset_overlap_days`
- `shadow_only_candidate_reset_days`
- `active_reset_with_shadow_days`

## Worked Portfolio Stories

### 1. Ordinary Subscription

| Date | Begin MV | BOD CF | EOD CF | End MV | Interpretation |
| --- | ---: | ---: | ---: | ---: | --- |
| 2025-01-01 | 100.00 | 0.00 | 0.00 | 101.00 | Normal gain |
| 2025-01-02 | 101.00 | 25.00 | 0.00 | 127.26 | Investor adds capital, but the portfolio remains healthy |
| 2025-01-03 | 127.26 | 0.00 | 0.00 | 128.53 | Compounding continues on the enlarged capital base |

Business meaning:

- this is still one continuous investment experience
- the subscription changes the capital base, but it does not invalidate TWR linking

Expected engine behavior:

- no active performance reset
- no candidate canonical reset

### 1A. Offsetting Cash-Flow Zero Day

| Date | Begin MV | BOD CF | EOD CF | End MV | Interpretation |
| --- | ---: | ---: | ---: | ---: | --- |
| 2025-01-01 | 0.00 | 1.00 | -1.00 | 0.00 | Cash moves through the account, but no capital stays invested |

Business meaning:

- this is a genuine methodology edge case rather than a normal invested day
- the current legacy NIP rule only recognizes a narrow offsetting-flow pattern here, which is why
  we keep the disagreement visible instead of assuming all equal-and-opposite flows behave the same

Expected characterization behavior today:

- the engine exposes this disagreement through `nip_rule_delta_days`
- the exact daily rule difference remains visible in methodology shadow samples until the
  canonical NIP rule is promoted

### 2. Fee-Only Day

| Date | Begin MV | BOD CF | Fees | End MV | Interpretation |
| --- | ---: | ---: | ---: | ---: | --- |
| 2025-01-01 | 1000.00 | 0.00 | 0.00 | 1010.00 | Normal gain |
| 2025-01-02 | 1010.00 | 0.00 | -5.00 | 1015.00 | Fee drag, but still one continuous invested path |
| 2025-01-03 | 1015.00 | 0.00 | 0.00 | 1020.00 | Compounding continues |

Business meaning:

- fees are part of return measurement, not a new episode boundary
- if fees alone caused resets, the engine would fragment ordinary performance paths

Expected engine behavior:

- no active performance reset
- no candidate canonical reset

### 3. Liquidation and Recapitalization

| Date | Begin MV | BOD CF | End MV | Interpretation |
| --- | ---: | ---: | ---: | --- |
| 2025-01-01 | 1000.00 | 0.00 | 500.00 | Severe loss, but still positive capital |
| 2025-01-02 | 500.00 | 0.00 | -50.00 | Capital path breaks through zero |
| 2025-01-03 | -50.00 | 1000.00 | 1050.00 | Fresh capital restarts the economic position |
| 2025-01-04 | 1050.00 | 0.00 | 1155.00 | New episode compounds from the recapitalized base |

Business meaning:

- by 2025-01-02 the original capital path is broken
- the 2025-01-03 capital injection is not just "more of the same"
- continuing to geometrically link straight through would tell an economically misleading story

Expected engine behavior today:

- active reset on the collapse boundary
- active reset again on the recapitalization boundary
- reset reasons typically surface as `NCTRL_1` followed by `NCTRL_4`

Current cross-surface caveat:

- this scenario is now covered end-to-end and both the top-line contribution result and the emitted
  daily contribution series reconcile to TWR after the service switched to reset-aware period
  return and residual-aware daily-series allocation
- that moves the remaining contribution methodology debt away from basic reset-heavy tie-out and
  toward whether the chosen daily residual allocation remains the right business explanation across
  more complex multi-position stories
- the contribution response now also exposes that Carino smoothing is not valid on the collapse day,
  and falls back to raw daily contribution arithmetic instead of applying a logarithmic adjustment
  outside its domain

### 4. Account Reset and SOD Reset Are Still Characterization Signals

These two signals are intentionally visible before they are active:

- `account_reset` captures an upstream instruction that says "treat this as a new performance
  episode"
- `sod_reset` captures the prior day when the next open begins with new capital and a reset state

Business meaning:

- both may prove useful in the canonical reset model
- neither should be promoted into active compounding until we can show they improve economic
  meaning without fragmenting ordinary portfolio paths

Interpretation aid:

- `shadow_only_candidate_reset_days` means the candidate model sees a reset boundary that the
  active engine does not yet enforce
- `active_reset_with_shadow_days` means today’s active reset and the shadow model are both
  pointing at the same economic boundary
- `nctrl4_exclusive_reset_days` helps us tell whether `NCTRL_4` is adding something genuinely
  distinct or mostly traveling with other reset signals

### 5. Reset-Relative Valid Days

Reset-relative valid-day counting answers a different question from total period length:

- "How many days belong to the current performance episode?"

That denominator matters later for contribution average-weight methodology.

Two rules drive it:

- days before the most recent active reset no longer belong to the current episode
- NIP days after that reset still belong to the episode timeline, but they do not count as valid
  invested days

Example interpretation:

- if a portfolio resets on `2025-01-03`, then `2025-01-01` and `2025-01-02` should not influence
  the reset-relative valid-day denominator anymore
- if `2025-01-04` is a true no-investment day, it should increase `nip_days_since_last_reset`
  without increasing `valid_days_since_last_reset`

## Implementation Notes

- `NCTRL_1..3` currently represent the strongest mathematically necessary reset candidates because
  they guard collapse boundaries where long/short cumulative linking stops making sense
- `NCTRL_4` is still under characterization; it appears economically useful in liquidation and
  recapitalization stories, but it should survive only if it continues to represent a reachable and
  meaningful portfolio state
- `account_reset` and `sod_reset` are currently shadow-only diagnostics while we verify whether
  they belong in the canonical reset model

Current working decision:

- keep `NCTRL_1..3` active
- keep `NCTRL_4` active provisionally because current characterization still shows unique value
- keep `account_reset` and `sod_reset` as shadow-only until they improve real portfolio meaning
  without fragmenting ordinary healthy paths

## Related References

- [TWR Guide](../guides/twr.md)
- [RFC 043 - Performance Reset, NIP, and Contribution Methodology Alignment](../RFCs/RFC%20043%20-%20Performance%20Reset,%20NIP,%20and%20Contribution%20Methodology%20Alignment.md)
