# RFC-023 Benchmark Contract Baseline

This page is the current implementation baseline for RFC-023. It separates the historical
`benchmark_spec` proposal from the supported benchmark contract implemented through RFC-042.

## Current Contract

| Area | Current support | Evidence | Boundary |
| --- | --- | --- | --- |
| Benchmark identity | Supported through `benchmark_id`; stateful mode can resolve portfolio benchmark assignment from lotus-core when the caller omits the id. | `app/models/benchmark_analytics_requests.py`; `docs/guides/benchmark.md`; benchmark integration tests. | lotus-core remains benchmark reference-data owner. |
| Calculated benchmark returns | Supported through `return_source="calculated"` using component observations or component price points in stateless mode, and lotus-core-sourced composition/price/FX inputs in stateful mode. | `docs/RFCs/RFC 042 - Core-Sourced Benchmark Performance Engine.md`; `docs/guides/benchmark.md`; `tests/integration/test_benchmark_api.py`. | This is the canonical replacement path for active benchmark calculation. |
| Vendor benchmark return series | Supported through explicit `return_source="vendor_series"`. | `app/models/benchmark_analytics_requests.py`; benchmark API tests. | Component contribution output is not emitted because lotus-performance did not calculate component returns. |
| TWR benchmark inclusion | Supported through `include_benchmark=true` plus optional nested `benchmark` configuration. | `docs/guides/twr.md`; `docs/guides/api_reference.md`; TWR integration tests. | `benchmark_spec` is not a TWR request field. |

## Superseded RFC-023 Scope

These original RFC-023 concepts are not current implementation targets:

| Original RFC-023 concept | Current status | Replacement or future path |
| --- | --- | --- |
| Free-form request `benchmark_spec` | Superseded by RFC-042 | Use `benchmark_id`, `input_mode`, `return_source`, and `stateless_input` / `stateful_input` instead. |
| `POST /benchmarks/resolve` helper endpoint | Unsupported | Add a separate endpoint RFC only if consumers need independent benchmark-resolution output. |
| `engine/benchmarks.py` dynamic blend engine | Superseded as named module target | Current benchmark logic follows the implemented benchmark service/engine modules and RFC-042 source contracts. |
| Caller-owned benchmark definition and market-data source | Superseded for stateful mode | lotus-core owns benchmark definitions, composition windows, component universe, prices, FX inputs, and assignment. |
| Drift, monthly, quarterly, annual, and scheduled policy rebalancing from `benchmark_spec` | Future backlog only | Implement through lotus-core effective-dated composition windows or a separately approved policy-weight contract, not a free-form request block. |

## No-Claim Rule

Current public docs and examples may describe `benchmark_id`, `input_mode`, `return_source`,
`component_observations`, `component_price_points`, `benchmark_return_points`, lotus-core stateful
sourcing, and RFC-042 composition-window behavior. They must not advertise `benchmark_spec` as a
supported request field unless the API models, OpenAPI examples, benchmark service, endpoint tests,
and downstream docs implement that exact contract.

## Future Backlog Shape

Future benchmark work should be split by capability instead of reviving RFC-023 as one broad final
contract:

1. independent benchmark-resolution endpoint, if a downstream consumer needs it;
2. policy-weight change schedule support through lotus-core-owned composition windows;
3. drift-threshold rebalance policy with deterministic source authority;
4. benchmark component FX normalization hardening;
5. downstream Gateway/Workbench support for any newly implemented benchmark capability.

