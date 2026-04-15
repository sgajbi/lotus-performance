# MWR Endpoint Certification

Status: in progress for `POST /performance/mwr`

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
- `mwr_method="DIETZ"` returns the period Dietz return.
- `mwr_method="MODIFIED_DIETZ"` currently follows the implemented Dietz path.
- `emit_cashflows_used=true` returns the exact signed cash-flow schedule used by the calculation.

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

## Downstream Consumers

- `lotus-gateway` calls `/performance/mwr` through `LotusAnalyticsClient.get_mwr_analytics` and
  uses it in the Workbench performance workspace summary/details flow.
- `lotus-risk` does not call `/performance/mwr`; risk surfaces consume
  `POST /integration/returns/series` for performance return series.

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
- `MODIFIED_DIETZ`: same implemented Dietz path, about `-0.93%`

Gateway Workbench performance summary now returns the same YTD XIRR MWR value, rounded to
`-3.613903%`, and preserves operational fees as performance drag rather than investor cash
movement.

## Certification Result

MWR is certified for the canonical YTD UI integration path with a governed source-quality caveat:
the current lotus-core source still contains large cross-observation capital-base breaks, so
`cashflows_used` must remain visible for supportability and the TWR inspector should be used when
front office needs to explain the source economics. The endpoint contract and normalization are now
aligned with the PB/quant MWR capital-timing lens, and focused tests cover the critical
normalization behavior.

## Validation Commands

```bash
python -m pytest tests/unit/app/test_mwr_openapi_contract.py tests/unit/docs/test_public_docs_contract.py tests/unit/services/test_mwr_mode_service.py tests/unit/services/test_workspace_summary_service.py tests/integration/test_mwr_api.py -q
python -m ruff check app/api/endpoints/performance.py app/services/stateful_mwr_input_service.py app/services/workspace_summary_service.py tests/unit/app/test_mwr_openapi_contract.py tests/unit/docs/test_public_docs_contract.py tests/unit/services/test_mwr_mode_service.py tests/unit/services/test_workspace_summary_service.py tests/integration/test_mwr_api.py
python -m ruff format --check app/api/endpoints/performance.py app/services/stateful_mwr_input_service.py app/services/workspace_summary_service.py tests/unit/app/test_mwr_openapi_contract.py tests/unit/docs/test_public_docs_contract.py tests/unit/services/test_mwr_mode_service.py tests/unit/services/test_workspace_summary_service.py tests/integration/test_mwr_api.py
```
