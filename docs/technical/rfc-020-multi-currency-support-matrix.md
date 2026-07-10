# RFC-020 Multi-Currency Support Matrix

This matrix is the canonical endpoint-by-endpoint support truth for RFC-020 currency semantics in
`lotus-performance`.

RFC-020 remains the strategic methodology target for local, FX, and base-currency analytics. Current
implementation is intentionally endpoint-specific. Do not infer endpoint-wide parity from shared
terms such as `currency_mode`, `report_ccy`, `reporting_currency`, `fx`, local return, FX return, or
base return.

## Status Vocabulary

| Status | Meaning |
| --- | --- |
| Implemented | The endpoint owns the named currency behavior and has test/certification evidence. |
| Partial | The endpoint exposes bounded currency evidence, but not the full RFC-020 target. |
| Unsupported | The endpoint intentionally does not support that currency behavior today. |
| Superseded | Older RFC wording is replaced by a more specific current contract. |

## Endpoint Matrix

| Endpoint | Current status | Supported request controls | Required source evidence | Response fields | Unsupported or superseded gaps | Proof |
| --- | --- | --- | --- | --- | --- | --- |
| `POST /performance/twr` | Partial | `currency_mode`, `report_ccy`, `fx.rates[]`, optional `hedging.series[]` activate the FX decomposition path when supplied. | Caller-supplied stateless FX rates or stateful upstream valuation data already normalized for the selected path. | `portfolio.summary.period_return.local`, `portfolio.summary.period_return.fx`, `portfolio.summary.period_return.base`, plus cumulative local/FX/base fields when the FX path is active. | Full endpoint-wide hedging product modeling and all-position local/FX evidence remain bounded to the current engine path. | `docs/methodologies/metrics/metric-twr-local-return.md`; `docs/methodologies/metrics/metric-twr-fx-return.md`; `tests/integration/test_performance_api.py`. |
| `POST /performance/mwr` | Partial | Stateless requests may supply `source_preconverted_fx_evidence`; stateful requests carry `reporting_currency` from lotus-core source context. | MWR engine inputs must already be in one reporting-currency schedule. Complete stateless source-preconverted FX evidence is validated when supplied. Stateful cross-currency inputs currently lack per-input FX rate/policy/version/fingerprint evidence. | `reporting_currency`; `currency_evidence.currency_mode` values `SINGLE_REPORTING_CURRENCY` or `SOURCE_PRECONVERTED_WITH_FX_EVIDENCE`; `conversion_evidence_status`; `market_values_used[]`; `cashflow_evidence[]`; `source_cashflow_quality`. | In-engine FX conversion and stateful complete per-input FX provenance are not implemented. Do not treat MWR as `currency_mode=BOTH` parity with Attribution. | `docs/technical/mwr-fx-contract-design.md`; `docs/methodologies/metrics/metric-mwr-xirr.md`; `docs/methodologies/metrics/metric-mwr-dietz.md`; `tests/integration/test_mwr_api.py`. |
| `POST /performance/contribution` | Implemented for contribution local/FX controls | `currency_mode="BOTH"` with `report_ccy`; stateful source position currencies; `fx.rates[]` when sourced position currencies differ from `report_ccy`; hierarchy, smoothing, and emit controls remain endpoint-specific. | Stateful portfolio and position rows from lotus-core, source position currencies, and FX rates for mixed-currency stateful inputs; stateless caller-provided contribution inputs and FX context. | Position and hierarchy contribution fields; local/FX contribution residual allocation that reconciles local plus FX contribution to total contribution when the multi-currency path is active. | Fund/structured-product lookthrough decomposition and broader source-economics P&L families remain source-owned and are not inferred locally. | `docs/guides/contribution.md`; `docs/technical/contribution-endpoint-certification.md`; `tests/integration/test_contribution_api.py`. |
| `POST /performance/attribution` | Implemented for currency attribution path | `currency_mode="BOTH"`, `report_ccy`, `fx.rates[]` when sourced positions include non-reporting currencies, and `group_by` including `currency` for currency attribution output. | Source position currencies, benchmark/portfolio local and FX return columns, and FX rates when mixed currencies require them. | `currency_attribution[]`; `currency_attribution_totals`; attribution group rows with portfolio/benchmark return evidence; supportability evidence for currency attribution posture. | Other currency modes are not parity targets for Attribution until explicitly designed and tested. | `docs/guides/attribution.md`; `docs/technical/attribution-endpoint-certification.md`; `tests/integration/test_attribution_api.py`. |
| `POST /performance/benchmark` | Implemented for benchmark normalization | Stateful calculated mode sources benchmark definition, component price series, and FX inputs from lotus-core. | lotus-core benchmark component prices, composition windows, and FX rates when component prices require normalization to benchmark currency. | Benchmark daily returns, component contributions, diagnostics, audit, and benchmark context. | The endpoint is not a general client-supplied RFC-020 local/FX/base decomposition surface. | `docs/guides/benchmark.md`; `docs/technical/benchmark-endpoint-certification.md`; `tests/integration/test_benchmark_api.py`. |
| `POST /integration/returns/series` | Partial | `reporting_currency` is required for stateful risk-free sourcing; benchmark return source controls determine calculated versus vendor series. | Portfolio return series, benchmark return series or benchmark calculation inputs, and risk-free return series by reporting currency. | Portfolio, benchmark, active, cumulative active, risk-free, diagnostics, benchmark context, and fill evidence. | Returns-series emits aligned return observations, not local/FX/base decomposition. | `docs/technical/returns-series-endpoint-certification.md`; `docs/methodologies/metrics/metric-returns-series-risk-free.md`; `tests/integration/test_returns_series_api.py`. |
| `POST /performance/workspace-summary` | Partial aggregator | Uses upstream endpoint outputs rather than owning independent currency-mode controls. | Source-owned TWR, MWR, benchmark, contribution, attribution, and returns-series outputs. | Workspace summary fields and warnings preserve source endpoint currency posture. | Workspace summary must not invent or reinterpret FX evidence absent from source endpoint responses. | `docs/technical/workspace-summary-endpoint-certification.md`; `tests/unit/services/test_workspace_summary_service.py`. |

## Governance Rules

1. New or removed endpoint currency modes must update this matrix in the same change.
2. Endpoint guides and API reference pages should link here rather than restating cross-endpoint
   parity claims.
3. MWR remains a reporting-currency schedule calculation with optional source-preconverted FX
   provenance until stateful upstream per-input FX evidence is available and validated.
4. Attribution `currency_mode="BOTH"` is the only current public currency-attribution path.
5. Unsupported RFC-020 goals should be classified as `Unsupported`, `Partial`, or `Superseded`
   instead of being implied as implemented by old RFC language.
