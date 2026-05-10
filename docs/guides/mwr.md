# Money-Weighted Return Guide

`POST /performance/mwr` calculates investor-experience return using cash-flow-aware money-weighted
return methods.

## Current request contract

The current request shape is:

- `input_mode: "stateless" | "stateful"`
- `portfolio_id`
- `as_of`
- `mwr_method`

Stateless callers can use either:

- legacy top-level `begin_mv`, `end_mv`, and `cash_flows`
- or `stateless_input.begin_mv`, `stateless_input.end_mv`, and `stateless_input.cash_flows`

Stateful callers use:

- `stateful_input.window_start_date`

The stateful envelope is intentionally lightweight. lotus-performance stamps the
source consumer identity server-side instead of requiring an explicit consumer field.

In stateful mode, lotus-performance sources portfolio timeseries from lotus-core query-control-plane
and normalizes them into canonical MWR inputs:

- `begin_mv`
- `end_mv`
- `cash_flows`
- authoritative `start_date`

Stateful normalization includes explicit external source cash flows and cross-observation capital
carry-forward adjustments where a valid observation's beginning market value does not equal the
prior valid observation's ending market value. Operational fees remain performance drag; they are
not treated as investor deposits or withdrawals in the MWR cash-flow schedule. This is necessary
because MWR is a capital-timing measure: a large unexplained capital-base jump must be treated as
dated client capital movement for the period calculation rather than as investment performance. The
TWR inspector remains the support tool for diagnosing whether those adjustments are expected source
behavior or upstream data-quality issues.

Optional controls include:

- `start_date`
- `annualization`
- `solver`
- `report_ccy`
- standard envelope fields such as `precision_mode`

## Implemented method behavior

The current engine behavior is:

- `mwr_method="XIRR"` attempts an XIRR solve first
- the XIRR path nets same-day solver flows, scans the configured log-rate interval, and returns
  XIRR only when exactly one root is detected
- if the XIRR path has no economic content, no positive and negative solver flows, no root,
  multiple roots, or invalid solver bounds, the response is explicitly labeled rather than silently
  selecting an arbitrary rate
- `mwr_method="DIETZ"` uses the Dietz computation path directly
- `mwr_method="MODIFIED_DIETZ"` currently maps to the same implemented Dietz computation path as
  `DIETZ`

That last point is an implementation reality, not a theory. It is also tracked in the metric
methodology index and RFC backlog.

## Core methodology

### XIRR path

When `mwr_method="XIRR"`, the engine solves for the discount rate that makes the net present value
of:

- negative beginning market value
- all signed cash flows
- positive ending market value

equal to zero across irregular cash-flow dates.

The successful XIRR value is annualized. The response also includes `holding_period_return` so
front-office and support users can distinguish the measured-period client outcome from the
annualized IRR.

### Dietz path

When the engine uses the Dietz path, it computes a period return from:

- beginning market value
- ending market value
- net cash flow over the period
- a midpoint-style denominator adjustment

If the denominator is zero, the engine returns `0.0` and records the condition in `notes`.
It also returns `status="NOT_CALCULABLE"` with `reason_codes=["ZERO_DENOMINATOR"]`, so downstream
consumers do not treat the value as an ordinary calculated zero return.

### Annualization

If annualization is enabled, the Dietz result is annualized from the measured period length using
the requested annualization basis.

## Current response shape

The response contains:

- `calculation_id`
- `portfolio_id`
- `input_mode`
- `money_weighted_return`
- `mwr_annualized`
- `method`
- `status`
- `reason_codes`
- `warnings`
- `holding_period_return`
- `is_annualized_primary`
- `fallback_from`
- `fallback_reason`
- `is_approximation`
- `convergence`
- `start_date`
- `end_date`
- `notes`
- `meta`
- `diagnostics`
- `audit`

When `emit_cashflows_used=true`, which is the default, the response also includes `cashflows_used`
so support, front office, and downstream clients can see the exact signed flow schedule used by the
calculation.

## Multi-currency note

MWR is not decomposed into local and FX components on the current public contract. Callers should
submit `begin_mv`, `end_mv`, and `cash_flows` in one consistent reporting currency.

## Example request

```json
{
  "input_mode": "stateless",
  "portfolio_id": "MWR_EXAMPLE_01",
  "as_of": "2025-12-31",
  "stateless_input": {
    "begin_mv": 100000.0,
    "end_mv": 115000.0,
    "cash_flows": [
      { "amount": 10000.0, "date": "2025-03-15" },
      { "amount": -5000.0, "date": "2025-09-20" }
    ]
  },
  "mwr_method": "XIRR",
  "annualization": { "enabled": true, "basis": "ACT/ACT" }
}
```

## Example response excerpt

```json
{
  "calculation_id": "2f4f3e0e-6e0e-4e0e-8e0e-2f4f3e0e6e0e",
  "portfolio_id": "MWR_EXAMPLE_01",
  "input_mode": "stateless",
  "money_weighted_return": 11.7149255445268,
  "mwr_annualized": 11.7149255445268,
  "method": "XIRR",
  "status": "CALCULATED",
  "reason_codes": [],
  "warnings": [],
  "holding_period_return": 9.23382685403924,
  "is_annualized_primary": true,
  "is_approximation": false,
  "convergence": {
    "iterations": 26,
    "converged": true,
    "algorithm": "log_rate_bracket_scan_bisection",
    "root_count_detected": 1,
    "residual_npv": 0.000009008654160425067,
    "rate_lower_bound": -0.999999999,
    "rate_upper_bound": 1000.0,
    "day_count_basis": "ACT/365",
    "anchor_date": "2025-03-15",
    "normalized_flow_count": 3,
    "gross_cash_flow_scale": 230000.0
  },
  "cashflows_used": [
    { "amount": 10000.0, "date": "2025-03-15" },
    { "amount": -5000.0, "date": "2025-09-20" }
  ],
  "start_date": "2025-03-15",
  "end_date": "2025-12-31",
  "notes": ["XIRR calculation successful."],
  "meta": {},
  "diagnostics": {},
  "audit": { "counts": { "cashflows": 2 } }
}
```

Older examples using only top-level `begin_mv`, `end_mv`, and `cash_flows` are still accepted for
stateless compatibility, but the Lotus-style mode envelope is the current contract for new
integrations.

Use `/docs` for the exact response schema and latest examples.

## Lotus Production Controls

The reviewed MWRR industry material has been converted into Lotus-authored, implementation-backed
documentation rather than retained as generic reference text:

- [Lotus MWR production controls](mwr-lotus-production-controls.md) explains the supported
  business flow, solver behavior, response controls, data mesh boundaries, and validation posture.
- [MWR production support playbook](../operations/mwr-production-support-playbook.md) gives
  operations, support, and front-office teams a reason-code triage flow and client-safe explanation
  language.
- [MWR industry review findings](../technical/mwr-industry-review-findings.md) records what was
  adopted, what Lotus already handled more strongly, and which candidate enhancements remain outside
  the current implementation-backed contract.

Operational trend visibility is exposed through
`lotus_performance_mwr_solver_outcome_total{input_mode,method,status,reason_code,fallback_used}` for
fallback, no-root, and multiple-root rate monitoring.
Alert and dashboard templates for this signal live in
`docs/operations/mwr-alert-rule-templates.md`.
