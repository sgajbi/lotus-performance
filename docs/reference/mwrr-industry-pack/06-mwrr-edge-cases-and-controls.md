# MWRR Edge Cases and Controls

**Status:** Draft edge-case guide  
**Audience:** BA, QA, developers, operations, production support  
**Last updated:** 2026-05-08

## 1. Why edge cases matter

MWRR is sensitive to cash-flow patterns, valuations, FX, timing, and scope. Production systems must treat edge cases as first-class requirements, not as afterthoughts.

A good MWRR engine should prefer:

```text
clear not-calculable status > misleading numeric result
```

## 2. Edge-case policy matrix

| Edge case | Recommended behavior | Code or warning |
|---|---|---|
| No external flows, valid BMV/EMV | Calculate simple-return-equivalent MWRR | None |
| Zero BMV, later investment flow, valid EMV | Calculate from first investment flow | `ZERO_BEGIN_MARKET_VALUE` optional |
| Missing ending value | Not calculable | `MISSING_END_VALUATION` |
| Missing beginning value | Not calculable unless zero-start policy applies | `MISSING_BEGIN_VALUATION` |
| Missing FX | Not calculable or fallback with warning | `MISSING_FX_RATE` |
| Missing transfer valuation | Not calculable unless approved valuation fallback | `TRANSFER_VALUATION_MISSING` |
| All flows same sign | Not calculable | `NO_POSITIVE_AND_NEGATIVE_CASH_FLOW` |
| No IRR root | Not calculable or fallback | `NO_ROOT_FOUND` |
| Multiple IRR roots | Not calculable by default | `MULTIPLE_IRR_ROOTS_DETECTED` |
| XIRR failure with Dietz fallback | Calculate Dietz, label fallback | `MODIFIED_DIETZ_FALLBACK_USED` |
| Near-zero NAV | Calculate with warning or suppress per policy | `NEAR_ZERO_NAV` |
| Negative NAV | Policy-dependent | `NEGATIVE_NAV` |
| Short period annualized | Calculate but warn | `SHORT_PERIOD_ANNUALIZED` |
| Stale valuation | Policy-dependent | `STALE_VALUATION` |
| Late correction | Supersede/restate | `RESULT_SUPERSEDED` |
| Internal transfer unmatched | Partial data or warning | `INTERNAL_TRANSFER_MATCH_INCOMPLETE` |

## 3. Zero beginning value

A portfolio may have zero value at period start and receive capital later.

Example:

| Date | Cash flow |
|---|---:|
| 2026-03-01 | -100,000 |
| 2026-12-31 | +110,000 |

This is valid. The anchor date may be the first non-zero flow date if the zero BMV is omitted.

Expected holding-period result over 305 days:

```text
10.0000%
```

Annualized ACT/365 result:

```text
approximately 12.0819%
```

Policy decisions:

- include zero BMV in evidence?
- omit zero flow from solver?
- anchor at period start or first investment date?
- display since-investment versus full reporting period?

## 4. Zero ending value

Ending value can be zero when:

- account closed,
- position fully redeemed,
- asset had total loss,
- all value was distributed before period end.

A zero EMV is not automatically invalid if there are positive distributions or withdrawals.

Example:

| Date | Cash flow |
|---|---:|
| 2026-01-01 | -100,000 |
| 2026-06-01 | +80,000 |
| 2026-12-31 | 0 |

This may produce a valid negative MWRR.

Do not treat a closed account with no terminal value as missing data if the closing withdrawal already captured all value, unless methodology requires an explicit zero terminal flow.

## 5. No economic content

If a period has:

- zero beginning value,
- zero ending value,
- no external flows,
- no positions,
- no economic exposure,

then return:

```text
NOT_APPLICABLE
```

Do not return 0% unless business methodology explicitly defines that as the display convention. A 0% return implies an investment existed and neither gained nor lost value.

## 6. Negative NAV

Negative NAV can occur with:

- leverage,
- overdrafts,
- margin loans,
- derivatives,
- short portfolios,
- accounting timing differences.

MWRR on negative NAV can be unintuitive or mathematically unstable.

Policy options:

| Policy | Behavior |
|---|---|
| Block | Return not calculable when BMV or EMV is negative. |
| Allow with warning | Calculate but emit `NEGATIVE_NAV`. |
| Special methodology | Use capital-account or equity-based treatment. |
| Supplement | Show P&L and gross exposure beside MWRR. |

Recommended support wording:

> The return is calculated on NAV/equity. When NAV is negative or near zero, percentage returns can be unstable and should be reviewed with P&L and exposure context.

## 7. Near-zero NAV

Near-zero NAV can create extreme MWRR.

Examples:

| Scenario | Risk |
|---|---|
| BMV = 1,000, EMV = 2,000 | 100% return despite small absolute gain. |
| Large gross exposure, tiny equity | NAV return amplified by leverage. |
| Large flow leaves small residual NAV | Solver may produce extreme annualized rate. |

Recommended controls:

- configurable near-zero NAV thresholds,
- warning flags,
- P&L context,
- gross exposure context,
- optional suppression of annualized values.

Example warnings:

```text
NEAR_ZERO_NAV
EXTREME_ANNUALIZED_RETURN
LEVERAGE_AMPLIFIED_RETURN
```

## 8. Large flows

MWRR should be sensitive to large flows. That is the point. But large flows should be visible in explanations.

Suggested materiality checks:

| Condition | Warning/context |
|---|---|
| Single flow > 25% of beginning value | `LARGE_EXTERNAL_FLOW` |
| Net flow > 50% of beginning value | `MATERIAL_NET_FLOW` |
| Flow occurs within few days of period end | `LATE_PERIOD_FLOW` |
| Flow occurs before large market move | Support explanation should highlight timing. |

Thresholds should be configurable.

## 9. TWRR and MWRR divergence

Large divergence between TWRR and MWRR is often legitimate.

Common causes:

- large deposit before poor performance,
- large withdrawal before good performance,
- capital concentrated during weak periods,
- capital concentrated during strong periods,
- account opened after strong historical period,
- account closed before weak period,
- private-market drawdown/distribution timing.

Recommended output:

- show TWRR and MWRR side by side,
- show major flows,
- show holding-period versus annualized MWRR,
- include explanation text.

## 10. Missing valuation

MWRR requires terminal valuation.

| Missing item | Recommended behavior |
|---|---|
| Missing BMV | Not calculable unless zero-start policy applies. |
| Missing EMV | Not calculable. |
| Missing component value | Component MWRR not calculable. |
| Missing private-asset NAV | Not calculable or estimate with strong warning if policy permits. |

Do not infer missing valuation from cash flows unless the methodology explicitly defines liquidation/closure treatment.

## 11. Stale or estimated valuation

Valuation quality affects MWRR.

| Valuation state | Behavior |
|---|---|
| Official/final | Normal calculation. |
| Estimated | Calculate with warning if allowed. |
| Stale within tolerance | Calculate with warning. |
| Stale beyond tolerance | Not calculable or suppressed. |
| Corrected later | Supersede/restate. |

Evidence should include valuation source, date, timestamp, and final/estimate status.

## 12. Missing FX

If values or flows are not in reporting currency, FX is required.

Options:

| Policy | Behavior |
|---|---|
| Strict | Not calculable. |
| Secondary source | Use fallback source with warning. |
| Previous good rate | Use prior rate with warning. |
| Manual override | Use approved override with audit trail. |

Never silently use 1.0 unless source and reporting currency are actually the same.

## 13. Missing transfer valuation

In-kind transfers must be valued.

If valuation is missing:

- do not use zero,
- do not ignore the transfer,
- do not treat it as a trade,
- return not calculable or partial data according to policy.

Possible fallback hierarchy:

1. custodian transfer value,
2. official price on transfer date,
3. prior close within staleness tolerance,
4. administrator NAV price,
5. approved manual valuation.

## 14. Account closed and reopened

A portfolio may close and reopen.

| Scenario | Recommended handling |
|---|---|
| Account closes and remains closed | Calculate through closure if final distribution captured. |
| Account has zero balance briefly then new deposit | Policy decides continuous versus split period. |
| Account reopens after long gap | Consider new inception date or separate reporting segment. |
| Period has no exposure | Return not applicable. |

Do not treat a reopened account's new capital as if it had been invested since original inception unless methodology requires continuous track record.

## 15. Late bookings and corrections

Late and corrected events can materially change MWRR.

Restatement triggers:

- backdated deposit,
- corrected withdrawal,
- corrected transfer value,
- corrected FX rate,
- corrected valuation,
- fee reclassification,
- internal transfer match discovered later,
- duplicate removed,
- reversal posted.

Required controls:

1. source versioning,
2. calculation supersession,
3. restatement reason,
4. prior/current comparison,
5. audit evidence.

## 16. Reversals

If a transaction is reversed, do not double count.

Acceptable ledger approaches:

| Approach | Description |
|---|---|
| Remove original and reversal | Clean current-state event view. |
| Include original and reversal | Works if both net to zero and dates are correct. |
| Versioned replacement | Supersede original with corrected event. |

Whatever the approach, evidence should explain the result.

## 17. Multiple roots

Multiple roots can arise from alternating cash-flow signs.

Pattern:

```text
-, +, -, +
```

Recommended policy:

- detect multiple roots,
- return not calculable by default,
- do not choose arbitrarily,
- optionally return Modified Dietz fallback if approved,
- show support-friendly explanation.

## 18. No root

Some cash-flow patterns do not produce a root in configured bounds.

Recommended policy:

- return not calculable,
- report search bounds,
- report cash-flow summary,
- allow explicitly labeled fallback only if approved.

## 19. Leverage

MWRR measured on NAV reflects return on investor equity, including leverage.

Example:

| Item | Amount |
|---|---:|
| Client equity | 100,000 |
| Borrowed amount | 400,000 |
| Gross investment | 500,000 |
| Investment gain | 25,000 |

Return on gross assets:

```text
25,000 / 500,000 = 5%
```

Return on equity/NAV:

```text
25,000 / 100,000 = 25%
```

MWRR on NAV is closer to equity return, not gross asset return.

## 20. Component-level MWRR edge cases

Component-level MWRR can be distorted by:

- asset-class reclassification,
- security master changes,
- strategy sleeve reassignment,
- buys and sells creating artificial component flows,
- short positions,
- derivatives exposure without cash capital,
- negative component market value,
- components with tiny market values.

Recommended controls:

- stable classification hierarchy,
- reclassification effective dating,
- component-flow evidence,
- clear labels,
- no additive summation claims.

## 21. Private-market edge cases

Private-market MWRR must consider:

- delayed NAVs,
- capital call dates versus booking dates,
- distribution dates versus received dates,
- recallable distributions,
- subscription credit lines,
- equalization payments,
- GP-led secondary transactions,
- in-kind distributions,
- residual value quality,
- multiple currency layers.

Recommended controls:

- use methodology-approved effective dates,
- disclose residual NAV date,
- include valuation status,
- consider since-inception as primary,
- distinguish realized distributions from residual value.

## 22. Suppression policy

Some results may be mathematically calculated but unsuitable for display.

Suppression candidates:

- near-zero NAV with extreme annualized return,
- stale valuation beyond threshold,
- short-period annualized value beyond threshold,
- negative NAV where policy blocks display,
- partial data affecting major flows,
- unresolved duplicate/reversal uncertainty.

Suppressed results should return status and reason, not blank without explanation.

## 23. Control checklist

- [ ] Zero-start behavior defined.
- [ ] Negative NAV policy defined.
- [ ] Near-zero NAV warning threshold defined.
- [ ] Missing valuation behavior defined.
- [ ] Stale valuation behavior defined.
- [ ] Missing FX behavior defined.
- [ ] Transfer valuation fallback hierarchy defined.
- [ ] Late booking restatement policy defined.
- [ ] Multiple-root behavior defined.
- [ ] No-root behavior defined.
- [ ] Fallback behavior defined.
- [ ] Suppression policy defined.
- [ ] Component-level caveats defined.
