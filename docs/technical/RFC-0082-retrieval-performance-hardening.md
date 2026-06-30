# RFC-0082 Retrieval Performance Hardening

This document records the `lotus-performance` Slice 4 retrieval-performance decision for platform
RFC-0082.

It should be read with:

1. `C:/Users/Sandeep/projects/lotus-platform/rfcs/RFC-0082-lotus-core-domain-authority-and-analytics-serving-boundary-hardening.md`
2. `docs/technical/RFC-0082-upstream-contract-family-map.md`
3. `docs/technical/performance_characterization.md`

## Scope

This slice evaluates the high-volume `lotus-performance` retrieval paths that consume `lotus-core`
analytics-input contracts.

Covered paths:

1. stateful portfolio timeseries retrieval,
2. stateful benchmark return-series retrieval,
3. stateful risk-free series retrieval,
4. calculated stateful benchmark normalization,
5. stateful returns-series orchestration.

Out of scope:

1. changing the transport protocol,
2. changing `lotus-core` API contracts,
3. changing OpenAPI schemas,
4. changing runtime defaults without additional live evidence.

## Current Retrieval Shape

Current configured defaults:

| Setting | Default | Purpose |
| --- | ---: | --- |
| `STATEFUL_INPUT_PORTFOLIO_CHUNK_DAYS` | `90` | Bounds portfolio and position analytics-input windows. |
| `STATEFUL_INPUT_REFERENCE_CHUNK_DAYS` | `365` | Bounds benchmark, index, FX, and risk-free reference windows. |
| `STATEFUL_INPUT_MAX_CONCURRENT_CHUNKS` | `4` | Caps concurrent upstream chunk retrieval. |
| `UPSTREAM_HTTP_MAX_CONNECTIONS` | `100` | Caps the lifecycle-managed outbound HTTP connection pool used by lotus-core and Lotus AI calls. |
| `UPSTREAM_HTTP_MAX_KEEPALIVE_CONNECTIONS` | `20` | Caps idle keep-alive connections retained for upstream fan-out. |
| `UPSTREAM_HTTP_KEEPALIVE_EXPIRY_SECONDS` | `30.0` | Controls keep-alive expiry for managed upstream HTTP connections. |
| portfolio/position `page_size` | `5000` | Requests large-but-bounded pages from `lotus-core` analytics-input contracts. |

Current orchestration behavior:

1. large windows are split into deterministic date chunks,
2. chunk retrieval is bounded by a concurrency semaphore,
3. outbound lotus-core calls use a lifecycle-managed `httpx.AsyncClient` pool under the FastAPI lifespan,
4. paginated portfolio and position inputs are merged and deduplicated by stable keys,
5. durable calculations record upstream request and response fingerprints,
6. benchmark and reference inputs use larger chunks because their payloads are narrower than position-level datasets.

## Characterization Evidence

Command run for this slice:

```powershell
python -m pytest tests/benchmarks/test_stateful_input_performance.py tests/benchmarks/test_returns_series_orchestration_performance.py -q --durations=10
```

Result:

```text
5 passed in 49.75s
```

Slowest test-call durations from the run:

| Test | Duration |
| --- | ---: |
| `test_returns_series_stateful_orchestration_characterization_contract` | `33.14s` |
| `test_stateful_calculated_benchmark_characterization_contract` | `14.99s` |
| `test_stateful_portfolio_timeseries_characterization_contract` | `0.96s` |
| `test_stateful_risk_free_reference_characterization_contract` | `0.19s` |
| `test_stateful_benchmark_reference_characterization_contract` | `0.19s` |

These are full pytest call durations, not the internal median budget values asserted by each test.
The tests passed their governed median budgets defined in `docs/technical/performance_characterization.md`.

## Decision

Current evidence does not justify adding gRPC between `lotus-performance` and `lotus-core`.

Reasoning:

1. the hot retrieval paths already have bounded chunking, pagination, concurrency, retry, and lineage behavior;
2. the existing characterization suite passes the current 10-year stateful retrieval and orchestration budgets;
3. the slowest paths are dominated by orchestration and normalization work, not proven REST transport overhead;
4. `lotus-core` already exposes an async analytics-timeseries export contract for larger retrieval use cases;
5. adding a second transport now would increase contract governance, CI, and operational complexity without measured need.

## Tuning Order Before Any Transport Proposal

Future retrieval-performance work must use this order:

1. profile payload size, chunk count, page count, and upstream latency separately;
2. tune `STATEFUL_INPUT_PORTFOLIO_CHUNK_DAYS`;
3. tune `STATEFUL_INPUT_REFERENCE_CHUNK_DAYS`;
4. tune `STATEFUL_INPUT_MAX_CONCURRENT_CHUNKS`;
5. tune `UPSTREAM_HTTP_MAX_CONNECTIONS`, `UPSTREAM_HTTP_MAX_KEEPALIVE_CONNECTIONS`, and `UPSTREAM_HTTP_KEEPALIVE_EXPIRY_SECONDS`;
6. tune portfolio/position `page_size`;
7. use the `lotus-core` analytics export job contract for bulk windows where polling many pages is the bottleneck;
8. review upstream query plans and indexes in `lotus-core`;
9. consider transport only after the prior steps produce evidence that serialization or HTTP request overhead is the dominant bottleneck.

## gRPC Reconsideration Threshold

A gRPC proposal is acceptable only if a future characterization report proves all of the following:

1. `lotus-performance` and `lotus-core` are spending material latency in transport serialization or request overhead after chunk/page/export tuning;
2. upstream query time and consumer normalization time are not the dominant cost;
3. the affected contract is stable enough to justify dual REST and gRPC governance;
4. OpenAPI remains the external and cross-repo governance source of truth;
5. a generated protobuf contract, backward-compatibility policy, observability contract, and CI lane are included in the proposal.

Until those conditions are met, REST/OpenAPI remains the correct integration model.

## Current Follow-Up Register

1. Add live environment retrieval telemetry when canonical core/performance seeded runs are available:
   chunk count, page count, payload row count, upstream latency, merge latency, and lineage write latency.
2. Compare interactive paged retrieval against `lotus-core` analytics export jobs for very large position windows.
3. Keep benchmark, index, risk-free, FX, and position-heavy retrievals under the existing characterization suite.
4. Escalate to PR Merge Gate only when runtime defaults, request/response contracts, or upstream API behavior change.
