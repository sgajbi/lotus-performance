# MWRR Cash-Flow Classification

**Status:** Draft classification guide  
**Audience:** BA, QA, developers, operations, support analysts  
**Last updated:** 2026-05-08

## 1. Governing principle

MWRR is only as good as the cash-flow vector. The governing classification question is:

> Did value enter or leave the measurement scope from outside?

If yes, include the event as an external cash flow. If no, exclude it from the MWRR cash-flow vector and treat it as investment performance, internal movement, income, expense, or valuation change according to policy.

## 2. Measurement scope

A measurement scope can be:

- single portfolio,
- account,
- household,
- client group,
- mandate,
- fund,
- composite,
- strategy sleeve,
- asset class,
- security,
- private-market commitment,
- model portfolio.

Classification depends on the scope.

Example:

| Event | Single Account A | Household containing Account A and B |
|---|---|---|
| Cash moves from Account A to Account B | External outflow from A | Internal; exclude |
| Security moves from external custodian to Account A | External inflow | External inflow |
| Account A buys a bond using Account A cash | Internal | Internal |

## 3. Standard cash-flow event table

### Funding events

| Event | Include? | Investor-perspective sign | Notes |
|---|---:|---:|---|
| Cash deposit from external source | Yes | Negative | Additional investor capital. |
| Cash withdrawal to external destination | Yes | Positive | Capital returned to investor. |
| Subscription | Yes | Negative | Investment into measured vehicle. |
| Redemption | Yes | Positive | Value leaves measured vehicle. |
| Capital call | Yes | Negative | Private-market contribution. |
| Distribution to investor | Yes | Positive | Private-market or fund distribution. |
| Account opening funded from outside | Yes | Negative | May be beginning value if at period start. |
| Account closure paid out externally | Yes | Positive | May be ending value or withdrawal depending period. |

### In-kind transfers

| Event | Include? | Sign | Valuation rule |
|---|---:|---:|---|
| Security transfer in from outside scope | Yes | Negative | Fair value on transfer date. |
| Security transfer out to outside scope | Yes | Positive | Fair value on transfer date. |
| In-kind distribution to investor | Yes | Positive | Fair value when leaves scope. |
| In-kind contribution | Yes | Negative | Fair value when enters scope. |
| Transfer between portfolios inside same group | Scope-dependent | Scope-dependent | Exclude at group scope if internal. |

### Trading and investment activity

| Event | Include? | Reason |
|---|---:|---|
| Buy trade | No | Converts cash to security inside scope. |
| Sell trade | No | Converts security to cash inside scope. |
| FX spot conversion | No | Converts one internal cash currency to another. |
| Dividend received inside portfolio | No | Investment income. |
| Coupon received inside portfolio | No | Investment income. |
| Accrued income change | No | Valuation/income accrual. |
| Reinvested dividend | No | Internal reinvestment. |
| Realized gain/loss | No | Investment performance. |
| Unrealized gain/loss | No | Investment performance. |

### Corporate actions

| Corporate action | Include? | Notes |
|---|---:|---|
| Stock split | No | Quantity changes, value remains inside scope. |
| Reverse split | No | Quantity changes, value remains inside scope. |
| Stock dividend retained inside scope | Usually no | Treat through holdings and valuation unless value leaves/enters scope. |
| Spin-off retained inside scope | Usually no | Usually valuation/security master treatment. |
| Cash merger proceeds retained inside scope | No | Investment realization inside scope. |
| Cash merger proceeds distributed outside scope | Yes | External outflow if value leaves scope. |
| Rights issue funded by external cash | Yes for external funding | Cash entering scope is external. |
| Rights issue funded by internal cash | No | Internal investment decision. |
| Tender proceeds retained inside portfolio | No | Internal realization. |
| Tender proceeds paid out to investor | Yes | Value leaves scope. |

## 4. Fees

Fee treatment depends on return basis.

| Fee event | Net basis | Gross basis | Notes |
|---|---|---|---|
| Management fee paid from portfolio cash | Reduces return | May be added back/excluded depending policy | Avoid double counting. |
| Advisory fee paid outside portfolio | Policy-dependent | Usually excluded | Decide whether client experience includes external fee. |
| Custody fee paid from portfolio | Usually reduces return | Policy-dependent | Often remains in net reporting. |
| Transaction costs embedded in trades | Usually reflected in valuation/P&L | Often still reflected | Hard to fully remove. |
| Performance fee accrued in NAV | Reduces return | Gross policy may add back | Must align to valuation basis. |

Rules to document:

1. Which fees reduce net MWRR?
2. Which fees are excluded from gross MWRR?
3. Are external fee payments treated as external flows or expenses?
4. Are fees accrued or recognized when paid?
5. Is fee add-back applied to valuations, cash flows, or both?

## 5. Taxes

Tax treatment depends on tax reporting basis.

| Tax event | Before-tax basis | After-tax basis |
|---|---|---|
| Withholding tax inside portfolio | Add back or exclude according to policy | Reduces return |
| Capital gains tax paid from portfolio | Exclude/add back according to policy | Reduces return |
| Tax paid externally | Usually excluded unless after-tax client experience includes it | Policy-dependent |
| Tax reclaim received inside portfolio | Policy-dependent | Usually increases after-tax return when received/accrued |

Tax policy must be explicit. Avoid mixing before-tax and after-tax treatment in the same result.

## 6. Security transfer valuation

In-kind transfers need fair value amounts.

Recommended evidence fields:

| Field | Purpose |
|---|---|
| instrument identifier | Security identity. |
| quantity | Valuation input. |
| transfer date | Effective flow date. |
| local price | Valuation input. |
| price date | Staleness control. |
| price source | Auditability. |
| local currency | FX input. |
| local market value | Pre-FX value. |
| FX rate | Reporting-currency conversion. |
| reporting-currency value | Solver amount. |
| valuation override flag | Governance. |
| classification reason | Auditability. |

Recommended valuation hierarchy:

1. official valuation on transfer date,
2. administrator or custodian transfer value,
3. last available price within allowed staleness window,
4. independent private-asset valuation,
5. approved manual override.

If value cannot be determined, do not silently use zero.

## 7. Multi-currency classification

Cash-flow classification happens before FX conversion. A EUR deposit into a USD reporting portfolio is still an external deposit. Then it is converted into USD for calculation.

Required fields:

| Field | Example |
|---|---|
| source amount | 100,000 |
| source currency | EUR |
| FX rate to reporting currency | 1.1000 |
| FX rate date | 2026-07-01 |
| FX rate source | official close, custodian booked, administrator NAV FX, etc. |
| reporting amount | USD 110,000 |

FX policy should define:

- trade-date or settlement-date treatment,
- official close versus booked rate,
- fallback source,
- missing-rate behavior,
- rounding rules,
- restatement behavior.

## 8. Internal transfer matching

For group-level reporting, internal transfers should be excluded.

A transfer may have two legs:

| Leg | Single-portfolio treatment | Group treatment |
|---|---|---|
| Portfolio A transfer out | External outflow from A | Internal to group |
| Portfolio B transfer in | External inflow to B | Internal to group |

Implementation needs transfer matching using some combination of:

- transfer reference,
- source account,
- destination account,
- transaction date,
- settlement date,
- amount,
- currency,
- instrument,
- quantity,
- custodian event ID,
- reversal/correction links.

If matching is incomplete, output a warning or partial classification state.

## 9. Private-market events

Private-market MWRR commonly includes:

| Event | Treatment |
|---|---|
| Capital call | External negative investor cash flow. |
| Distribution | External positive investor cash flow. |
| Recallable distribution | Policy-dependent; may need separate memorandum tracking. |
| Management fee outside commitment | Policy-dependent. |
| Partnership expense inside NAV | Usually reflected in NAV. |
| Residual NAV | Ending synthetic cash flow. |
| Secondary purchase | Negative cash flow at acquisition value. |
| Secondary sale | Positive cash flow at sale proceeds. |
| Equalization payment | Policy-dependent. |

Private-market considerations:

- valuations may be quarterly or delayed,
- residual NAV quality materially affects MWRR,
- subscription lines can shift timing and affect IRR,
- since-inception MWRR is often more meaningful than short-window MWRR,
- cash-flow dates must reflect methodology, not just operational booking dates.

## 10. Component-level classification

At total portfolio level, selling bonds and buying equities is internal. At component level:

| Component | Event interpretation |
|---|---|
| Bonds | Outflow from bond component. |
| Equities | Inflow to equity component. |

Component-level MWRR requires defining component cash flows from allocation changes.

Cautions:

- reclassifications can create artificial flows,
- component boundaries must be stable,
- component MWRR is not contribution,
- total MWRR cannot be reconstructed by summing component MWRRs.

## 11. Reversals and corrections

Production systems must handle:

- reversed transactions,
- corrected amounts,
- corrected dates,
- corrected FX rates,
- corrected transfer prices,
- late-booked flows,
- canceled trades,
- duplicate events.

Rules:

1. Preserve source lineage.
2. Avoid double counting original and reversal.
3. Recalculate affected periods.
4. Mark previous results superseded where applicable.
5. Expose restatement reason.

## 12. Classification reason codes

Suggested included-flow reason codes:

| Code | Meaning |
|---|---|
| `CASH_DEPOSIT_ENTERED_SCOPE` | External cash deposit. |
| `CASH_WITHDRAWAL_LEFT_SCOPE` | External cash withdrawal. |
| `SECURITY_TRANSFER_ENTERED_SCOPE` | In-kind transfer in. |
| `SECURITY_TRANSFER_LEFT_SCOPE` | In-kind transfer out. |
| `CAPITAL_CALL` | Private-market contribution. |
| `DISTRIBUTION_TO_INVESTOR` | Distribution left measured scope. |
| `SYNTHETIC_BEGIN_MARKET_VALUE` | Beginning value inserted for MWRR. |
| `SYNTHETIC_END_MARKET_VALUE` | Ending value inserted for MWRR. |

Suggested excluded-flow reason codes:

| Code | Meaning |
|---|---|
| `INTERNAL_TRADE` | Buy/sell trade inside scope. |
| `INTERNAL_FX_CONVERSION` | Currency conversion inside scope. |
| `INVESTMENT_INCOME_RETAINED` | Dividend/coupon retained inside scope. |
| `INTERNAL_TRANSFER_WITHIN_GROUP` | Transfer did not cross group scope. |
| `CORPORATE_ACTION_NO_EXTERNAL_VALUE` | Corporate action did not move value across scope. |
| `FEE_EXCLUDED_BY_GROSS_BASIS` | Fee excluded according to gross methodology. |
| `TAX_EXCLUDED_BY_BEFORE_TAX_BASIS` | Tax excluded according to before-tax methodology. |

## 13. BA sign-off checklist

- [ ] Event taxonomy is complete for all source systems.
- [ ] Scope-aware internal transfer treatment is approved.
- [ ] Fee treatment is approved for gross and net basis.
- [ ] Tax treatment is approved for before-tax and after-tax basis.
- [ ] In-kind transfer valuation hierarchy is approved.
- [ ] FX conversion policy is approved.
- [ ] Same-day netting policy is approved.
- [ ] Reversal/correction policy is approved.
- [ ] Component-level MWRR caveats are approved.
- [ ] Evidence fields are sufficient for support and audit.
