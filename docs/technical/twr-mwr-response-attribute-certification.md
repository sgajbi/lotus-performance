# TWR And MWR Response Attribute Certification

Status: certified for deterministic stateless response attributes and canonical stateful runtime
sanity evidence.

Related endpoints:

- `POST /performance/twr`
- `GET /performance/twr/results/{calculation_id}`
- `POST /performance/mwr`

Canonical portfolio used for live runtime probes: `PB_SG_GLOBAL_BAL_001`

Governed as-of date: `2026-04-10`

## Certification Standard

This certification checks the full emitted response contract, not only headline return values.

For each emitted attribute we check:

- semantic purpose;
- source or formula;
- response presence or intentional omission;
- percentage-point convention;
- date/window identity;
- metadata, diagnostics, and audit consistency;
- downstream UI relevance.

Small stateless examples are used for strict math assertions because every number can be derived
from the request. Canonical stateful probes remain runtime evidence for lotus-core and gateway
integration.

The workspace summary endpoint is explicitly drift-guarded against the canonical direct endpoints.
For the same stateless valuation points, tests call direct TWR, direct MWR, and workspace summary,
then assert that workspace TWR returns, MWR returns, method, dates, and explicit economic-context
fields match the canonical endpoint semantics. Workspace may shape the UI response, but it must not
own separate financial formulas.

## TWR Attribute Matrix

| Attribute | Certification expectation |
| --- | --- |
| `calculation_id` | Stable calculation identity; equals `meta.calculation_id`. |
| `portfolio_id` | Echoes the requested portfolio identifier. |
| `input_mode` | Echoes the resolved input mode, currently `stateless` or `stateful`. |
| `benchmark_context` | Present only when a benchmark is resolved; omitted when no benchmark was requested. |
| `results_by_period.<period>` | Contains one block for each resolved requested analysis period. |
| `portfolio.summary.period_return.base` | Linked TWR return for the resolved period in percentage points. |
| `portfolio.summary.period_return.local` | Local component; equals base in base-only deterministic certification case. |
| `portfolio.summary.period_return.fx` | FX component; zero in base-only deterministic certification case. |
| `portfolio.summary.cumulative_return` | Cumulative linked return through the resolved period end. |
| `portfolio.breakdowns.<frequency>[]` | Frequency-specific rows for the requested breakdown frequency. |
| `period` | Human-readable resolved bucket label matching the bucket date/window. |
| `period_start` / `period_end` | Inclusive bucket bounds. |
| `period_return` | Bucket-level return in percentage points, independently recomputed from market values, cash flows, and fees. |
| `cumulative_return` | Product-linked cumulative return through the bucket end. |
| `annualized_return` | Omitted when annualization is disabled or not applicable. |
| `daily_data` | Omitted unless explicitly requested for drill-down/diagnostic output. |
| `benchmark` | Omitted when no benchmark was requested; present and separately certified in benchmark-aware TWR probes. |
| `relative_performance` | Omitted when no benchmark is present; otherwise arithmetic active return versus benchmark. |
| `reset_events` | Omitted when no reset events were emitted. |
| `meta.engine_version` | Non-empty engine version from settings. |
| `meta.precision_mode` | Echoes resolved precision mode. |
| `meta.annualization` | Echoes annualization controls. |
| `meta.calendar` | Echoes calendar controls. |
| `meta.periods` | Carries requested periods and master calculation window. |
| `meta.input_fingerprint` / `meta.calculation_hash` | SHA-256 identities with `sha256:` prefix. |
| `diagnostics.effective_period_start` | Resolved effective start date for calculation. |
| `diagnostics.nip_days` / `reset_days` | Zero in clean deterministic certification case. |
| `diagnostics.valid_days_since_last_reset` | Equals valid row count in clean deterministic certification case. |
| `diagnostics.notes` | Empty when no warnings or fallback conditions are present. |
| `diagnostics.policy` / `samples` | Present with policy and sample evidence from the engine. |
| `audit.counts.input_rows` | Equals input valuation row count. |
| `audit.residual_applied_bp` | Zero in deterministic certification case. |

## TWR Deterministic Math Case

The certification test uses three daily valuation points:

- day 1: `1000 -> 1010`, no flows, expected `1.0%`;
- day 2: `1010 -> 1121`, `100` beginning-of-day cash flow, expected
  `(1121 - 1010 - 100) / (1010 + 100) = 0.99099099%`;
- day 3: `1121 -> 1071`, `-50` end-of-day cash flow and `-10` fee drag, expected
  `-10 / 1121 = -0.89206099%`.

The period return and final cumulative return are independently checked as the geometric link of
the daily returns.

## MWR Attribute Matrix

| Attribute | Certification expectation |
| --- | --- |
| `calculation_id` | Stable calculation identity; equals `meta.calculation_id`. |
| `portfolio_id` | Echoes the requested portfolio identifier. |
| `input_mode` | Echoes the resolved input mode. |
| `money_weighted_return` | MWR result in percentage points. |
| `mwr_annualized` | Present when annualization is produced; omitted when not applicable. |
| `method` | Computation path actually used, for example `XIRR` or `DIETZ`. |
| `status` | Calculation status, including calculated, fallback used, not calculable, or not applicable. |
| `reason_codes` | Machine-readable reason codes for fallback, not-calculable, or not-applicable states. Empty for clean calculations. |
| `warnings` | Machine-readable warning codes, including fallback warnings. Empty for clean calculations. |
| `holding_period_return` | Measured-period MWR in percentage points; for XIRR this distinguishes period outcome from annualized IRR. |
| `is_annualized_primary` | `true` when `money_weighted_return` is annualized XIRR; `false` for Dietz period return. |
| `fallback_from` / `fallback_reason` | Present when XIRR falls back to Dietz; omitted for clean direct calculations. |
| `is_approximation` | Indicates whether the emitted method is approximate. XIRR success is `false`; Dietz output is `true`. |
| `convergence` | Present for XIRR convergence evidence; omitted for direct Dietz output. |
| `cashflows_used` | Present when `emit_cashflows_used=true`; omitted when explicitly false. |
| `cashflows_used[].amount` / `date` | Exact signed cash-flow schedule used by the engine. |
| `start_date` | Earliest cash-flow date for stateless Dietz when no explicit start date is supplied; stateful uses requested window start. |
| `end_date` | Equals `as_of`. |
| `notes` | Empty for clean Dietz; carries solver/fallback notes for XIRR paths. |
| `meta.engine_version` | Non-empty engine version from settings. |
| `meta.precision_mode` | Echoes resolved precision mode. |
| `meta.annualization` | Echoes annualization controls. |
| `meta.calendar` | Echoes calendar controls. |
| `meta.periods` | Explicit MWR calculation window. |
| `meta.input_fingerprint` / `meta.calculation_hash` | SHA-256 identities with `sha256:` prefix. |
| `diagnostics.nip_days` / `reset_days` | Zero for MWR calculation path. |
| `diagnostics.effective_period_start` | Equals the resolved MWR start date. |
| `diagnostics.notes` | Mirrors method notes. |
| `audit.counts.cashflows` | Equals the number of cash flows passed to the engine even when `cashflows_used` is omitted. |

## MWR Deterministic Math Case

The certification test uses:

- beginning market value: `1000`;
- ending market value: `1120`;
- cash flows: `+100` on `2026-01-02`, `-20` on `2026-01-03`;
- net cash flow: `80`;
- Dietz numerator: `1120 - 1000 - 80 = 40`;
- Dietz denominator: `1000 + 80 / 2 = 1040`;
- expected MWR: `40 / 1040 = 3.846153846%`.

The test also proves that `emit_cashflows_used=false` omits the cash-flow echo while preserving
`audit.counts.cashflows`.

## Workspace Drift Guard

Workspace economics use explicit source economics:

- `net_cash_flow = beginning_cash_flow + ending_cash_flow`
- `flow_adjusted_end_market_value = end_market_value - explicit net_cash_flow`

Workspace economics must not include internal MWR carry-forward capital adjustments in
`beginning_cash_flow`, `ending_cash_flow`, `net_cash_flow`, or `flow_adjusted_end_market_value`.
Carry-forward capital adjustments can be part of the MWR calculation cash-flow schedule without
changing the display meaning of explicit workspace cash-flow fields.

The drift guard test asserts:

- workspace TWR summary and daily breakdown returns match direct TWR;
- workspace MWR method, return, and dates match direct MWR;
- workspace `beginning_cash_flow`, `ending_cash_flow`, `fees`, `net_cash_flow`, and
  `flow_adjusted_end_market_value` remain explicit display economics.

## Live Canonical Runtime Evidence

The latest live artifacts are under:

- `artifacts/twr-api-option-matrix-2026-04-10/`
- `artifacts/mwr-api-certification-2026-04-10/`

Current canonical MWR evidence after rebuild:

- direct stateful YTD XIRR MWR: about `-3.613903%`;
- direct stateful YTD Dietz MWR: about `-0.930505%`;
- gateway Workbench performance summary MWR: about `-3.613903%`.
- gateway/workspace `flow_adjusted_end_market_value` remains `end_market_value - explicit
  net_cash_flow`; it must not subtract carry-forward capital adjustments used internally for MWR.

Current TWR endpoint certification remains governed by:

- `docs/technical/twr-endpoint-certification.md`

Current MWR endpoint certification remains governed by:

- `docs/technical/mwr-endpoint-certification.md`

## Validation

```bash
python -m pytest tests/integration/test_response_attribute_certification.py -q
```
