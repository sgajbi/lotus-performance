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
