# Benchmark Endpoint Certification

Status: certified for `POST /performance/benchmark` and
`GET /performance/benchmark/results/{calculation_id}`

Canonical live portfolio: `PB_SG_GLOBAL_BAL_001`

Governed as-of date: `2026-04-10`

Canonical benchmark: `BMK_PB_GLOBAL_BALANCED_60_40`

## Endpoint Purpose

`POST /performance/benchmark` calculates a benchmark's own return path and, in calculated mode,
component-level benchmark contribution. Use it when the business question is "what did this
benchmark return, and which benchmark components drove that return?"

Use this endpoint for:

- standalone benchmark performance review;
- calculated benchmark return from beginning-of-day component weights and component returns;
- benchmark return derivation from component price points;
- stateful lotus-core-backed benchmark composition, index price, and FX sourcing;
- benchmark component contribution and local/FX return decomposition;
- async benchmark execution and durable result retrieval.

Do not use this endpoint for:

- portfolio headline return. Use `POST /performance/twr`;
- investor capital-timing return. Use `POST /performance/mwr`;
- generic downstream return-series sourcing. Use `POST /integration/returns/series`;
- benchmark exposure history for active-risk attribution. Use
  `POST /integration/benchmarks/exposure-context`;
- source-quality triage. Use inspector and upstream snapshot artifacts.

## Supported Request Options

Validated option families:

- `input_mode="stateless"` with `return_source="calculated"` and
  `stateless_input.component_observations`;
- `input_mode="stateless"` with `return_source="calculated"` and
  `stateless_input.component_price_points`;
- `input_mode="stateless"` with `return_source="vendor_series"` and
  `stateless_input.benchmark_return_points`;
- `input_mode="stateful"` with `return_source="calculated"` and `stateful_input={}`;
- `input_mode="stateful"` with `return_source="vendor_series"` and `stateful_input={}`;
- `analyses` including canonical `SI`, `YTD`, and `EXPLICIT`, with legacy `ITD` accepted only as a `SI` alias;
- `frequencies` including daily, weekly, monthly, quarterly, and yearly;
- `output.include_timeseries=true` and `false`;
- caller-supplied or service-generated `calculation_id`;
- async `202 Accepted` result polling through `/performance/benchmark/results/{calculation_id}`.

## Required Figure Tie-Outs

Every certified benchmark response must satisfy these invariants for each resolved period:

- `benchmark.summary.period_return.base` is the geometric link of daily benchmark returns inside
  the period;
- `benchmark.summary.period_return.local` and `.fx`, when present, are the linked daily local and FX
  components in percentage-point output units;
- `benchmark.summary.cumulative_return` is linked through the period end from the benchmark master
  start date;
- each `benchmark.breakdowns.<frequency>[]` row has bucket period return and cumulative return that
  reconcile to the daily return ladder;
- `daily_returns[].benchmark_return` equals the sum of same-date component contributions in
  calculated mode;
- `daily_returns[].cumulative_return` geometrically links the emitted daily return ladder;
- each `component_contributions[]` row satisfies
  `contribution = weight_bop * component_return` after percentage scaling;
- each `component_contributions[]` local and FX contribution satisfies the same weight application
  when local/FX components are supplied;
- `audit.counts.component_observations`, `audit.counts.benchmark_return_points`, and
  `audit.counts.daily_returns` match the normalized calculation input and output;
- `audit.residual_applied_bp` reports component-weight deviation in basis points;
- `diagnostics.effective_period_start` identifies the earliest effective benchmark observation;
- `meta.input_fingerprint` and `meta.calculation_hash` are stable lineage hashes for reproducibility.

## Upstream Integration

Stateful calculated benchmark mode sources:

- benchmark composition-window from lotus-core;
- component index price series from lotus-core;
- FX rates from lotus-core when component currency differs from benchmark currency.

Stateful vendor-series mode sources benchmark definition and benchmark return series from lotus-core.
lotus-core remains the benchmark definition, composition, index-series, and FX source of record.
lotus-performance owns return derivation, component contribution, linkage, lineage, diagnostics,
and response semantics.

## Downstream Consumers

Known consumers:

| Consumer | How it uses benchmark analytics | Evidence |
| --- | --- | --- |
| `lotus-gateway` performance workspace | Does not call `/performance/benchmark` directly. It requests benchmark-aware TWR and workspace-summary outputs, which are the correct UI-facing aggregate surfaces. | `lotus-gateway/src/app/clients/lotus_analytics_client.py`; `lotus-gateway/src/app/services/performance_workspace_service.py` |
| `lotus-workbench` | Consumes benchmark-aware gateway workspace contracts, not the raw benchmark endpoint. | `lotus-workbench/src/apps/performance` |
| `lotus-risk` | Does not call `/performance/benchmark`; it correctly consumes `/integration/returns/series` for benchmark return series and `/integration/benchmarks/exposure-context` for benchmark exposure history. | `lotus-risk/src/app/services/stateful_returns_request.py`; `lotus-risk/docs/standards/risk-analytics-contract.md` |

No duplicate downstream use of `/performance/benchmark` was found during this pass. If a downstream
application later uses `/performance/benchmark` only to source aligned benchmark return series, it
should migrate to `POST /integration/returns/series` because that is the strategic integration
surface for downstream analytics engines.

## GitHub Issue Disposition

Open issue search for benchmark found only broad stateful sourcing issue `#83`. It remains open
because it covers more than benchmark endpoint certification. No direct benchmark endpoint defect
issue was found during this pass.

## Test Pyramid Assessment

| Layer | Coverage | Assessment |
| --- | --- | --- |
| Model and validation tests | Request-mode exclusivity, return-source shape validation, explicit-period requirements, schema examples, and accepted-response schema documentation. | Adequate after this pass. |
| Engine tests | Component contribution aggregation, local/FX component preservation, weight residual diagnostics, vendor-series linking, duplicate rejection, and empty input rejection. | Good for benchmark math. |
| Service tests | Period slicing, breakdown labels, timeseries omission, vendor-series behavior, explicit windows, and helper scaling. | Good; standalone endpoint now emits input-mode context in the benchmark block. |
| Integration tests | Stateless calculated, price-derived, stateful calculated, vendor-series, async result retrieval, failure persistence, and full response attribute tie-out. | Strong for the current contract. |
| Documentation and OpenAPI tests | Public guide, API reference, route descriptions, schema examples, OpenAPI quality, and vocabulary gates. | Adequate after this pass. |
| Cross-repo consumer tests | Gateway and risk code searches show correct strategic endpoint usage; focused downstream tests are not required because the benchmark endpoint shape is not directly consumed. | Adequate for known consumers. |
| Live canonical probes | Stateful canonical benchmark request for `BMK_PB_GLOBAL_BALANCED_60_40` through rebuilt local service. | Required before PR readiness. |

## Live Canonical Evidence

Rebuilt local runtime evidence for `BMK_PB_GLOBAL_BALANCED_60_40`, YTD through `2026-04-10`,
using `POST http://localhost:8002/performance/benchmark`:

| Check | Result |
| --- | --- |
| Response status | `200` |
| `input_mode` / `return_source` | `stateful` / `calculated` |
| Benchmark currency | `USD` |
| YTD period return | `5.095680231948784%` |
| YTD cumulative return | `5.095680231948784%` |
| Daily return rows | `100` |
| Component contribution rows | `200` |
| Monthly breakdown buckets | `4` |
| Maximum absolute daily benchmark return | about `0.121214%` |
| `2026-04-10` daily return | `0.11165395961018762%` |
| `2026-04-10` component contribution sum | `0.1116539596101876%` |
| Audit counts | `component_observations=200`, `daily_returns=100`, `benchmark_return_points=0` |
| Weight residual | `0.0` basis points |
| Diagnostics notes | none |

## Validation Commands

Focused validation for benchmark changes should include:

```powershell
python -m pytest tests\unit\engine\test_benchmarks.py tests\unit\services\test_benchmark_calculation_service.py tests\unit\services\test_benchmark_mode_service.py tests\unit\services\test_stateful_benchmark_input_service.py tests\unit\services\test_stateless_benchmark_input_service.py tests\unit\models\test_benchmark_analytics_requests.py tests\unit\models\test_benchmark_requests.py tests\unit\models\test_benchmark_response_models.py tests\unit\app\test_benchmark_openapi_contract.py tests\integration\test_benchmark_api.py -q
ruff check app\api\endpoints\benchmark.py app\models\benchmark_analytics_requests.py app\models\benchmark_responses.py app\services\benchmark_calculation_service.py app\services\benchmark_service.py tests\integration\test_benchmark_api.py tests\unit\models\test_benchmark_analytics_requests.py tests\unit\models\test_benchmark_response_models.py tests\unit\app\test_benchmark_openapi_contract.py
ruff format --check app\api\endpoints\benchmark.py app\models\benchmark_analytics_requests.py app\models\benchmark_responses.py app\services\benchmark_calculation_service.py app\services\benchmark_service.py tests\integration\test_benchmark_api.py tests\unit\models\test_benchmark_analytics_requests.py tests\unit\models\test_benchmark_response_models.py tests\unit\app\test_benchmark_openapi_contract.py
mypy app\api\endpoints\benchmark.py app\models\benchmark_analytics_requests.py app\models\benchmark_responses.py app\services\benchmark_calculation_service.py app\services\benchmark_service.py
python scripts/openapi_quality_gate.py
python scripts/api_vocabulary_inventory.py --validate-only
```
