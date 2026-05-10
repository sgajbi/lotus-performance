# RFC 016: MWR Enhancements (XIRR + Modified Dietz)

**Status:** Implemented
**Owner:** lotus-performance
**Reviewers:** Perf Engine, Platform, Gateway Consumers
**Current implementation:** `POST /performance/mwr`
**Related:** RFC-014, RFC-020, RFC-025, RFC-044

## Executive Summary

RFC-016 upgraded Lotus money-weighted return from a simple Dietz-only calculation into a
supportable investor capital-timing analytics contract.

The current implementation provides:

1. XIRR as the primary dated cash-flow method;
2. Modified Dietz as a distinct dated-weight fallback and direct method;
3. Simple Dietz as the explicit midpoint Dietz method;
4. annualized and holding-period return separation;
5. solver convergence diagnostics;
6. machine-readable supportability posture through `status`, `reason_codes`, `warnings`,
   `fallback_from`, `fallback_reason`, and `is_approximation`;
7. cash-flow schedule echoing through `cashflows_used` when requested;
8. bounded operational telemetry for MWR solver outcomes.

The current contract is implementation-backed in code, tests, OpenAPI, public guides,
methodology documents, response certification, and repo-local wiki material.

## Original Requirement Intent

The original RFC asked lotus-performance to move `/performance/mwr` beyond a minimal periodic
Dietz calculation by adding:

1. a dated XIRR calculation path for irregular investor cash flows;
2. Modified Dietz fallback behavior when XIRR could not produce a usable result;
3. Simple Dietz compatibility;
4. annualization controls;
5. convergence diagnostics;
6. richer response evidence for support and downstream consumers;
7. unit and integration tests for solver behavior, fallback behavior, and annualization math.

That intent remains valid, but the implemented contract has evolved to use Lotus field names and
supportability language rather than the early proposal's placeholder response names.

## Current Implementation

### API Contract

`POST /performance/mwr` accepts both stateless and stateful input modes.

Stateless callers provide a single reporting-currency schedule through either legacy top-level
fields or the current `stateless_input` envelope:

- `begin_mv`
- `end_mv`
- `cash_flows[].amount`
- `cash_flows[].date`
- `start_date`
- `as_of`

Stateful callers provide:

- `input_mode="stateful"`
- `portfolio_id`
- `as_of`
- `stateful_input.window_start_date`

lotus-performance then sources governed portfolio observations from lotus-core query-control-plane,
normalizes them into canonical MWR inputs, and stamps source consumer identity server-side.

### Method Semantics

| Requested method | Implemented behavior |
| --- | --- |
| `XIRR` | Builds a dated solver vector from beginning market value, signed cash flows, and ending market value. Same-day solver flows are netted deterministically. The solver scans the configured log-rate interval and returns XIRR only when exactly one root is detected. |
| `MODIFIED_DIETZ` | Computes dated weighted capital using each cash flow's time remaining in the measurement window. This is a distinct path from Simple Dietz. |
| `DIETZ` | Computes midpoint Dietz using half of net cash flow in the denominator. |

XIRR success returns `method="XIRR"`, `status="CALCULATED"`, `is_annualized_primary=true`, and
`is_approximation=false`.

XIRR failure states such as no economic content, missing positive/negative solver flow, no root,
multiple roots, and invalid solver bounds are not silently converted into arbitrary IRR values.
Fallback responses are labeled with `status="FALLBACK_USED"`, include the solver `reason_codes`,
set `fallback_from="XIRR"`, and return Modified Dietz as the calculation method.

### Response Contract

The implementation emits the current Lotus response shape:

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
- `cashflows_used`
- `calculation_supportability`
- `meta`
- `diagnostics`
- `audit`

`money_weighted_return` is in percentage-point output units. For successful XIRR it is the
annualized IRR; `holding_period_return` gives the measured-period equivalent. For Dietz-family
outputs, `money_weighted_return` and `holding_period_return` are period returns unless
`mwr_annualized` is separately produced.

### Operational Telemetry

`lotus_performance_mwr_solver_outcome_total{input_mode,method,status,reason_code,fallback_used}`
tracks bounded solver outcomes without promoting portfolio identifiers, trace identifiers, request
payload values, or other high-cardinality data into labels.

## Requirement-To-Implementation Traceability

| Requirement | Current evidence | Status |
| --- | --- | --- |
| XIRR dated cash-flow method | `engine/mwr.py`, `tests/unit/engine/test_mwr.py`, `tests/integration/test_mwr_api.py` | Implemented |
| Modified Dietz distinct from Simple Dietz | `engine/mwr.py`, `test_calculate_mwr_modified_dietz_weights_cash_flows_by_time_remaining` | Implemented |
| XIRR fallback to Modified Dietz | `test_calculate_mwr_xirr_fallback_to_dietz`, `test_calculate_mwr_xirr_multiple_root_fallback_is_labeled` | Implemented |
| Simple Dietz compatibility | `test_calculate_mwr_dietz` | Implemented |
| Annualization and period-return separation | `holding_period_return`, `mwr_annualized`, `is_annualized_primary`; `test_calculate_mwr_xirr_short_period_exposes_holding_period_return` | Implemented |
| Convergence diagnostics | `Convergence` model and integration assertions on `root_count_detected`, `residual_npv`, and `day_count_basis` | Implemented |
| Support-facing fallback diagnostics | `status`, `reason_codes`, `warnings`, `fallback_from`, `fallback_reason`, `is_approximation`; response attribute certification | Implemented |
| Cash-flow schedule evidence | `cashflows_used` with `emit_cashflows_used` control; `test_mwr_emit_cashflows_used_false_omits_cashflow_echo` | Implemented |
| OpenAPI and public docs | `tests/unit/app/test_mwr_openapi_contract.py`, `docs/guides/mwr.md`, `docs/technical/mwr-endpoint-certification.md` | Implemented |

## Deviations From The Original Proposal

The original proposal mentioned adding `scipy` for numerical solving. The implemented solver does
not depend on SciPy. It uses a deterministic log-rate bracket scan and bisection refinement in
`engine/mwr.py`, which keeps the runtime dependency surface smaller while preserving explicit
convergence evidence.

The original response examples used placeholder names such as `mwr` and `mwr_annualized`. The
current public contract uses Lotus response names such as `money_weighted_return`,
`holding_period_return`, `calculation_supportability`, and the shared response envelopes.

## Current Boundaries

RFC-016 is complete for the single reporting-currency MWR contract.

FX-aware per-flow MWR conversion is not part of RFC-016 closure. It remains governed by RFC-020 and
the dedicated readiness design in `docs/technical/mwr-fx-contract-design.md`. Current MWR inputs
must already be expressed in one consistent reporting currency.

## Validation

Primary validation:

```bash
python -m pytest tests/unit/engine/test_mwr.py tests/integration/test_mwr_api.py tests/integration/test_response_attribute_certification.py tests/unit/app/test_mwr_openapi_contract.py -q
```

Documentation guardrails:

```bash
python -m pytest tests/unit/docs/test_public_docs_contract.py tests/unit/docs/test_metric_methodology_docs.py -q
```

Full repository gate:

```bash
make check
```
