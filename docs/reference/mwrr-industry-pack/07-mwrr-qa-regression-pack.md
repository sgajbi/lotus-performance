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
