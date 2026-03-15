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

- `stateful_input.consumer_system`
- `stateful_input.window_start_date`

In stateful mode, lotus-performance sources portfolio timeseries from lotus-core query-control-plane
and normalizes them into canonical MWR inputs:

- `begin_mv`
- `end_mv`
- `cash_flows`
- authoritative `start_date`

Optional controls include:

- `start_date`
- `annualization`
- `solver`
- `report_ccy`
- standard envelope fields such as `precision_mode`

## Implemented method behavior

The current engine behavior is:

- `mwr_method="XIRR"` attempts an XIRR solve first
- if the XIRR solve does not converge or the cash-flow pattern has no sign change, the engine falls
  back to the Dietz computation path
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

### Dietz path

When the engine uses the Dietz path, it computes a period return from:

- beginning market value
- ending market value
- net cash flow over the period
- a midpoint-style denominator adjustment

If the denominator is zero, the engine returns `0.0` and records the condition in `notes`.

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
- `convergence`
- `start_date`
- `end_date`
- `notes`
- `meta`
- `diagnostics`
- `audit`

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
  "money_weighted_return": 11.723,
  "mwr_annualized": 11.723,
  "method": "XIRR",
  "convergence": { "converged": true },
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
