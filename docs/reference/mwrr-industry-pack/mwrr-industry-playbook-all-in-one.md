# MWRR Industry Playbook - All in One

**Status:** Combined draft industry-methodology starter pack
**Last updated:** 2026-05-08


---

# MWRR Methodology

**Status:** Draft methodology guide  
**Audience:** Business, BA, QA, developers, production support  
**Last updated:** 2026-05-08

## 1. Definition

**Money-Weighted Rate of Return** is the return earned by the actual money invested in a portfolio or investment program, considering the timing and size of external cash flows.

MWRR answers:

> What return did the investor's money actually earn, given when money was added and withdrawn?

It is usually implemented as an **IRR** or **XIRR** calculation. In a dated portfolio environment, XIRR-style logic is normally preferred because cash flows are not always evenly spaced.

## 2. What MWRR measures

MWRR measures the investor experience. It includes:

- investment performance,
- external deposits,
- external withdrawals,
- in-kind transfers,
- capital calls,
- distributions,
- timing of flows,
- size of flows,
- reporting-currency FX effects,
- leverage effects when measured on NAV/equity,
- fee and tax effects depending on reporting basis.

MWRR is useful when the business question is:

- What did this client actually earn?
- How did cash-flow timing affect the outcome?
- What was the IRR of this account, fund, mandate, or private-market investment?
- What return was earned on the invested capital?

MWRR is less suitable when the question is:

- How did the manager perform independent of client cash-flow timing?
- What contributed additively to performance?
- How do allocation and selection effects reconcile to active return?

For those questions, TWRR, contribution, and attribution are usually more appropriate.

## 3. MWRR versus TWRR

The difference between MWRR and TWRR is central.

| Topic | MWRR | TWRR |
|---|---|---|
| Full name | Money-Weighted Rate of Return | Time-Weighted Rate of Return |
| Cash-flow timing impact | Included | Neutralized |
| Main use | Investor experience | Manager or strategy performance |
| Calculation style | IRR/XIRR over cash flows | Geometric linking of sub-period returns |
| Sensitive to deposits/withdrawals | Yes | No, if cash flows are handled correctly |
| Additive contribution support | No | Yes, through contribution/attribution methods |
| Best for private-market IRR | Yes | Sometimes secondary |
| Best for public-market manager comparison | Usually no | Usually yes |

Both metrics can be correct at the same time because they answer different questions.

## 4. Example: TWRR positive but MWRR negative

Assume a two-year path:

| Year | Portfolio return | Capital invested at start of year |
|---:|---:|---:|
| Year 1 | +50% | 100,000 |
| Year 2 | -10% | 1,000,000 after large deposit |

Timeline:

| Date | Event | Investor-perspective cash flow |
|---|---|---:|
| 2025-01-01 | Beginning value | -100,000 |
| 2026-01-01 | Large deposit after strong first year | -850,000 |
| 2027-01-01 | Ending value | +900,000 |

TWRR:

```text
(1 + 0.50) * (1 - 0.10) - 1 = 35.0000% cumulative
```

Annualized TWRR over two years:

```text
sqrt(1.35) - 1 = 16.1895%
```

MWRR/XIRR:

```text
approximately -4.7837% annualized
```

Interpretation:

- The strategy path did well over two years.
- The investor added most capital before the negative year.
- The investor's money-weighted experience was negative.

This is not a contradiction. It is the core reason both metrics exist.

## 5. Core formula

MWRR solves for the rate `r` that makes the net present value of all investor cash flows equal to zero:

```text
NPV(r) = sum_i CF_i / (1 + r) ^ tau_i = 0
```

Where:

| Symbol | Meaning |
|---|---|
| `CF_i` | Cash flow amount using the chosen sign convention. |
| `r` | Money-weighted return. If `tau_i` is a year fraction, `r` is annualized. |
| `tau_i` | Year fraction from anchor date to cash-flow date. |
| `i` | Cash-flow index. |

Using a common ACT/365 convention:

```text
tau_i = calendar_days_between(anchor_date, cash_flow_date) / 365
```

The anchor date is usually the earliest cash-flow date in the solver vector. In normal portfolio-period reporting, this is usually the measurement start date because the beginning market value is inserted there.

## 6. Cash-flow signs

A consistent sign convention is mandatory.

### Investor-perspective convention

| Event | Sign |
|---|---:|
| Beginning market value | Negative |
| Deposit into measured scope | Negative |
| Transfer in to measured scope | Negative |
| Capital call | Negative |
| Withdrawal from measured scope | Positive |
| Transfer out from measured scope | Positive |
| Distribution to investor | Positive |
| Ending market value | Positive |

This convention treats money invested into the portfolio as an investor outflow and money received from the portfolio as an investor inflow.

### Portfolio-perspective convention

Some systems store flows from the portfolio's perspective:

| Event | Sign |
|---|---:|
| Deposit into portfolio | Positive |
| Withdrawal from portfolio | Negative |

Either convention can work, but the solver and evidence must be explicit. Do not mix conventions.

## 7. Synthetic beginning and ending flows

MWRR normally creates synthetic cash flows from valuations:

| Synthetic flow | Date | Investor-perspective amount |
|---|---|---:|
| Beginning market value | Period start | `-BMV` |
| Ending market value | Period end | `+EMV` |

These are not source transactions. They are calculation constructs. They should still be stored or exposed as evidence so the result can be reproduced.

## 8. External cash flows

External cash flows are movements of value into or out of the measurement scope from outside.

Usually external:

- cash deposit,
- cash withdrawal,
- security transfer in,
- security transfer out,
- capital call,
- distribution to investor,
- subscription,
- redemption,
- in-kind distribution leaving the measured scope.

Usually not external:

- buy trade,
- sell trade,
- dividend received inside portfolio,
- coupon received inside portfolio,
- FX conversion inside portfolio,
- reinvested income,
- realized gain/loss,
- unrealized gain/loss,
- internal transfer inside the same measured group.

The governing question is:

> Did value enter or leave the measurement scope from outside?

## 9. Scope matters

The same event can be external for one scope and internal for another.

| Event | Single account scope | Household/group scope |
|---|---|---|
| Cash transfer from Account A to Account B in same household | External to A and B individually | Internal to household; exclude |
| Security transfer from external custodian into Account A | External | External |
| Buy equity using account cash | Internal | Internal |
| Dividend received into account cash | Investment income | Investment income |

Implementation consequence:

> Flow classification must be performed after resolving the measurement scope.

## 10. Annualized versus holding-period MWRR

XIRR-style MWRR is often annualized because the exponent uses year fractions.

For short periods, annualized returns can look surprisingly large.

Example:

| Date | Cash flow |
|---|---:|
| 2026-01-01 | -100,000 |
| 2026-01-31 | +101,000 |

Holding-period return:

```text
1.0000%
```

Annualized MWRR using ACT/365:

```text
(1.01) ^ (365 / 30) - 1 = 12.8695%
```

Recommended display policy:

| Period | Recommended display treatment |
|---|---|
| MTD | Non-annualized primary; annualized optional with warning. |
| QTD | Non-annualized primary; annualized optional with warning. |
| YTD | Non-annualized primary unless business policy says otherwise. |
| 1Y | Annualized and holding-period values are effectively aligned. |
| More than 1Y | Annualized primary; cumulative optional. |
| Since inception less than 1Y | Non-annualized primary. |
| Since inception more than 1Y | Annualized primary; cumulative optional. |

Always label the result.

## 11. Modified Dietz

Modified Dietz is an approximation to money-weighted return. It is often used when a full IRR solve is unnecessary, unstable, unavailable, or when a platform calculates short-period flow-adjusted returns.

Using portfolio-perspective flow signs:

```text
R_MD = (EMV - BMV - sum(CF_i)) / (BMV + sum(w_i * CF_i))
```

Where:

| Symbol | Meaning |
|---|---|
| `BMV` | Beginning market value. |
| `EMV` | Ending market value. |
| `CF_i` | External cash flow into the portfolio is positive; outflow is negative. |
| `w_i` | Fraction of the period for which the cash flow was invested. |

Modified Dietz is useful when:

- an approximation is acceptable,
- the period is short,
- cash flows are not extreme relative to market value,
- the calculation must be simple and stable,
- a fallback is required and explicitly labeled.

Modified Dietz is weaker when:

- flows are large,
- flows occur during volatile periods,
- market value is near zero,
- the period is long,
- exact cash-flow timing is economically important.

Do not silently present Modified Dietz as XIRR.

## 12. Gross, net, before-tax, and after-tax basis

MWRR must be calculated on a defined basis.

| Basis | Meaning |
|---|---|
| Gross of fees | Investment result before selected fees, according to methodology. |
| Net of fees | Investment result after selected fees. |
| Before tax | Tax effects excluded or added back according to policy. |
| After tax | Tax effects included according to policy. |

Fee treatment must be consistent with valuation treatment. A fee paid from portfolio cash usually reduces net return. A fee paid outside the portfolio requires an explicit methodology decision.

Do not mix gross and net treatment in the same result.

## 13. Reporting currency

MWRR should be calculated in the selected reporting currency.

For each valuation and cash flow:

1. determine source amount,
2. determine source currency,
3. select FX rate according to methodology,
4. convert to reporting currency,
5. store source and converted values for evidence.

If the portfolio contains non-reporting-currency assets, FX effects are part of the reporting-currency MWRR.

## 14. Benchmarks

Public-market benchmarks are usually time-weighted index return series. Comparing a portfolio MWRR directly against a time-weighted benchmark can be misleading unless the basis is explained.

Better approaches:

| Use case | Better practice |
|---|---|
| Public-market manager comparison | Use TWRR versus a time-weighted benchmark. |
| Client experience | Show MWRR with cash-flow context; show TWRR separately. |
| Private markets | Consider benchmark IRR, PME-style analysis, or cash-flow-matched benchmark analysis. |
| Client reporting | Label benchmark return type and methodology. |

## 15. Component-level MWRR

Component-level MWRR can be calculated for asset classes, sleeves, sectors, strategies, funds, or securities by treating allocation into and out of the component as cash flows.

However:

- component MWRRs do not sum to total portfolio MWRR,
- reallocations create component flows even when total portfolio has no external flow,
- asset-class reclassification can create artificial flows,
- component boundaries must be stable,
- component MWRR should not be presented as contribution.

Recommended label:

> Component MWRR measures the money-weighted return on capital allocated to that component. It is not an additive contribution to total portfolio return.

## 16. What MWRR should not be used for

Avoid using MWRR as the primary metric for:

- additive contribution,
- Brinson attribution reconciliation,
- manager ranking for client-directed flows,
- daily return linking,
- active-return decomposition,
- explaining sector/security contribution totals,
- comparing against a time-weighted benchmark without context.

## 17. Business explanation templates

### Simple explanation

> Money-weighted return reflects the return earned by the investor's money, including the effect of deposits, withdrawals, transfers, and when those flows occurred.

### Difference from TWRR

> Time-weighted return measures the strategy path independent of cash-flow timing. Money-weighted return reflects the investor experience because larger amounts of invested capital have more influence.

### Negative MWRR with positive TWRR

> The portfolio can have positive time-weighted performance but negative money-weighted performance if most money was added before weaker performance.

### High short-period annualized MWRR

> The annualized value converts a short-period result to a one-year rate. The holding-period return should be reviewed alongside it.

## 18. Methodology decisions to document

Before production use, document:

1. sign convention,
2. day-count basis,
3. annualization policy,
4. flow timing convention,
5. gross/net fee treatment,
6. tax treatment,
7. external cash-flow classification rules,
8. security-transfer valuation policy,
9. reporting-currency FX policy,
10. same-day netting policy,
11. internal-transfer treatment by scope,
12. stale valuation policy,
13. missing FX policy,
14. solver root-selection policy,
15. fallback policy,
16. precision and rounding policy,
17. data restatement policy,
18. evidence and audit policy.


---

# MWRR Calculation Methods

**Status:** Draft calculation guide  
**Audience:** Developers, QA, BA, quant/dev, production support  
**Last updated:** 2026-05-08

## 1. Calculation method overview

There are several related methods that may appear in industry systems:

| Method | Description | Typical use |
|---|---|---|
| Simple return | `(EMV - BMV) / BMV` when no flows exist | No external-flow periods. |
| IRR | Internal rate of return for periodic or equally spaced cash flows | Less common in dated portfolio ledgers. |
| XIRR-style MWRR | IRR using actual cash-flow dates | Standard dated cash-flow MWRR implementation. |
| Modified Dietz | Flow-weighted approximation | Short-period approximation or explicit fallback. |
| MIRR | Modified IRR using finance/reinvestment assumptions | More common in corporate finance than portfolio reporting. |

Recommended default for dated investment reporting:

```text
Primary method: XIRR-style MWRR
Fallback or secondary method: Modified Dietz, explicitly labeled
```

## 2. Solver cash-flow vector

A normal portfolio-period MWRR cash-flow vector includes:

1. synthetic beginning market value,
2. external cash flows during the period,
3. synthetic ending market value.

Using investor-perspective signs:

| Date | Event | Cash flow |
|---|---|---:|
| Period start | Beginning market value | `-BMV` |
| Flow date | Deposit / transfer in / capital call | Negative |
| Flow date | Withdrawal / transfer out / distribution | Positive |
| Period end | Ending market value | `+EMV` |

Example:

| Date | Event | Cash flow |
|---|---|---:|
| 2026-01-01 | Beginning market value | -100,000 |
| 2026-07-01 | Deposit | -100,000 |
| 2027-01-01 | Ending market value | +230,000 |

## 3. XIRR-style equation

The MWRR is the rate `r` satisfying:

```text
sum_i CF_i / (1 + r) ^ tau_i = 0
```

Where:

```text
tau_i = days_between(anchor_date, cash_flow_date_i) / day_count_basis
```

Common day-count basis:

```text
day_count_basis = 365
```

The rate `r` is annualized when the exponent is measured in years.

## 4. Day-count conventions

| Basis | Description | Notes |
|---|---|---|
| ACT/365 | Actual calendar days divided by 365 | Common for XIRR-style calculations and spreadsheet comparability. |
| ACT/ACT | Actual days divided by actual year length | More precise across leap years, but may differ from common XIRR expectations. |
| ACT/360 | Actual days divided by 360 | Common in money markets, less common for portfolio MWRR. |
| 30/360 | Thirty-day month convention | Usually not preferred for multi-asset portfolio MWRR. |

Select one basis as methodology policy. Expose it in evidence.

## 5. Annualized and holding-period conversion

If `r_annual` is the annualized XIRR-style result and the measurement period has `D` calendar days:

```text
holding_period_return = (1 + r_annual) ^ (D / day_count_basis) - 1
```

If a holding-period return is known and must be annualized:

```text
annualized_return = (1 + holding_period_return) ^ (day_count_basis / D) - 1
```

Do not convert negative rates less than or equal to `-100%`. The expression `(1 + return)` must remain positive.

## 6. Simple no-flow case

If there are no external flows, and BMV and EMV are valid:

```text
holding_period_return = (EMV - BMV) / BMV
```

Example:

| Date | Event | Cash flow |
|---|---|---:|
| 2026-01-01 | Beginning value | -100,000 |
| 2027-01-01 | Ending value | +110,000 |

Result:

```text
(110,000 - 100,000) / 100,000 = 10.0000%
```

For a one-year ACT/365 period, annualized MWRR is also 10.0000%.

## 7. Mid-year deposit example

Cash flows:

| Date | Event | Cash flow |
|---|---|---:|
| 2026-01-01 | Beginning value | -100,000 |
| 2026-07-01 | Deposit | -100,000 |
| 2027-01-01 | Ending value | +230,000 |

Equation under ACT/365:

```text
-100,000
-100,000 / (1 + r) ^ (181 / 365)
+230,000 / (1 + r) ^ (365 / 365)
= 0
```

Result:

```text
annualized MWRR approximately 20.25568892%
```

Interpretation:

- Ending value grew by 30,000 after adjusting for the 100,000 deposit.
- Because the deposit was invested for about half the period, the annualized IRR is higher than a simple return on total ending capital.

## 8. Modified Dietz example for the same case

Using portfolio-perspective flow signs:

| Item | Value |
|---|---:|
| BMV | 100,000 |
| Deposit | +100,000 |
| EMV | 230,000 |
| Period days | 365 |
| Deposit date | 2026-07-01 |
| Days from period start to deposit | 181 |
| Days remaining after deposit | 184 |
| End-of-day Dietz weight | 184 / 365 = 0.504109589 |

Formula:

```text
R_MD = (EMV - BMV - sum(CF_i)) / (BMV + sum(w_i * CF_i))
```

Calculation:

```text
R_MD = (230,000 - 100,000 - 100,000)
       / (100,000 + 0.504109589 * 100,000)
     = 0.1994535519
     = 19.94535519%
```

Dietz and XIRR are close here, but not identical.

## 9. Modified Dietz timing weights

Let:

| Symbol | Meaning |
|---|---|
| `D` | Total calendar days in period. |
| `d_i` | Calendar days from period start to cash-flow date. |

For end-of-day flow timing:

```text
w_i = (D - d_i) / D
```

For beginning-of-day flow timing:

```text
w_i = (D - d_i + 1) / D
```

Examples for a 365-day period:

| Flow date | End-of-day weight | Beginning-of-day weight |
|---|---:|---:|
| Start date | `365/365` or `1.0000` depending convention | `366/365` should usually be capped or handled by policy |
| Day after start | `364/365` | `365/365` |
| Mid-period | About `0.50` | About `0.50` plus one day |
| End date | `0/365` | `1/365` |

Define the convention clearly. For beginning-of-day formulas, avoid accidental weights greater than one by specifying how start-date flows combine with beginning market value.

## 10. Portfolio-perspective versus investor-perspective Modified Dietz

Modified Dietz formulas are often written with portfolio-perspective flows:

- deposit into portfolio = positive,
- withdrawal from portfolio = negative.

XIRR examples are often written with investor-perspective flows:

- deposit into portfolio = negative,
- withdrawal from portfolio = positive.

Implementation must normalize signs before calculation. A common production pattern is:

1. store source events with source sign,
2. classify event type,
3. normalize to a calculation sign convention,
4. persist normalized amount in evidence,
5. solve using normalized values.

## 11. Annualized short-period example

Cash flows:

| Date | Cash flow |
|---|---:|
| 2026-01-01 | -100,000 |
| 2026-01-31 | +101,000 |

Holding-period return:

```text
1.0000%
```

Days:

```text
30
```

Annualized result:

```text
(1.01) ^ (365 / 30) - 1 = 12.86952942%
```

Recommended warning if annualized value is displayed:

```text
SHORT_PERIOD_ANNUALIZED
```

## 12. Since-inception calculation

For since-inception MWRR:

1. identify inception date,
2. include the first capital invested or beginning value,
3. include all external flows after inception,
4. include residual ending value,
5. solve XIRR over full dated cash-flow stream.

For private-market assets, since-inception MWRR often uses:

- contributions or capital calls,
- distributions,
- residual NAV,
- recallable distribution policy where applicable,
- equalization or transfer treatment where applicable.

## 13. Periodic IRR versus dated XIRR

If cash flows are equally spaced, a periodic IRR formulation can be used:

```text
sum_t CF_t / (1 + r_period) ^ t = 0
```

Then convert to annualized return depending on period frequency:

```text
annualized = (1 + r_period) ^ periods_per_year - 1
```

However, real portfolio cash flows are usually irregular. Dated XIRR-style MWRR is usually more appropriate.

## 14. Handling zero cash flows

Zero cash flows do not affect the equation. They can be removed from the solver input after evidence capture.

Do not let zero-only vectors produce a 0% return. If there is no economic content, return `NOT_APPLICABLE` or `NOT_CALCULABLE` according to policy.

## 15. Handling same-day flows

Same-day flows should usually be netted after sign normalization.

Example:

| Date | Source event | Investor-perspective amount |
|---|---|---:|
| 2026-04-10 | Deposit | -100,000 |
| 2026-04-10 | Withdrawal | +30,000 |

Solver input:

| Date | Net amount |
|---|---:|
| 2026-04-10 | -70,000 |

Keep both source events in evidence.

## 16. Cash-flow stream validity

The solver requires both positive and negative cash flows.

Valid example:

```text
[-100,000, -50,000, +175,000]
```

Invalid examples:

```text
[-100,000, -50,000]
[+100,000, +50,000]
[0, 0, 0]
```

Return a clear reason code for invalid streams.

## 17. Multiple-root example

Cash flows:

| Date | Cash flow |
|---|---:|
| 2026-01-01 | -100 |
| 2027-01-01 | +230 |
| 2028-01-01 | -132 |

This cash-flow pattern has two valid annual IRRs:

```text
10% and 20%
```

Recommended behavior:

- detect multiple roots,
- return `NOT_CALCULABLE` or `AMBIGUOUS_IRR` by default,
- provide diagnostic root count,
- do not silently choose one root.

## 18. Recommended calculation fields

A calculation result should include:

| Field | Purpose |
|---|---|
| `method` | XIRR, IRR, Modified Dietz, fallback method. |
| `money_weighted_return` | Primary value according to display policy. |
| `annualized_return` | Annualized value when available. |
| `holding_period_return` | Exact-period value when available. |
| `is_annualized_primary` | Prevents display confusion. |
| `day_count_basis` | Required for reproducibility. |
| `sign_convention` | Required for interpretation. |
| `flow_timing` | Required for Dietz and dated treatment. |
| `basis` | Gross, net, before-tax, after-tax. |
| `reporting_currency` | Return currency context. |
| `solver_status` | Convergence and ambiguity state. |
| `warnings` | Explains suspicious or limited results. |
| `reason_codes` | Explains not-calculable or fallback cases. |


---

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


---

# MWRR Implementation Design

**Status:** Draft implementation guide  
**Audience:** Developers, architects, quant/dev, platform owners, QA, production support  
**Last updated:** 2026-05-08

## 1. Target behavior

A production MWRR engine should produce results that are:

1. mathematically correct for the selected method,
2. consistent with approved methodology,
3. reproducible from persisted evidence,
4. robust under edge cases,
5. clearly labeled by method, basis, period, currency, and annualization,
6. explicit when not calculable,
7. stable under source-event ordering,
8. explainable by support teams and future agents.

Recommended primary calculation method:

```text
XIRR-style MWRR using actual dated external cash flows
```

Recommended fallback, if approved:

```text
Modified Dietz, explicitly labeled as approximation or fallback
```

## 2. Inputs

Minimum inputs:

| Input | Required? | Notes |
|---|---:|---|
| Measurement scope | Yes | Portfolio, account, group, mandate, fund, sleeve, component, etc. |
| Period start date | Yes | Measurement start date. |
| Period end date | Yes | Measurement end date. |
| Reporting currency | Yes | All values converted to this currency. |
| Beginning market value | Usually | Required unless zero-start policy applies. |
| Ending market value | Yes | Terminal value. |
| Candidate cash-flow events | Yes, can be empty | Deposits, withdrawals, transfers, fees, taxes, private-market flows, etc. |
| Flow classification rules | Yes | Determines external versus internal. |
| Valuation data | Yes | For beginning/end values and in-kind transfers. |
| FX rates | Conditional | Required for non-reporting-currency values. |
| Fee/tax methodology | Yes | Determines basis-adjusted values and flows. |
| Day-count basis | Yes | Example: ACT/365. |
| Sign convention | Yes | Example: investor perspective. |
| Flow timing policy | Yes | Date-only, beginning-of-day, end-of-day, timestamp. |

## 3. Basis-adjusted calculation view

Build a methodology-specific view before calculating MWRR.

Examples:

| Basis | View construction |
|---|---|
| Net | Include fees/expenses/taxes according to net policy. |
| Gross | Add back or exclude selected fees according to gross policy. |
| Before tax | Exclude/add back taxes according to policy. |
| After tax | Include tax effects according to policy. |

Avoid adjusting only the final return after calculation. The correct pattern is:

```text
source data -> methodology-specific valuation/flow view -> MWRR calculation
```

## 4. Normalized cash-flow ledger

Create a normalized cash-flow ledger independent of source transaction formats.

Suggested fields:

```json
{
  "calculation_id": "calc-001",
  "scope_type": "PORTFOLIO",
  "scope_id": "P12345",
  "period_start": "2026-01-01",
  "period_end": "2026-12-31",
  "reporting_currency": "USD",
  "cash_flow_id": "cf-001",
  "source_event_id": "txn-123",
  "cash_flow_date": "2026-07-01",
  "cash_flow_role": "EXTERNAL_FLOW",
  "event_type": "CASH_DEPOSIT",
  "instrument_id": null,
  "source_amount": 100000.00,
  "source_currency": "USD",
  "fx_rate_to_reporting": 1.0,
  "amount_reporting_currency": -100000.00,
  "sign_convention": "INVESTOR_PERSPECTIVE",
  "flow_timing": "END_OF_DAY",
  "classification": "INCLUDED_EXTERNAL",
  "classification_reason": "CASH_DEPOSIT_ENTERED_SCOPE",
  "valuation_source": null,
  "is_synthetic": false,
  "is_reversal": false,
  "reversal_of_cash_flow_id": null
}
```

Synthetic beginning and ending flows should be represented as evidence:

| Role | Date | Investor-perspective amount |
|---|---|---:|
| `BEGINNING_MARKET_VALUE` | Start date | `-BMV` |
| `ENDING_MARKET_VALUE` | End date | `+EMV` |

## 5. Output contract

Suggested response shape:

```json
{
  "calculation_id": "calc-20260508-001",
  "status": "CALCULATED",
  "scope": {
    "type": "PORTFOLIO",
    "id": "P12345"
  },
  "period": {
    "start_date": "2026-01-01",
    "end_date": "2027-01-01",
    "total_days": 365
  },
  "reporting_currency": "USD",
  "basis": "NET",
  "methodology": {
    "return_type": "MONEY_WEIGHTED_RETURN",
    "method": "XIRR",
    "methodology_version": "mwrr.v1",
    "sign_convention": "INVESTOR_PERSPECTIVE",
    "day_count_basis": "ACT_365",
    "flow_timing": "DATE_ONLY",
    "annualization_policy": "ANNUALIZED_FOR_PERIODS_GE_1Y"
  },
  "result": {
    "money_weighted_return": 0.2025568892,
    "money_weighted_return_pct": 20.25568892,
    "annualized_return": 0.2025568892,
    "annualized_return_pct": 20.25568892,
    "holding_period_return": 0.2025568892,
    "holding_period_return_pct": 20.25568892,
    "is_annualized_primary": true
  },
  "solver": {
    "status": "CONVERGED_UNIQUE_ROOT",
    "algorithm": "BRACKETED_BRENT",
    "iterations": 18,
    "residual_npv": 0.0000001,
    "root_count_detected": 1,
    "rate_lower_bound": -0.999999999,
    "rate_upper_bound": 1000.0
  },
  "cash_flow_summary": {
    "beginning_market_value": 100000.0,
    "ending_market_value": 230000.0,
    "external_inflows_to_portfolio": 100000.0,
    "external_outflows_from_portfolio": 0.0,
    "normalized_solver_flow_count": 3
  },
  "warnings": [],
  "reason_codes": [],
  "evidence_ref": "evidence://calc-20260508-001"
}
```

## 6. Calculation algorithm

### Step 1: Resolve request

Validate:

- scope type,
- scope ID,
- period start,
- period end,
- reporting currency,
- basis,
- requested method,
- methodology version.

Reject invalid date ranges.

### Step 2: Resolve measurement scope

Determine boundaries:

- single portfolio,
- group of portfolios,
- fund,
- sleeve,
- component,
- composite.

This boundary controls whether a transfer is external or internal.

### Step 3: Load valuations

Load beginning and ending values in reporting currency and selected basis.

Validation:

- beginning valuation exists or zero-start policy applies,
- ending valuation exists,
- valuations are not stale beyond policy,
- valuation source and timestamp are recorded,
- values are finite numbers,
- negative values are allowed only if policy permits.

### Step 4: Load candidate events

Load events that may affect MWRR:

- cash deposits,
- cash withdrawals,
- security transfers,
- capital calls,
- distributions,
- subscriptions,
- redemptions,
- fee and tax events if relevant,
- reversals and corrections,
- account opening/closing events.

### Step 5: Classify events

For each event, determine:

- included or excluded,
- external or internal,
- reason code,
- scope-dependence,
- basis-dependence,
- reversal/correction status.

### Step 6: Value and convert events

For included events:

1. determine effective cash-flow date,
2. determine source amount and currency,
3. value in-kind transfers,
4. convert to reporting currency,
5. apply sign convention,
6. store normalized evidence.

### Step 7: Add synthetic valuation flows

Investor-perspective convention:

```text
period_start: -beginning_market_value
period_end:   +ending_market_value
```

If beginning value is zero, policy may omit the zero flow from solver input while retaining zero-start evidence.

### Step 8: Net same-day flows

After sign normalization, net flows with the same effective date unless timestamp-level solving is used.

Benefits:

- lower numerical noise,
- deterministic solver input,
- easier evidence review,
- ordering independence.

### Step 9: Validate solver vector

Preconditions:

- at least one positive cash flow,
- at least one negative cash flow,
- all cash flows finite,
- dates valid,
- year fractions non-negative,
- rate domain supports `r > -1`,
- no missing required valuation, FX, or transfer value.

### Step 10: Solve

For XIRR:

```text
find r such that sum(CF_i / (1 + r) ^ tau_i) = 0
```

Recommended solver:

- bracketed root search,
- Brent or bisection refinement,
- multiple-root detection,
- explicit no-root handling,
- no single-guess Newton-only production default.

### Step 11: Convert display values

Return:

- annualized return,
- holding-period return,
- primary display return according to policy,
- annualization flag.

### Step 12: Attach evidence, warnings, and status

Return the result with:

- calculation evidence reference,
- solver status,
- warnings,
- reason codes,
- fallback information,
- data quality indicators.

## 7. Status model

Recommended statuses:

| Status | Meaning |
|---|---|
| `CALCULATED` | Result calculated successfully. |
| `CALCULATED_WITH_WARNINGS` | Result calculated, but warnings apply. |
| `NOT_CALCULABLE` | Required data or mathematical conditions failed. |
| `PARTIAL_DATA` | Calculation blocked or weakened by incomplete data. |
| `FALLBACK_USED` | Alternative method used. |
| `SUPERSEDED` | Result replaced by later data or methodology. |
| `NOT_APPLICABLE` | No economic content or scope not applicable. |

## 8. Reason codes

Suggested reason codes:

| Code | Meaning |
|---|---|
| `INVALID_DATE_RANGE` | Start/end dates invalid. |
| `MISSING_BEGIN_VALUATION` | Beginning value missing and zero-start policy not applicable. |
| `MISSING_END_VALUATION` | Ending value missing. |
| `STALE_BEGIN_VALUATION` | Beginning valuation too old. |
| `STALE_END_VALUATION` | Ending valuation too old. |
| `MISSING_FX_RATE` | Required FX conversion unavailable. |
| `TRANSFER_VALUATION_MISSING` | In-kind transfer cannot be valued. |
| `NO_POSITIVE_AND_NEGATIVE_CASH_FLOW` | IRR precondition failed. |
| `NO_ROOT_FOUND` | No valid root found. |
| `MULTIPLE_IRR_ROOTS_DETECTED` | More than one root found. |
| `SOLVER_DID_NOT_CONVERGE` | Numerical solver failed. |
| `NEGATIVE_NAV_POLICY_BLOCK` | Negative NAV calculation blocked by policy. |
| `NEAR_ZERO_NAV_WARNING` | NAV too small for stable interpretation. |
| `MODIFIED_DIETZ_FALLBACK_USED` | Approximate fallback used. |
| `SHORT_PERIOD_ANNUALIZED` | Annualized short-period value may be surprising. |
| `RESULT_SUPERSEDED` | Result changed after source data or methodology update. |

## 9. Warnings

Warnings should not necessarily block calculation.

Examples:

| Warning | Meaning |
|---|---|
| `SHORT_PERIOD_ANNUALIZED` | Annualized value over short period. |
| `LARGE_EXTERNAL_FLOW` | Flow materially large relative to portfolio value. |
| `MWRR_TWRR_DIVERGENCE` | MWRR and TWRR differ materially. |
| `NEAR_ZERO_NAV` | Return may be unstable. |
| `NEGATIVE_NAV` | Special interpretation required. |
| `STALE_VALUATION_USED` | Calculation used stale valuation under allowed policy. |
| `FX_FALLBACK_USED` | Secondary FX source or prior rate used. |
| `TRANSFER_VALUATION_OVERRIDE_USED` | Manual or non-standard transfer value used. |
| `FALLBACK_METHOD_USED` | Result is not primary XIRR method. |

## 10. Evidence design

Every result should be reproducible.

Evidence should include:

1. request parameters,
2. methodology version,
3. selected basis,
4. sign convention,
5. day-count basis,
6. annualization policy,
7. flow timing convention,
8. valuation snapshots,
9. source events considered,
10. included external flows,
11. excluded internal events with reasons where feasible,
12. FX rates,
13. transfer valuations,
14. normalized solver vector,
15. solver diagnostics,
16. output values,
17. warnings and reason codes,
18. source data versions,
19. calculation timestamp,
20. supersession/restatement links.

## 11. Caching and idempotence

Cache key should include all methodology-affecting inputs:

- scope type,
- scope ID,
- period start,
- period end,
- reporting currency,
- basis,
- method,
- day-count basis,
- flow timing policy,
- sign convention,
- methodology version,
- source data snapshot version,
- valuation version,
- FX version,
- classification rule version.

If any of these changes, invalidate or supersede the result.

## 12. Pseudocode

```python
def calculate_mwrr(request):
    policy = load_policy(request.methodology_version, request.basis)
    validate_request(request)

    scope = resolve_scope(request.scope_type, request.scope_id)

    begin_mv = load_begin_market_value(scope, request.start_date, request.reporting_currency, policy)
    end_mv = load_end_market_value(scope, request.end_date, request.reporting_currency, policy)

    candidate_events = load_candidate_cash_flow_events(scope, request.start_date, request.end_date)

    included_flows = []
    excluded_events = []

    for event in candidate_events:
        classification = classify_event(event, scope, policy)
        if not classification.is_external:
            excluded_events.append((event, classification.reason_code))
            continue

        valued = value_event(event, policy, request.reporting_currency)
        normalized = normalize_to_investor_perspective(valued, classification)
        included_flows.append(normalized)

    solver_flows = []

    if begin_mv is not None and begin_mv != 0:
        solver_flows.append(CashFlow(request.start_date, -begin_mv, "BEGINNING_MARKET_VALUE"))

    solver_flows.extend(included_flows)
    solver_flows.append(CashFlow(request.end_date, +end_mv, "ENDING_MARKET_VALUE"))

    solver_flows = net_same_day_flows(solver_flows)

    validation = validate_solver_flows(solver_flows, policy)
    if not validation.ok:
        return not_calculable(validation.reason_codes, evidence=build_evidence(...))

    if request.method == "XIRR":
        roots = find_xirr_roots(solver_flows, policy)
        if len(roots) == 1:
            annualized = roots[0]
            holding = annualized_to_holding_period(annualized, request.start_date, request.end_date, policy)
            return calculated(annualized, holding, evidence=build_evidence(...))

        if policy.modified_dietz_fallback_enabled:
            dietz = calculate_modified_dietz(begin_mv, end_mv, included_flows, policy)
            return fallback_used(dietz, fallback_reason="NO_UNIQUE_IRR_ROOT", evidence=build_evidence(...))

        return not_calculable("NO_UNIQUE_IRR_ROOT", evidence=build_evidence(...))

    if request.method == "MODIFIED_DIETZ":
        dietz = calculate_modified_dietz(begin_mv, end_mv, included_flows, policy)
        return calculated(dietz, dietz, evidence=build_evidence(...))
```

## 13. Implementation readiness checklist

- [ ] Cash-flow sign convention approved.
- [ ] Scope-aware classification implemented.
- [ ] Security transfer valuation implemented.
- [ ] FX conversion implemented and evidenced.
- [ ] Gross/net basis construction implemented.
- [ ] Same-day netting implemented.
- [ ] XIRR root search implemented.
- [ ] Multiple-root detection implemented.
- [ ] Modified Dietz explicitly labeled.
- [ ] Annualization policy implemented.
- [ ] Reason codes implemented.
- [ ] Evidence output implemented.
- [ ] QA golden cases implemented.
- [ ] Observability metrics implemented.
- [ ] Support playbook published.


---

# MWRR Solver and Numerical Controls

**Status:** Draft numerical design guide  
**Audience:** Developers, quant/dev, QA, production support  
**Last updated:** 2026-05-08

## 1. Why solver design matters

MWRR looks simple conceptually, but production-grade IRR solving requires care.

Common issues:

- no valid root,
- multiple valid roots,
- convergence to different roots depending on initial guess,
- extreme annualized values for short periods,
- instability near `r = -100%`,
- near-zero NAV or cash-flow scale problems,
- floating-point precision and residual tolerance disputes.

A production engine should not rely only on a spreadsheet-style single initial guess.

## 2. XIRR function

Given dated cash flows:

```text
(date_i, CF_i)
```

Define:

```text
tau_i = days_between(anchor_date, date_i) / day_count_basis
```

The function is:

```text
f(r) = sum_i CF_i / (1 + r) ^ tau_i
```

The solver finds:

```text
f(r) = 0
```

Domain:

```text
r > -1
```

The domain exists because `(1 + r)` appears in the denominator.

## 3. Recommended solver approach

Recommended production sequence:

1. normalize and net cash flows,
2. validate at least one positive and one negative cash flow,
3. transform rate domain if useful,
4. scan a grid for sign-changing brackets,
5. refine each bracket using Brent or bisection,
6. de-duplicate roots within tolerance,
7. classify root count,
8. return result only when policy permits.

Avoid a default design that does only:

```text
Newton(initial_guess = 10%)
```

Newton may be fast, but it can fail or converge to an arbitrary root.

## 4. Rate domain

Lower bound must be greater than -100%.

Suggested lower bound:

```text
r_min = -0.999999999
```

Suggested upper bound should be configurable.

Example:

```text
r_max = 1000.0
```

This means 100,000% annualized. Extreme values should be flagged, not necessarily blocked.

## 5. Log-rate transformation

For numerical stability, solve in log-rate space:

```text
x = ln(1 + r)
r = exp(x) - 1
```

Then:

```text
f(x) = sum_i CF_i * exp(-x * tau_i)
```

Benefits:

- avoids direct singularity at `r = -1`,
- supports wide rate ranges,
- handles extreme annualized short-period results better,
- makes bracketing more stable across large rate ranges.

Example bounds:

```text
x_min = ln(1 + r_min)
x_max = ln(1 + r_max)
```

## 6. Bracket scanning

A bracket exists when `f(a)` and `f(b)` have opposite signs.

Basic approach:

```text
for each adjacent pair in grid:
    if f(x_left) == 0:
        record root
    if f(x_left) * f(x_right) < 0:
        refine bracket
```

Grid strategies:

| Strategy | Notes |
|---|---|
| Linear grid in rate space | Simple but poor near -100% and extreme rates. |
| Linear grid in log-rate space | More stable across wide rate ranges. |
| Adaptive grid | More work, better for unusual streams. |
| Multi-pass grid | Coarse scan, then dense scan near sign changes. |

Recommended default:

```text
log-rate grid + bracketed refinement
```

## 7. Root refinement

Preferred algorithms:

| Algorithm | Pros | Cons |
|---|---|---|
| Brent | Fast and robust for bracketed roots | More implementation complexity. |
| Bisection | Very stable and simple | Slower. |
| Secant | Faster than bisection | Less robust without bracket. |
| Newton | Fast near solution | Can fail, diverge, or find arbitrary root. |

Recommended:

```text
Use Brent when available. Use bisection as safe fallback.
```

## 8. Root classification

| Root count | Status | Recommended behavior |
|---:|---|---|
| 0 | `NO_ROOT_FOUND` | Return not calculable or explicit fallback. |
| 1 | `CONVERGED_UNIQUE_ROOT` | Return result. |
| >1 | `MULTIPLE_IRR_ROOTS_DETECTED` | Return not calculable by default. |

## 9. Multiple-root example

Cash flows:

| Date | Cash flow |
|---|---:|
| 2026-01-01 | -100 |
| 2027-01-01 | +230 |
| 2028-01-01 | -132 |

For annual periods, the equation becomes:

```text
-100 + 230 / (1 + r) - 132 / (1 + r)^2 = 0
```

This has roots:

```text
r = 10%
r = 20%
```

Production behavior should not silently select one.

Recommended response:

```json
{
  "status": "NOT_CALCULABLE",
  "reason_code": "MULTIPLE_IRR_ROOTS_DETECTED",
  "solver": {
    "root_count_detected": 2
  }
}
```

## 10. No-root cases

A no-root case occurs when the cash-flow function does not cross zero within the configured domain.

Recommended behavior:

- return `NOT_CALCULABLE`,
- include `NO_ROOT_FOUND`,
- include search bounds,
- include cash-flow summary,
- optionally compute Modified Dietz separately if policy allows.

Do not force a root by widening bounds indefinitely without governance. Extremely wide bounds can produce unstable or economically meaningless results.

## 11. Tolerances

Suggested tolerances:

| Tolerance | Suggested default | Notes |
|---|---:|---|
| Rate tolerance | `1e-10` | Raw rate precision. |
| NPV absolute residual | `0.01` reporting currency | Good for money-scale checks. |
| NPV relative residual | `1e-10` of gross cash-flow scale | Helps across different portfolio sizes. |
| Root de-duplication tolerance | `1e-8` rate | Avoid duplicate adjacent-bracket roots. |
| Max iterations | 100 to 200 | Depends on algorithm. |

Use both absolute and relative checks. A residual of 0.01 may be too strict for tiny portfolios and too loose for very large portfolios if used alone.

## 12. Money precision

Recommended:

- persist money using decimal or integer minor units,
- do not persist rounded intermediate cash flows unless source accounting does,
- convert to solver numeric type only after final normalized amounts are prepared,
- store raw return at high precision,
- round only for display.

Avoid binary floating-point for persisted money.

## 13. Scaling cash flows

IRR is scale-invariant. Multiplying all cash flows by a positive constant should not change MWRR.

Example:

```text
[-100, -100, +230]
```

and

```text
[-1,000,000, -1,000,000, +2,300,000]
```

should return the same MWRR if dates are identical.

This is a useful property test.

## 14. Same-day netting and ordering

Solver results should not depend on source-event ordering.

Recommended process:

1. normalize signs,
2. group by effective date,
3. sum amounts,
4. remove zero net amounts if desired,
5. sort by date.

Keep pre-netted source evidence for audit.

## 15. Anchor date

Common choice:

```text
anchor_date = earliest cash-flow date in solver vector
```

In normal portfolio-period MWRR, this is the period start because the BMV flow is inserted at period start.

If BMV is zero and omitted, anchor date may become the first investment flow date.

Document the policy for:

- zero start,
- delayed first deposit,
- account reopening,
- since-inception calculation.

## 16. Negative rates and annualization

The rate domain is:

```text
r > -100%
```

A holding-period return of `-100%` cannot be annualized using normal compounding because `1 + return = 0`.

A result close to `-100%` should be flagged:

```text
EXTREME_NEGATIVE_RETURN
```

## 17. Extreme positive rates

Extreme positive annualized returns can happen when:

- period is very short,
- beginning value is tiny,
- large gain occurs soon after investment,
- leveraged NAV is near zero,
- cash-flow timing creates high IRR.

Do not automatically reject extreme positive rates, but warn and provide holding-period return and cash-flow context.

Suggested warning:

```text
EXTREME_ANNUALIZED_RETURN
```

## 18. Solver diagnostics

Return or store:

| Field | Purpose |
|---|---|
| algorithm | Brent, bisection, Newton, etc. |
| root_count_detected | Detect ambiguity. |
| iterations | Debug performance. |
| residual_npv | Confirms solve quality. |
| rate_lower_bound | Evidence of search domain. |
| rate_upper_bound | Evidence of search domain. |
| day_count_basis | Required for reproduction. |
| anchor_date | Required for reproduction. |
| normalized_flow_count | Debug vector construction. |
| gross_cash_flow_scale | Relative residual checks. |
| convergence_status | Support and monitoring. |

## 19. Modified Dietz fallback controls

If Modified Dietz fallback is enabled:

- return `method = MODIFIED_DIETZ`,
- return `fallback_from = XIRR`,
- return `fallback_reason`,
- return `is_approximation = true`,
- show warning,
- preserve XIRR failure diagnostics.

Example:

```json
{
  "status": "FALLBACK_USED",
  "method": "MODIFIED_DIETZ",
  "fallback_from": "XIRR",
  "fallback_reason": "MULTIPLE_IRR_ROOTS_DETECTED",
  "is_approximation": true
}
```

## 20. Pseudocode: root search

```python
def find_xirr_roots(cash_flows, policy):
    # cash_flows are sorted and same-day-netted.
    # amounts use investor-perspective sign convention.

    anchor = cash_flows[0].date

    def tau(flow):
        return days_between(anchor, flow.date) / policy.day_count_denominator

    taus = [tau(flow) for flow in cash_flows]
    amounts = [flow.amount for flow in cash_flows]

    def f_x(x):
        # x = ln(1 + r)
        return sum(amount * exp(-x * t) for amount, t in zip(amounts, taus))

    x_min = log(1 + policy.rate_min)
    x_max = log(1 + policy.rate_max)
    grid = make_grid(x_min, x_max, policy.grid_size)

    brackets = []
    prev_x = grid[0]
    prev_y = f_x(prev_x)

    for x in grid[1:]:
        y = f_x(x)
        if is_close(prev_y, 0, policy.npv_tolerance):
            brackets.append((prev_x, prev_x))
        elif prev_y * y < 0:
            brackets.append((prev_x, x))
        prev_x = x
        prev_y = y

    roots = []
    for left, right in brackets:
        if left == right:
            root_x = left
        else:
            root_x = brent_or_bisect(f_x, left, right, policy)
        root_r = exp(root_x) - 1
        roots.append(root_r)

    roots = deduplicate_roots(roots, policy.root_dedupe_tolerance)
    return roots
```

## 21. QA expectations for solver

Solver tests should prove:

- no-flow one-year simple case returns simple return,
- mid-year deposit case matches expected XIRR,
- same-day netting is order-independent,
- all-positive and all-negative streams are rejected,
- multiple-root case is detected,
- no-root cases are detected,
- short-period annualized values are converted correctly,
- scale invariance holds,
- residual tolerance is enforced,
- fallback is clearly labeled,
- solver bounds are configurable.


---

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


---

# MWRR QA and Regression Pack

**Status:** Draft QA guide  
**Audience:** QA, developers, BA, production support  
**Last updated:** 2026-05-08

## 1. QA goals

MWRR QA must test more than the formula. It must verify:

1. correct event inclusion,
2. correct event exclusion,
3. correct scope-aware classification,
4. correct sign normalization,
5. correct valuation and FX conversion,
6. correct synthetic beginning and ending flows,
7. correct same-day netting,
8. correct annualization and holding-period conversion,
9. correct solver behavior,
10. correct fallback labeling,
11. correct warning and reason-code output,
12. reproducible evidence.

## 2. Test tolerances

Suggested tolerances:

| Test type | Suggested tolerance |
|---|---:|
| Raw rate unit test | `1e-8` absolute rate difference. |
| Percentage display | `0.0001` percentage point for deterministic tests. |
| NPV residual | Less than `0.01` reporting-currency unit or relative threshold. |
| UI display | Match rounded business display, usually two decimals. |
| Money inputs | Exact decimals or integer minor units. |

## 3. Golden fixture shape

Example fixture:

```json
{
  "case_id": "MWRR_XIRR_002_MID_YEAR_DEPOSIT",
  "description": "Mid-year deposit with positive ending value",
  "method": "XIRR",
  "sign_convention": "INVESTOR_PERSPECTIVE",
  "day_count_basis": "ACT_365",
  "period_start": "2026-01-01",
  "period_end": "2027-01-01",
  "cash_flows": [
    { "date": "2026-01-01", "amount": -100000, "role": "BEGINNING_MARKET_VALUE" },
    { "date": "2026-07-01", "amount": -100000, "role": "EXTERNAL_FLOW" },
    { "date": "2027-01-01", "amount": 230000, "role": "ENDING_MARKET_VALUE" }
  ],
  "expected": {
    "status": "CALCULATED",
    "annualized_return": 0.2025568892,
    "annualized_return_pct": 20.25568892,
    "root_count_detected": 1
  }
}
```

## 4. Deterministic test cases

### Case 1: no external flows

Purpose: MWRR equals simple return when no external flows exist.

| Date | Cash flow | Role |
|---|---:|---|
| 2026-01-01 | -100,000 | Beginning market value |
| 2027-01-01 | +110,000 | Ending market value |

Expected:

| Metric | Value |
|---|---:|
| Status | `CALCULATED` |
| Annualized MWRR | `10.0000%` |
| Holding-period return | `10.0000%` |
| Root count | `1` |

### Case 2: mid-year deposit, XIRR

Purpose: dated deposit influences MWRR.

| Date | Cash flow | Role |
|---|---:|---|
| 2026-01-01 | -100,000 | Beginning market value |
| 2026-07-01 | -100,000 | Deposit |
| 2027-01-01 | +230,000 | Ending market value |

Expected under ACT/365:

| Metric | Value |
|---|---:|
| Status | `CALCULATED` |
| Annualized MWRR | `20.2557%` |
| Raw annualized rate | `0.2025568892` |
| Root count | `1` |

### Case 3: mid-year deposit, Modified Dietz

Purpose: compare Dietz approximation to XIRR and ensure method labeling.

Portfolio-perspective inputs:

| Item | Value |
|---|---:|
| BMV | 100,000 |
| EMV | 230,000 |
| Deposit on 2026-07-01 | +100,000 |
| Period days | 365 |
| Days from start to deposit | 181 |
| End-of-day weight | 184 / 365 = 0.504109589 |

Expected:

| Metric | Value |
|---|---:|
| Method | `MODIFIED_DIETZ` |
| Modified Dietz return | `19.9454%` |
| Raw rate | `0.1994535519` |
| Is approximation | `true` |

Formula:

```text
R_MD = (230,000 - 100,000 - 100,000)
       / (100,000 + 0.504109589 * 100,000)
     = 0.1994535519
```

### Case 4: short-period annualization

Purpose: annualized MWRR can be much larger than holding-period return.

| Date | Cash flow | Role |
|---|---:|---|
| 2026-01-01 | -100,000 | Investment |
| 2026-01-31 | +101,000 | Ending value |

Expected under ACT/365:

| Metric | Value |
|---|---:|
| Period days | `30` |
| Holding-period return | `1.0000%` |
| Annualized MWRR | `12.8695%` |
| Raw annualized rate | `0.1286952942` |
| Warning | `SHORT_PERIOD_ANNUALIZED` if annualized shown |

### Case 5: TWRR positive but MWRR negative

Purpose: show sensitivity to large deposit timing.

Cash flows:

| Date | Cash flow | Role |
|---|---:|---|
| 2025-01-01 | -100,000 | Beginning value |
| 2026-01-01 | -850,000 | Deposit |
| 2027-01-01 | +900,000 | Ending value |

Investment path:

| Year | TWRR sub-period return |
|---|---:|
| 2025 | +50% |
| 2026 | -10% |

Expected:

| Metric | Value |
|---|---:|
| Cumulative TWRR | `35.0000%` |
| Annualized TWRR | `16.1895%` |
| Annualized MWRR | approximately `-4.7837%` |
| Explanation | Large deposit was invested before weak second year. |

### Case 6: same-day netting

Purpose: source event ordering should not affect result.

Source events:

| Date | Event | Investor-perspective amount |
|---|---|---:|
| 2026-01-01 | Beginning value | -100,000 |
| 2026-04-10 | Deposit | -100,000 |
| 2026-04-10 | Withdrawal | +30,000 |
| 2027-01-01 | Ending value | +125,000 |

Solver vector after same-day netting:

| Date | Net amount |
|---|---:|
| 2026-01-01 | -100,000 |
| 2026-04-10 | -70,000 |
| 2027-01-01 | +125,000 |

Expected:

- same result regardless of source-event ordering,
- evidence retains both source events,
- normalized solver vector has one net flow on 2026-04-10.

### Case 7: invalid all-negative vector

Purpose: IRR precondition failure.

| Date | Cash flow |
|---|---:|
| 2026-01-01 | -100,000 |
| 2026-07-01 | -50,000 |

Expected:

| Field | Value |
|---|---|
| Status | `NOT_CALCULABLE` |
| Reason code | `NO_POSITIVE_AND_NEGATIVE_CASH_FLOW` |
| Return | `null` |

### Case 8: multiple roots

Purpose: detect ambiguous IRR.

| Date | Cash flow |
|---|---:|
| 2026-01-01 | -100 |
| 2027-01-01 | +230 |
| 2028-01-01 | -132 |

Expected:

| Field | Value |
|---|---|
| Status | `NOT_CALCULABLE` by default |
| Reason code | `MULTIPLE_IRR_ROOTS_DETECTED` |
| Roots detected | `10%` and `20%` |

This fixture should fail if the solver silently returns the first root only.

### Case 9: zero beginning value with later deposit

Purpose: valid calculation when portfolio starts empty.

| Date | Cash flow |
|---|---:|
| 2026-03-01 | -100,000 |
| 2026-12-31 | +110,000 |

Expected:

| Metric | Value |
|---|---:|
| Status | `CALCULATED` |
| Period days from first investment | `305` |
| Holding-period return | `10.0000%` |
| Annualized ACT/365 return | approximately `12.0819%` |

### Case 10: missing transfer valuation

Purpose: in-kind transfer cannot be included without value.

| Date | Event | Problem |
|---|---|---|
| 2026-06-01 | Security transfer in | Missing price and valuation source. |

Expected:

| Field | Value |
|---|---|
| Status | `NOT_CALCULABLE` or `PARTIAL_DATA` according to policy |
| Reason code | `TRANSFER_VALUATION_MISSING` |
| Included flow amount | No silent zero |

### Case 11: group-level internal transfer exclusion

Purpose: scope-aware classification.

Event:

| Date | Event |
|---|---|
| 2026-02-01 | Portfolio A transfers 50,000 cash to Portfolio B. |

Expected:

| Scope | Treatment |
|---|---|
| Portfolio A | External outflow from A. |
| Portfolio B | External inflow to B. |
| Household containing A and B | Exclude as internal transfer. |

### Case 12: non-reporting-currency flow

Purpose: FX conversion is included in solver value.

| Date | Event | Source amount | FX | Reporting amount |
|---|---|---:|---:|---:|
| 2026-07-01 | EUR deposit | EUR 100,000 | 1.10 USD/EUR | USD -110,000 |

Expected:

- source amount and currency preserved,
- FX rate and source preserved,
- solver uses USD -110,000,
- missing FX triggers reason code if unavailable.

### Case 13: zero economic content

Purpose: avoid misleading 0% return.

| Item | Value |
|---|---:|
| Beginning market value | 0 |
| Ending market value | 0 |
| External flows | none |

Expected:

| Field | Value |
|---|---|
| Status | `NOT_APPLICABLE` or approved equivalent |
| Return | `null` |
| Explanation | No investment exposure or economic content. |

### Case 14: fallback labeling

Purpose: Modified Dietz fallback must not be mislabeled.

Use a multiple-root or no-root XIRR case with fallback enabled.

Expected:

| Field | Value |
|---|---|
| Status | `FALLBACK_USED` |
| Method | `MODIFIED_DIETZ` |
| Fallback from | `XIRR` |
| Fallback reason | `NO_UNIQUE_IRR_ROOT` |
| Is approximation | `true` |

## 5. Property tests

### Ordering independence

Randomly shuffle source event order. Result should be unchanged after sorting and netting.

### Same-day netting equivalence

Separate same-day flows should produce the same result as the netted same-day flow.

### Scale invariance

Multiplying all cash flows by a positive constant should not change MWRR.

### Sign convention conversion

Portfolio-perspective flows converted to investor-perspective flows should match direct investor-perspective fixtures.

### No-flow equivalence

With only BMV and EMV:

```text
holding-period MWRR = (EMV - BMV) / BMV
```

### Reversal neutrality

A source event plus a full reversal should not create net performance impact if methodology treats them as offsetting.

### FX determinism

Given a fixed FX table, repeated calculations should produce the same reporting-currency flow amounts and MWRR.

## 6. Integration tests

### Portfolio-level pipeline

Validate:

1. valuation loading,
2. event loading,
3. classification,
4. transfer valuation,
5. FX conversion,
6. sign normalization,
7. same-day netting,
8. solving,
9. evidence output.

### Group-level pipeline

Validate internal transfers are excluded at group scope while included at single-portfolio scope.

### Gross/net pipeline

Create a fee event. Validate net MWRR differs from gross MWRR according to policy and evidence explains treatment.

### Restatement pipeline

Run calculation, then add backdated flow or corrected valuation. Validate:

- prior result is superseded,
- new result changes,
- restatement reason is recorded.

### Solver ambiguity pipeline

Use multiple-root fixture. Validate status and optional fallback behavior.

## 7. UI/API acceptance checks

BA and QA should verify:

- [ ] MWRR label says money-weighted or cash-flow-aware return.
- [ ] Annualized values are clearly labeled.
- [ ] Holding-period values are available where useful.
- [ ] Short-period annualized values have explanatory context.
- [ ] TWRR and MWRR are not presented as interchangeable.
- [ ] MWRR is not used as additive contribution.
- [ ] Gross/net basis is visible.
- [ ] Reporting currency is visible.
- [ ] Method is visible: XIRR, IRR, Modified Dietz, fallback, etc.
- [ ] Invalid results show reason codes.
- [ ] Evidence or drill-down can show included cash flows.
- [ ] Fallback results are clearly labeled.

## 8. Regression checklist

Run regression after changes to:

- solver implementation,
- cash-flow classification rules,
- fee methodology,
- tax methodology,
- FX source logic,
- valuation source logic,
- transfer matching logic,
- annualization policy,
- API schema,
- rounding/display formatting,
- data restatement logic,
- caching keys,
- evidence schema.

Regression should include:

1. deterministic golden cases,
2. randomized property tests,
3. production-like fixtures,
4. expected failure cases,
5. independent calculator comparison for selected XIRR cases,
6. UI display tests,
7. evidence reproduction tests.

## 9. Defect taxonomy

| Defect type | Example |
|---|---|
| Flow inclusion error | Buy trade incorrectly included as external flow. |
| Flow exclusion error | Cash deposit missing from solver vector. |
| Scope error | Internal transfer included at group scope. |
| Sign error | Deposit treated as positive investor-perspective flow. |
| FX error | Flow converted using wrong date or rate. |
| Valuation error | Transfer valued at stale or wrong price. |
| Annualization error | 30-day value displayed as annualized without label. |
| Solver error | Multiple-root case returns arbitrary result. |
| Fallback labeling error | Dietz result shown as XIRR. |
| Rounding error | API and UI disagree materially. |
| Evidence error | Result cannot be reproduced from persisted inputs. |
| Restatement error | Late correction changes result without superseding prior calculation. |

## 10. Minimum acceptance criteria

An MWRR implementation should not be production-ready until:

1. deterministic XIRR cases pass,
2. Modified Dietz cases pass if method is supported,
3. multiple-root and no-root cases are controlled,
4. same-day netting is order-independent,
5. cash-flow classification has BA approval,
6. security transfer valuation is tested,
7. FX conversion is tested,
8. group-level internal transfer exclusion is tested,
9. annualization policy is tested,
10. gross/net treatment is tested,
11. evidence output reproduces the result,
12. not-calculable statuses are user-friendly,
13. observability captures failure and warning rates.


---

# MWRR Production Support and Agent Playbook

**Status:** Draft support guide  
**Audience:** Operations, support analysts, SRE, business support, future production-support agents  
**Last updated:** 2026-05-08

## 1. Purpose

This playbook helps support teams and future agents explain, troubleshoot, and escalate MWRR questions.

Most production MWRR questions are caused by:

- cash-flow timing,
- cash-flow classification,
- annualization confusion,
- scope mismatch,
- gross/net basis mismatch,
- FX conversion,
- missing valuations,
- stale prices,
- fallback methods,
- late or corrected data.

The formula is rarely the only issue.

## 2. First-response principles

When answering an MWRR query:

1. confirm period,
2. confirm measurement scope,
3. confirm reporting currency,
4. confirm basis: gross, net, before-tax, after-tax,
5. confirm method: XIRR, IRR, Modified Dietz, fallback,
6. confirm annualized versus holding-period display,
7. inspect major external flows,
8. inspect solver status and reason codes,
9. avoid comparing MWRR to TWRR without explaining the difference,
10. avoid claiming the number is wrong before reviewing evidence.

## 3. Minimum evidence to retrieve

| Evidence item | Why |
|---|---|
| Calculation ID | Reproducibility. |
| Methodology version | Detect methodology changes. |
| Scope type and ID | Classification depends on scope. |
| Period start/end | Period mistakes are common. |
| Reporting currency | FX effects can drive result. |
| Basis | Gross/net/tax treatment can change result. |
| Beginning and ending market values | Core synthetic flows. |
| Normalized cash-flow vector | Solver input. |
| Included source events | Verify external flows. |
| Excluded source events | Verify internal-flow treatment. |
| FX rates | Verify currency conversion. |
| Transfer valuations | Verify in-kind flows. |
| Solver status | Convergence and ambiguity. |
| Annualization policy | Prevent short-period confusion. |
| Warnings and reason codes | Explain abnormal behavior. |
| Prior calculation if changed | Support restatement analysis. |

## 4. Common questions and answer patterns

### Question: Why is MWRR different from TWRR?

Answer pattern:

> MWRR includes the timing and size of deposits, withdrawals, and transfers. TWRR neutralizes external cash-flow timing to show the strategy path. The difference is usually caused by when large flows occurred relative to portfolio performance.

Evidence to show:

- MWRR,
- TWRR,
- period,
- major cash flows,
- performance before and after major flows.

### Question: Why is MWRR negative when TWRR is positive?

Answer pattern:

> This can happen when the portfolio performed well while less money was invested, and more money was added before weaker performance. MWRR gives more influence to the periods when more capital was invested.

Evidence to show:

- largest deposits,
- performance after deposits,
- TWRR path,
- MWRR cash-flow vector.

### Question: Why is MWRR extremely high?

Answer pattern:

> The result may be annualized over a short period, or the portfolio may have had a small beginning value, near-zero NAV, leverage, or a large flow near the period end. The holding-period return and cash-flow timeline should be reviewed alongside the annualized value.

Evidence to show:

- annualized return,
- holding-period return,
- period length,
- beginning/ending values,
- major flows,
- near-zero NAV or leverage warning.

### Question: Why does MWRR not equal contribution totals?

Answer pattern:

> MWRR is an IRR-style return based on cash flows. Contribution is usually a TWR-based additive explanation by asset, sector, security, or strategy. Component MWRRs do not sum to total MWRR.

Evidence to show:

- contribution methodology,
- MWRR methodology,
- statement that MWRR is not additive.

### Question: Why did MWRR change after a previous report?

Answer pattern:

> MWRR can change if late or corrected data changes cash flows, valuations, FX rates, transfer values, fee/tax classification, or methodology. Compare the prior and current calculation evidence to identify the driver.

Evidence to show:

- prior calculation ID,
- current calculation ID,
- changed cash flows,
- changed valuations,
- changed FX rates,
- method/basis changes,
- restatement reason.

### Question: Why is MWRR blank or not calculable?

Answer pattern:

> The calculation could not produce a reliable result for this period. The reason code identifies the blocker, such as missing valuation, missing FX, missing transfer value, invalid cash-flow signs, no root, multiple roots, or solver failure.

Evidence to show:

- status,
- reason code,
- missing data or solver diagnostics,
- fallback availability.

### Question: Why was Modified Dietz used?

Answer pattern:

> Modified Dietz was used because the primary XIRR calculation was unavailable or ambiguous according to methodology. It is an approximation and is labeled separately from XIRR.

Evidence to show:

- fallback reason,
- XIRR solver status,
- Modified Dietz inputs,
- fallback warning.

## 5. Triage decision tree

### Step 1: Confirm period

Check:

- requested start date,
- requested end date,
- as-of date,
- inception date,
- closure/reopen dates,
- UI horizon selection.

Common issue:

```text
User expects YTD, but selected trailing 1Y or since-inception.
```

### Step 2: Confirm scope

Check:

- portfolio versus group,
- household versus account,
- sleeve/component versus total portfolio,
- fund/share class versus investor account.

Common issue:

```text
Transfer is external at account level but internal at household level.
```

### Step 3: Confirm basis

Check:

- gross or net,
- before-tax or after-tax,
- fee treatment,
- tax treatment,
- reporting currency.

Common issue:

```text
User compares net MWRR to gross TWRR.
```

### Step 4: Check annualization

Check:

- period length,
- annualized flag,
- holding-period value,
- short-period warning.

Common issue:

```text
1% over 30 days appears as about 12.87% annualized.
```

### Step 5: Review major flows

Inspect flows by absolute size.

Questions:

- Were deposits included?
- Were withdrawals included?
- Were security transfers valued?
- Were internal transfers excluded at group scope?
- Were fees/taxes treated according to basis?
- Were reversals handled correctly?

### Step 6: Review solver status

Check:

- converged unique root,
- no root,
- multiple roots,
- fallback used,
- residual NPV,
- root count,
- solver bounds.

### Step 7: Review data changes

Check:

- late bookings,
- corrected transactions,
- corrected FX rates,
- corrected valuations,
- transfer valuation changes,
- methodology version changes.

## 6. Reason-code guide

| Code | Support explanation |
|---|---|
| `MISSING_END_VALUATION` | The calculation needs an ending value to use as terminal value. |
| `MISSING_BEGIN_VALUATION` | The calculation needs a beginning value unless zero-start policy applies. |
| `MISSING_FX_RATE` | A non-reporting-currency amount could not be converted. |
| `TRANSFER_VALUATION_MISSING` | An in-kind transfer could not be valued. |
| `NO_POSITIVE_AND_NEGATIVE_CASH_FLOW` | IRR requires at least one investment outflow and one inflow or terminal value. |
| `NO_ROOT_FOUND` | The cash-flow pattern did not produce a valid root in configured bounds. |
| `MULTIPLE_IRR_ROOTS_DETECTED` | More than one valid IRR exists, so the system did not choose arbitrarily. |
| `SOLVER_DID_NOT_CONVERGE` | The numerical solver failed to converge. |
| `MODIFIED_DIETZ_FALLBACK_USED` | Approximate fallback used instead of primary XIRR. |
| `SHORT_PERIOD_ANNUALIZED` | Annualized value may look large because the period is short. |
| `NEAR_ZERO_NAV` | Small NAV can make percentage returns unstable. |
| `NEGATIVE_NAV` | Negative NAV requires special interpretation or policy block. |
| `STALE_VALUATION` | Result uses a valuation older than preferred freshness. |
| `RESULT_SUPERSEDED` | A newer calculation replaced the previous result. |

## 7. Support answer templates

### General result

```text
The money-weighted return for {period} is {mwrr}. It was calculated using {method} on {basis} basis in {currency}. This return includes the timing and size of external cash flows. The largest flows were {top_flows}. The displayed value is {annualized_or_holding_period}; the alternate value is {alternate_return}.
```

### Difference from TWRR

```text
The time-weighted return was {twrr}, while the money-weighted return was {mwrr}. They differ because MWRR gives more influence to periods when more capital was invested. In this case, {flow_summary} occurred around {performance_summary}, which explains the difference.
```

### Not calculable

```text
The money-weighted return could not be calculated for {period}. The status is {status} with reason {reason_code}. The blocking item is {blocking_detail}. No return has been inferred because doing so could be misleading.
```

### Fallback used

```text
The primary XIRR calculation was not available because {fallback_reason}. The displayed value uses {fallback_method}, which is an approximation and is labeled separately.
```

### Short-period annualized value

```text
The displayed value is annualized over a {days}-day period. The holding-period return is {holding_period_return}. Annualization can make short-period gains or losses look much larger than the period result.
```

## 8. Agent guardrails

A support agent should not:

- claim MWRR is wrong solely because it differs from TWRR,
- claim component MWRRs add to total MWRR,
- hide fallback usage,
- ignore annualization,
- ignore gross/net basis,
- ignore reporting currency,
- invent missing data reasons,
- compare against benchmarks without checking benchmark return type,
- provide tax, legal, or compliance conclusions beyond approved methodology text.

A support agent should:

- state method, basis, period, currency, and annualization,
- show major flows,
- reference calculation evidence internally,
- use reason codes,
- explain cash-flow timing effects,
- escalate unresolved data or methodology cases.

## 9. Observability metrics

Track:

| Metric | Why |
|---|---|
| Calculation count by status | Availability and health. |
| Not-calculable count by reason | Data quality bottlenecks. |
| Solver non-convergence count | Numerical problems. |
| Multiple-root count | Ambiguous cash-flow patterns. |
| Fallback usage count | Ensure fallback is controlled. |
| Extreme MWRR count | Detect near-zero NAV or annualization issues. |
| Missing transfer valuation count | Improve in-kind transfer pipeline. |
| Missing FX count | Improve FX coverage. |
| Stale valuation count | Improve valuation freshness. |
| Superseded result count | Monitor late/corrected data volume. |

Suggested dimensions:

- scope type,
- period type,
- basis,
- reporting currency,
- booking center,
- custodian,
- asset class,
- source system,
- methodology version.

## 10. Alerting ideas

Alert when:

- not-calculable rate spikes,
- missing FX spikes,
- missing transfer valuations spike,
- fallback usage spikes,
- extreme annualized return count spikes,
- solver failures spike,
- stale valuations exceed threshold,
- restatements spike after upstream deployment.

Do not alert on every negative MWRR. Negative MWRR can be legitimate.

## 11. Incident examples

### Incident: Many MWRRs became blank after deployment

Likely causes:

- sign convention changed,
- solver precondition broken,
- ending valuation not loaded,
- FX source unavailable,
- solver bounds too narrow,
- date parsing bug,
- classification rules excluding all flows.

Immediate checks:

1. compare normalized flow vectors before and after,
2. inspect reason-code distribution,
3. run golden fixtures in deployed environment,
4. check methodology feature flags.

### Incident: MWRRs changed overnight

Likely causes:

- backfilled transactions,
- valuation restatement,
- FX correction,
- transfer valuation update,
- fee/tax classification update,
- internal transfer matching update,
- methodology version change.

Immediate checks:

1. compare calculation evidence,
2. identify changed flows and valuations,
3. check upstream data releases,
4. decide whether report restatement is needed.

### Incident: Client challenges negative MWRR

Likely causes:

- large deposit before market decline,
- comparison to TWRR,
- annualized versus holding-period confusion,
- net/gross mismatch,
- reporting-currency FX impact.

Immediate checks:

1. show cash-flow timeline,
2. show TWRR path,
3. show MWRR cash-flow vector,
4. show annualized and holding-period values.

## 12. Escalation matrix

| Issue | First owner | Escalate to |
|---|---|---|
| Missing valuation | Data/Ops | Valuation data owner |
| Missing FX | Data/Ops | FX data owner |
| Missing transfer valuation | Ops | Custody/security master owner |
| Internal transfer mismatch | BA/Data | Transaction classification owner |
| Multiple roots | Quant/dev | Methodology owner |
| Solver non-convergence | Dev/quant | Platform owner |
| Fee treatment dispute | BA/Product | Methodology/compliance owner |
| Tax treatment dispute | BA/Product | Tax methodology owner |
| Client-facing disclosure issue | Product/BA | Compliance/legal owner |
| Result changed after correction | Ops | Data owner and client reporting owner |

## 13. Ticket closure checklist

Before closing a ticket:

- [ ] Confirm period, scope, basis, currency.
- [ ] Confirm method and annualization flag.
- [ ] Review BMV and EMV.
- [ ] Review top external flows.
- [ ] Check excluded internal flows if group scope.
- [ ] Check FX warnings.
- [ ] Check transfer valuation warnings.
- [ ] Check solver status and fallback.
- [ ] Compare to TWRR only with explanation.
- [ ] Attach evidence summary.
- [ ] Record whether issue was data, methodology, system, or user interpretation.
