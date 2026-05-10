# Money-Weighted Rate of Return Documentation Pack

**Status:** Draft industry-methodology starter pack  
**Audience:** Business, BA, QA, developers, quant/dev, operations, production support, future support agents  
**Last updated:** 2026-05-08

## Purpose

This documentation pack explains Money-Weighted Rate of Return, usually abbreviated as **MWRR**, from an industry-practice and implementation perspective.

It is designed to be used as a starter reference for:

- business explanation,
- business analysis,
- requirements refinement,
- implementation design,
- edge-case handling,
- QA and regression testing,
- operational support,
- future production-support agents.

The pack is intentionally platform-neutral. Product teams can align terminology, API names, field names, methodology versions, storage models, and evidence contracts to their own systems.

## Executive summary

MWRR measures the return earned by the actual money invested in a portfolio, fund, mandate, sleeve, or account. It reflects the timing and size of external cash flows such as deposits, withdrawals, capital calls, distributions, and in-kind transfers.

The standard implementation form is an **IRR/XIRR-style calculation** over dated cash flows:

```text
NPV(r) = sum(CF_i / (1 + r) ^ tau_i) = 0
```

MWRR is powerful, but it is sensitive to data quality and methodology choices. The hardest production problems are usually not mathematical. They are usually caused by:

- wrong cash-flow classification,
- wrong scope treatment,
- missing or stale valuations,
- missing FX rates,
- inconsistent fee and tax treatment,
- annualized versus holding-period confusion,
- solver ambiguity,
- late or corrected transaction data.

## Core principles

1. **MWRR is cash-flow-aware.** Large flows matter more than small flows, and flows invested for longer matter more than flows invested briefly.
2. **MWRR is not TWRR.** Time-weighted return measures the strategy path; money-weighted return measures the investor experience.
3. **MWRR is not additive.** Component MWRRs do not sum to total portfolio MWRR.
4. **Classification is methodology.** The same transaction can be external at one scope and internal at another.
5. **Evidence is mandatory.** A production result should be reproducible from a persisted cash-flow vector, valuation snapshots, FX rates, and solver diagnostics.
6. **Fallbacks must be labeled.** Modified Dietz or other approximations must not be silently presented as XIRR/MWRR.
7. **Annualization must be explicit.** Short-period annualized MWRR can be surprising and must be clearly labeled.
8. **Invalid is better than misleading.** If inputs or math do not support a reliable result, return a clear status and reason code.

## Documentation map

| File | Purpose |
|---|---|
| `01-mwrr-methodology.md` | Business and methodology explanation of MWRR, TWRR differences, formulas, examples, usage, limitations, and reporting interpretation. |
| `02-mwrr-calculation-methods.md` | Detailed formulas for XIRR-style MWRR, holding-period conversion, Modified Dietz, annualization, and worked calculations. |
| `03-mwrr-cash-flow-classification.md` | Industry-style classification rules for deposits, withdrawals, transfers, trades, income, fees, taxes, corporate actions, private markets, and group scopes. |
| `04-mwrr-implementation-design.md` | Data model, normalized cash-flow ledger, output contract, algorithm, evidence design, status model, caching, idempotence, and pseudocode. |
| `05-mwrr-solver-and-numerical-controls.md` | Solver domain, bracketing, log-rate transformation, multiple-root detection, no-root handling, tolerances, and numerical safeguards. |
| `06-mwrr-edge-cases-and-controls.md` | Edge-case policy guide for zero NAV, negative NAV, missing data, stale valuations, flow corrections, closed accounts, private assets, and component MWRR. |
| `07-mwrr-qa-regression-pack.md` | QA test cases, expected values, property tests, integration tests, regression checklist, and defect taxonomy. |
| `08-mwrr-production-support-agent-playbook.md` | Production support triage, user explanation templates, reason-code guide, observability metrics, alerts, escalation matrix, and agent guardrails. |
| `mwrr-industry-playbook-all-in-one.md` | Single combined document for agents or tools that prefer one markdown file. |

## Recommended production minimum

A production MWRR capability should provide:

- method: `XIRR`, `IRR`, `MODIFIED_DIETZ`, or another explicit method,
- basis: `GROSS`, `NET`, `BEFORE_TAX`, `AFTER_TAX`, or business-defined equivalent,
- annualization flag and policy,
- reporting currency,
- period start and end dates,
- beginning and ending market values,
- included external cash flows,
- excluded candidate events with reasons where feasible,
- day-count basis,
- sign convention,
- flow timing convention,
- solver status,
- root count or ambiguity indicator,
- fallback indicator where applicable,
- warnings and reason codes,
- calculation evidence or evidence reference.

## Recommended implementation backlog themes

1. Build a normalized external cash-flow ledger.
2. Implement scope-aware cash-flow classification.
3. Store synthetic beginning and ending flows as evidence.
4. Implement robust XIRR root detection, not single-guess Newton only.
5. Detect multiple roots and no-root patterns.
6. Implement Modified Dietz as an explicit method or labeled fallback.
7. Add annualized and holding-period values with clear labeling.
8. Add gross/net/fee/tax methodology policy versions.
9. Implement transfer valuation and FX evidence.
10. Add QA golden files and property tests.
11. Add production reason codes, warnings, and support templates.
12. Add observability metrics for failed, ambiguous, fallback, extreme, and restated calculations.

## Important terminology

| Term | Meaning |
|---|---|
| MWRR | Money-Weighted Rate of Return. Return that reflects timing and size of external cash flows. |
| IRR | Internal Rate of Return. Rate that makes discounted cash flows sum to zero. |
| XIRR | IRR calculated using actual dates for non-periodic cash flows. |
| TWRR | Time-Weighted Rate of Return. Return that neutralizes external cash-flow timing. |
| External cash flow | Value entering or leaving the measurement scope from outside. |
| Synthetic cash flow | Beginning or ending market value inserted into the solver cash-flow vector. |
| Holding-period return | Return over the exact measurement period. |
| Annualized return | Return converted to a one-year rate. |
| Modified Dietz | Approximate money-weighted method using weighted cash flows. |
| Measurement scope | Boundary of the calculation, such as portfolio, group, account, mandate, fund, sleeve, or component. |
