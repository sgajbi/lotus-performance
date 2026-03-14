# Performance Characterization

This document records the repo-owned capacity and performance characterization contract for
`lotus-performance`.

## Scope

This characterization currently governs the vectorized engine hot path behind
`engine.compute.run_calculations(...)` plus the durable queue-stat aggregation paths used by
the runtime control plane and Prometheus collector, plus the public async execution-polling
read path, plus the stateful portfolio-retrieval orchestration path.

## Governed workload

- Workload type: single-portfolio daily TWR calculation
- Dataset size: `75,000` unique daily valuation rows
- Input pattern: repeating realistic valuation templates with unique `perf_date` values
- Precision mode: default `float64`

## Why not 500k daily rows

The older benchmark attempted to approximate `500k` rows by repeating three dates. That did
not create a true 500k-row engine dataframe, so it was not valid capacity evidence.

A true 500k unique-daily-row workload is also not representable in this engine path because
timestamp-backed daily dates hit pandas/numpy bounds well before that size. The governed
workload therefore uses the largest practical daily-row scale that still exercises the real
vectorized path with unique dates.

## Runtime budget

- Metric: median wall-clock runtime across 5 measured runs after one warm-up run
- Budget: `<= 0.50s`
- Test owner: [test_engine_performance.py](/C:/Users/Sandeep/projects/lotus-performance/tests/benchmarks/test_engine_performance.py)

This is a characterization contract, not a theoretical peak claim. If the engine changes
materially, we should refresh the budget using measured evidence and record that change in the
review ledger.

## Durable queue-stat budgets

These characterize the control-plane query path behind:

- `/integration/runtime-status`
- `/metrics`

### Compute queue stats

- Workload: `5,000` durable compute jobs
- Metric: median wall-clock runtime across 10 reads
- Budget: `<= 15ms`
- Test owner: [test_runtime_store_performance.py](/C:/Users/Sandeep/projects/lotus-performance/tests/benchmarks/test_runtime_store_performance.py)

### Lineage queue stats

- Workload: `1,000` durable lineage payloads
- Metric: median wall-clock runtime across 10 reads
- Budget: `<= 10ms`
- Test owner: [test_runtime_store_performance.py](/C:/Users/Sandeep/projects/lotus-performance/tests/benchmarks/test_runtime_store_performance.py)

## Execution polling budget

- Workload: one async execution with:
  - `5` lifecycle stages
  - `100` upstream snapshots
  - durable compute-job metadata
  - durable async-result metadata
- Metric: median wall-clock runtime across 20 reads
- Budget: `<= 20ms`
- Test owner: [test_execution_polling_performance.py](/C:/Users/Sandeep/projects/lotus-performance/tests/benchmarks/test_execution_polling_performance.py)

## Stateful retrieval budget

- Workload: stateful portfolio timeseries retrieval across `2024-01-01` to `2033-12-31`
- Retrieval characteristics:
  - `90`-day portfolio chunks
  - paginated upstream responses per chunk
  - durable upstream snapshot recording enabled
  - canonical deduped merge of returned observations
- Metric: median wall-clock runtime across 5 reads after warm-up
- Budget: `<= 250ms`
- Test owner: [test_stateful_input_performance.py](/C:/Users/Sandeep/projects/lotus-performance/tests/benchmarks/test_stateful_input_performance.py)

## Stateful reference retrieval budgets

### Benchmark return series

- Workload: stateful benchmark return-series retrieval across `2024-01-01` to `2033-12-31`
- Retrieval characteristics:
  - `365`-day reference chunks
  - durable upstream snapshot recording enabled
  - canonical deduped merge of returned points
- Metric: median wall-clock runtime across 5 reads after warm-up
- Budget: `<= 25ms`
- Test owner: [test_stateful_input_performance.py](/C:/Users/Sandeep/projects/lotus-performance/tests/benchmarks/test_stateful_input_performance.py)

### Risk-free series

- Workload: stateful risk-free series retrieval across `2024-01-01` to `2033-12-31`
- Retrieval characteristics:
  - `365`-day reference chunks
  - durable upstream snapshot recording enabled
  - canonical deduped merge of returned points
- Metric: median wall-clock runtime across 5 reads after warm-up
- Budget: `<= 25ms`
- Test owner: [test_stateful_input_performance.py](/C:/Users/Sandeep/projects/lotus-performance/tests/benchmarks/test_stateful_input_performance.py)
