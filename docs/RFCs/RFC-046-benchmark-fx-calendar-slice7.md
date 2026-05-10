# RFC-046 Slice 7 FX, Currency, Benchmark, and Calendar Alignment

| Field | Value |
| --- | --- |
| RFC | RFC-046 - TWR Industry Methodology Alignment, Evidence Contract, and Data Product Hardening |
| Slice | 7 - FX, Currency, Benchmark, and Calendar Alignment |
| `lotus-performance` branch | `feat/rfc-046-twr-industry-evidence` |

## Implementation

Slice 7 adds implementation-backed benchmark, FX, and calendar supportability evidence to
`benchmark_context.supportability_evidence` on TWR responses when benchmark output is requested.

The evidence records:

- resolved benchmark input mode and return source
- requested reporting currency and benchmark currency
- benchmark currency state:
  - `single_currency`
  - `base_only`
  - `fx_decomposed`
  - `vendor_series_base_only`
- portfolio and benchmark daily observation counts
- overlapping observation count
- missing portfolio-vs-benchmark date counts and bounded date samples
- calendar-alignment state:
  - `aligned`
  - `partial_overlap`
  - `no_overlap`
- bounded warning codes for benchmark calendar gaps, vendor-series base-only evidence, missing FX
  decomposition, and benchmark/reporting currency differences

Slice 7 does not add composite, group, or sleeve TWR calculation. It also does not claim benchmark FX
decomposition when Lotus only receives a vendor return series.

## Currency And FX Policy

Stateless benchmark component price points already reject cross-currency components when
`fx_rate_to_benchmark` is missing. Slice 7 makes that behavior visible in the product docs and adds
response evidence for successful benchmark calculations:

- calculated benchmark returns with local and FX columns are `fx_decomposed`
- vendor return series are `vendor_series_base_only`
- single-currency calculated benchmarks are `single_currency`
- component-observation payloads that carry cross-currency component metadata without local/FX
  decomposition are `base_only` with `BENCHMARK_FX_DECOMPOSITION_UNAVAILABLE`

## Calendar Alignment Policy

TWR active return remains calculated only for periods where benchmark observations are available.
Slice 7 exposes whether the portfolio and benchmark daily observation sets align:

- `aligned`: portfolio and benchmark dates match
- `partial_overlap`: at least one side has missing dates but overlap exists
- `no_overlap`: no shared daily observation dates exist

This evidence lets downstream consumers explain benchmark gaps without treating a missing benchmark
date as a hidden calculation success.

## Validation

Slice 7 was validated with focused, contract, governance, and full coverage gates:

- `python -m pytest tests/unit/services/test_twr_benchmark_supportability.py tests/unit/app/test_twr_openapi_contract.py tests/unit/docs/test_public_docs_contract.py tests/integration/test_performance_api.py::test_twr_supports_stateless_benchmark_request tests/integration/test_performance_api.py::test_twr_supports_stateful_benchmark_assignment tests/integration/test_performance_api.py::test_twr_supports_include_benchmark_without_nested_stateful_benchmark_config tests/unit/services/test_stateless_benchmark_input_service.py::test_normalize_stateless_component_observations_rejects_cross_currency_price_points_without_fx -q`
  - Result: `50 passed, 1 warning`
- `python -m pytest tests/integration/test_performance_api.py tests/integration/test_response_attribute_certification.py tests/unit/app/test_twr_openapi_contract.py tests/unit/docs/test_public_docs_contract.py tests/unit/models/test_responses_models.py tests/unit/services/test_twr_benchmark_supportability.py tests/unit/services/test_stateless_benchmark_input_service.py -q`
  - Result: `100 passed, 7 warnings`
- `python -m pytest tests/unit/services/test_compute_executor_worker.py::test_compute_executor_worker_processes_resolved_twr_job -q`
  - Result: `1 passed`
- `python -m pytest tests/integration/test_execution_api.py::test_execution_api_tracks_async_twr_job_state -q`
  - Result: `1 passed`
- `make typecheck`
  - Result: `Success: no issues found in 159 source files`
- `make lint`
  - Result: passed, including the monetary-float guard with `135` findings and `135` allowlisted findings
- `python scripts/openapi_quality_gate.py`
  - Result: passed
- `make api-vocabulary-gate`
  - Result: passed with no vocabulary drift
- `python scripts/no_alias_contract_guard.py`
  - Result: passed
- `make coverage-gate`
  - Result: unit `1200 passed`, integration `274 passed`, e2e `21 passed`, combined coverage `99%`
