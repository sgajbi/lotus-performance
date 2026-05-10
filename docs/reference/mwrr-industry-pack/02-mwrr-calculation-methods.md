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
