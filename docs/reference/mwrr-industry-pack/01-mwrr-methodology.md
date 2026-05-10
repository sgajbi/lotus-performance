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
