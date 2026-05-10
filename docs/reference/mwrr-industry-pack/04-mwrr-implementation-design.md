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
