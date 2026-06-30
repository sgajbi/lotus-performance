# MWR Endpoint Certification

Status: certified for `POST /performance/mwr`

Canonical live portfolio: `PB_SG_GLOBAL_BAL_001`

Governed as-of date: `2026-04-10`

## Endpoint Purpose

`POST /performance/mwr` calculates money-weighted return for the investor capital-timing lens.
Use it when the business question is how the portfolio performed for the client after the size and
timing of deposits, withdrawals, fees, and other served capital movements are considered.

Do not use MWR as a substitute for manager skill or strategy performance. Use `POST /performance/twr`
for that TWR lens.

## Supported Modes And Options

- `input_mode="stateless"` accepts caller-owned `stateless_input.begin_mv`,
  `stateless_input.end_mv`, and `stateless_input.cash_flows`.
- legacy top-level `begin_mv`, `end_mv`, and `cash_flows` are still accepted for stateless
  compatibility, but new integrations should use `stateless_input`.
- `input_mode="stateful"` accepts `stateful_input.window_start_date` and sources the portfolio
  timeseries from lotus-core query-control-plane.
- `mwr_method="XIRR"` solves annual IRR across irregular cash-flow dates.
- `mwr_method="MODIFIED_DIETZ"` returns the period Modified Dietz return using dated cash-flow
  weights.
- `mwr_method="DIETZ"` returns the period midpoint Dietz return.
- cash-flow dates must fit the resolved measurement window; invalid stateless or stateful schedules
  fail with `error_code="MWR_CASH_FLOW_OUT_OF_WINDOW"` before Modified Dietz weights or XIRR
  solver vectors are built.
- Dietz-family annualization honors `annualization.periods_per_year` first, then `BUS/252`,
  `ACT/365`, and `ACT/ACT`.
- `emit_cashflows_used=true` returns the exact signed cash-flow schedule used by the calculation.
- `source_preconverted_fx_evidence` is optional for stateless requests whose inputs were converted
  upstream; when supplied, the endpoint validates complete per-input FX provenance and returns it
  in `currency_evidence` without performing in-engine FX conversion.
- `solver` controls searched annual-rate bounds, root scan density, tolerance, and maximum
  bisection iterations.

The XIRR implementation nets same-day solver flows after sign normalization, scans the configured
log-rate interval for all sign-changing roots, and returns XIRR only when exactly one root exists.
No-root and multiple-root cases are not silently interpreted as a valid annual IRR; they are labeled
through `status`, `reason_codes`, `fallback_from`, and `fallback_reason`.

Stateless source-preconverted FX evidence fails closed when the evidence does not align with the
reporting-currency MWR inputs. This protects downstream consumers from accepting a mixed-currency
story that cannot be reproduced from the submitted market values, cash flows, rate metadata, policy,
timestamp, and conversion fingerprint.

## Upstream Integration

Stateful MWR reads:

- `POST /integration/portfolios/{portfolio_id}/analytics/portfolio-timeseries`

The base URL must be `CORE_CONTROL_PLANE_BASE_URL`, not the lotus-core query-service read plane.

Stateful MWR normalization uses:

- first valid observation beginning market value as `begin_mv`;
- last valid observation ending market value as `end_mv`;
- explicit external source cash-flow rows;
- cross-observation capital carry-forward adjustments where a valid observation beginning market
  value differs from the prior valid observation ending market value.

The carry-forward adjustment is necessary for MWR because a capital-base jump between observations
is capital timing, not portfolio investment performance. Operational fees remain performance drag
and are not treated as investor deposits or withdrawals. The source-quality inspector remains the
support tool for deciding whether a carry-forward adjustment represents expected source behavior or
an upstream data-quality issue.

Stateful MWR response evidence now distinguishes:

- observed upstream source cash-flow rows,
- rows included in the investor cash-flow schedule,
- rows excluded as fee/operational, internal, unsupported or income-like, invalid, or missing
  required values,
- source transaction/event lifecycle identity when supplied by lotus-core.

When source lifecycle identity is absent, components explicitly report
`lifecycle_identity_status="not_supplied_by_source"` so downstream support tools do not invent
transaction lineage.

## Downstream Consumers

- `lotus-gateway` calls `/performance/mwr` through `LotusAnalyticsClient.get_mwr_analytics` and
  uses it in the Workbench performance workspace summary/details flow.
- `lotus-risk` does not call `/performance/mwr`; risk surfaces consume
  `POST /integration/returns/series` for performance return series.

Downstream certification status:

- `lotus-gateway` uses the stateful MWR endpoint for the investor capital-timing lens and maps the
  returned MWR value, annualized value, method, period dates, economic context, status,
  reason-code, warning, holding-period, annualized-primary, fallback, and approximation metadata
  into Workbench performance contracts.
- Gateway does not currently request `emit_cashflows_used=true` for normal Workbench surfaces. That
  is acceptable for front-office summary use, because the cash-flow schedule is support evidence,
  not a required summary display field.
- No direct open gateway issue was found for MWR endpoint misuse during this pass.

## Supportability and Observability

Completed MWR responses now include `calculation_supportability` with bounded `state`, `reason`,
and `freshness_bucket` values plus input-row and resolved-period counts. The service also increments:

`lotus_performance_calculation_supportability_total{operation="mwr",supportability_state,reason,freshness_bucket}`

MWR-specific solver outcomes are also counted for operational trend analysis:

`lotus_performance_mwr_solver_outcome_total{input_mode,method,status,reason_code,fallback_used}`

Use this block as the source-owned freshness and degraded-state signal for front-office MWR panels.
The response publishes `calculation_supportability.metric_labels` with the same bounded label keys
used by the metric. The metric labels must not include portfolio, tenant, account, benchmark,
calculation, trace, correlation, request body, response body, or security identifiers.
The solver-outcome metric follows the same support-safety rule: label values are bounded to input
mode, calculation method, outcome status, reason code, and fallback flag.

Operational alert and dashboard templates for fallback, no-root, multiple-root, and stateful
source-data rejection rates are governed in `docs/operations/mwr-alert-rule-templates.md`.

Calculation-quality metadata is part of the product contract:

- `status="CALCULATED"` means the emitted method completed without fallback.
- `status="FALLBACK_USED"` means XIRR was attempted but Modified Dietz was returned with explicit
  `fallback_reason`.
- `status="NOT_CALCULABLE"` means the engine could not produce a meaningful return, for example
  `ZERO_DENOMINATOR`.
- `status="NOT_APPLICABLE"` means no economic content was present.
- `holding_period_return` distinguishes measured-period outcome from annualized XIRR.
- `convergence` carries root count, residual NPV, searched bounds, day-count basis, anchor date,
  normalized solver-flow count, and gross cash-flow scale.

## GitHub Issue Disposition

Open issue search for MWR currently finds only broad stateful-sourcing issue `#83`. That issue
remains open because it covers wider RFC-0082 architecture work. No direct open MWR-output defect
was found during this pass.

## Live Canonical Evidence

Artifacts are under:

`artifacts/mwr-api-certification-2026-04-10/`

Initial live runtime before the normalization fix returned source-economically invalid stateful
MWR for YTD:

- `XIRR`: about `450.57%`
- `DIETZ`: about `58.92%`

The root cause was a large cross-observation capital-base break in lotus-core portfolio timeseries,
for example `2026-02-28` beginning market value exceeded the prior observation ending market value
by about `471,091.70` while no explicit cash-flow row was served. TWR is less sensitive to this
because it calculates each served day from that day's own beginning and ending values; MWR requires a
period capital-flow schedule.

After normalization hardening and API rebuild, validation against the live query-control-plane
source produced domain-plausible YTD stateful MWR:

- `XIRR`: about `-3.61%` annual IRR
- `DIETZ`: about `-0.93%` period return
- `MODIFIED_DIETZ`: weighted cash-flow period return from dated capital movements

Gateway Workbench performance summary returns the same YTD XIRR MWR value, rounded to
`-3.613903%`. Workspace economic-context fields remain explicit source economics:
`beginning_cash_flow`, `ending_cash_flow`, and `net_cash_flow` do not include carry-forward capital
adjustments, while the MWR calculation cash-flow schedule does include those adjustments.

## Certification Result

MWR is certified for the canonical YTD UI integration path with a governed source-quality caveat:
the current lotus-core source still contains large cross-observation capital-base breaks, so
`cashflows_used` must remain visible for supportability and the TWR inspector should be used when
front office needs to explain the source economics. The endpoint contract and normalization are now
aligned with the PB/quant MWR capital-timing lens, and focused tests cover the critical
normalization behavior.

Response attribute-level certification is covered in
`docs/technical/twr-mwr-response-attribute-certification.md` and
`tests/integration/test_response_attribute_certification.py`. That pass checks emitted MWR response
fields, cash-flow echo behavior, metadata, diagnostics, audit counts, optional-field omission, and
independently recomputed Dietz math.

## Validation Commands

```bash
python -m pytest tests/unit/app/test_mwr_openapi_contract.py tests/unit/docs/test_public_docs_contract.py tests/unit/services/test_mwr_mode_service.py tests/unit/services/test_workspace_summary_service.py tests/integration/test_mwr_api.py -q
python -m ruff check app/api/endpoints/performance.py app/services/mwr_cash_flow_window_validation.py app/services/stateful_mwr_input_service.py app/services/mwr_mode_service.py app/services/mwr_calculation_service.py engine/mwr.py tests/unit/app/test_mwr_openapi_contract.py tests/unit/docs/test_public_docs_contract.py tests/unit/services/test_mwr_mode_service.py tests/unit/services/test_mwr_calculation_service.py tests/integration/test_mwr_api.py
python -m ruff format --check app/api/endpoints/performance.py app/services/mwr_cash_flow_window_validation.py app/services/stateful_mwr_input_service.py app/services/mwr_mode_service.py app/services/mwr_calculation_service.py engine/mwr.py tests/unit/app/test_mwr_openapi_contract.py tests/unit/docs/test_public_docs_contract.py tests/unit/services/test_mwr_mode_service.py tests/unit/services/test_mwr_calculation_service.py tests/integration/test_mwr_api.py
```
