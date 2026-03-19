# Performance Characterization

This document records the repo-owned capacity and performance characterization contract for
`lotus-performance`.

## Scope

This characterization currently governs the vectorized engine hot path behind
`engine.compute.run_calculations(...)` plus the durable queue-stat aggregation paths used by
the runtime control plane and Prometheus collector, plus the public async execution-polling
read path, plus the stateful portfolio-retrieval orchestration path, plus calculated stateful
benchmark normalization, plus PostgreSQL query-plan verification for the durable hot-path reads.

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

## Stateful returns-series orchestration budget

- Workload: one stateful returns-series request across `2024-01-01` to `2033-12-31` with:
  - portfolio return series
  - benchmark return series
  - risk-free return series
  - daily frequency
  - canonical normalization and response shaping
- Metric: median wall-clock runtime across 5 reads after warm-up
- Budget: `<= 1200ms`
- Test owner: [test_returns_series_orchestration_performance.py](/C:/Users/Sandeep/projects/lotus-performance/tests/benchmarks/test_returns_series_orchestration_performance.py)

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

## Stateful calculated benchmark normalization budget

- Workload: calculated stateful benchmark normalization across `2024-01-01` to `2033-12-31`
- Retrieval characteristics:
  - effective-dated composition-window sourcing
  - `365`-day component price-series chunks
  - `365`-day FX-rate chunks for non-benchmark-currency components
  - beginning-of-day weight application across rebalance segments
  - durable upstream snapshot recording enabled
- Benchmark shape:
  - `4` benchmark components
  - `8` effective-dated composition segments
  - `3` FX pairs normalized into benchmark currency
- Metric: median wall-clock runtime across 5 reads after warm-up
- Budget: `<= 2200ms`
- Test owner: [test_stateful_input_performance.py](/C:/Users/Sandeep/projects/lotus-performance/tests/benchmarks/test_stateful_input_performance.py)

## Stateful benchmark orchestration budget

- Workload: full stateful benchmark orchestration across `2024-01-01` to `2033-12-31`
- Orchestration characteristics:
  - calculated benchmark mode
  - shared benchmark request resolution
  - effective-dated composition-window sourcing
  - component price loading and FX normalization
  - benchmark response shaping with daily timeseries enabled
  - durable execution identity updates and lineage handoff
- Benchmark shape:
  - `4` benchmark components
  - `8` effective-dated composition segments
  - `3` FX pairs normalized into benchmark currency
- Metric: median wall-clock runtime across 5 runs after warm-up
- Budget: `<= 3600ms`
- Test owner: [test_benchmark_orchestration_performance.py](/C:/Users/Sandeep/projects/lotus-performance/tests/benchmarks/test_benchmark_orchestration_performance.py)

## Stateful benchmark-inclusive TWR orchestration budget

- Workload: full stateful benchmark-inclusive TWR orchestration across `2024-01-01` to `2033-12-31`
- Orchestration characteristics:
  - stateful portfolio valuation sourcing
  - stateful benchmark assignment lookup
  - calculated benchmark sourcing and normalization
  - TWR engine execution with benchmark inclusion
  - arithmetic relative-performance output
  - durable execution identity updates and lineage handoff
- Request shape:
  - `include_benchmark=true`
  - implicit benchmark assignment from lotus-core
  - `ITD` request with monthly breakdown output
- Metric: median wall-clock runtime across 5 runs after warm-up
- Budget: `<= 4200ms`
- Test owner: [test_twr_orchestration_performance.py](/C:/Users/Sandeep/projects/lotus-performance/tests/benchmarks/test_twr_orchestration_performance.py)

## PostgreSQL plan verification

These checks are not generic SQL compilation tests. They run `EXPLAIN (FORMAT JSON)` against a
live PostgreSQL durable metadata store after explicit `ANALYZE`, so the planner contract is
based on realistic table statistics rather than empty-table defaults.

### Compute queue stats

- Workload: `5,000` durable compute jobs
- Plan contract:
  - root aggregate plan over `analytics_compute_job`
  - no explicit `Sort`
  - no planner regression into multi-query application-side aggregation
- Test owner: [test_postgres_query_plans.py](/C:/Users/Sandeep/projects/lotus-performance/tests/benchmarks/test_postgres_query_plans.py)

### Lineage queue stats

- Workload: `1,000` durable lineage payloads with joined lineage records
- Plan contract:
  - root aggregate plan over the `lineage_payloads` / `lineage_records` join
  - no explicit `Sort`
  - join/aggregate remains in SQL rather than application-side row walks
- Test owner: [test_postgres_query_plans.py](/C:/Users/Sandeep/projects/lotus-performance/tests/benchmarks/test_postgres_query_plans.py)

### Execution snapshot polling

- Workload: `25` executions with `100` upstream snapshots each
- Plan contract:
  - ordered snapshot polling uses the composite `ix_upstream_snapshot_calculation_created_at` index
  - no fallback to sequential scan on `analytics_upstream_snapshot`
- Notes:
  - PostgreSQL may still choose a bitmap-heap-plus-sort plan at this cardinality after `ANALYZE`
    because the query returns all snapshots for one calculation and the sort is cheap; the governed
    contract is index participation plus no sequential scan, not a brittle “never sort” rule.
- Test owner: [test_postgres_query_plans.py](/C:/Users/Sandeep/projects/lotus-performance/tests/benchmarks/test_postgres_query_plans.py)

## Running the characterization suite

- Full repo-owned characterization: `make performance-characterization`
- Live PostgreSQL plan verification: `make performance-characterization-postgres`

## PostgreSQL concurrency proof

These are live multi-worker claim contracts against PostgreSQL, not SQLite compilation proxies.

### Compute queue claims

- Workload: `20` pending compute jobs, `2` workers, `10` claims each
- Contract:
  - claims are disjoint across workers
  - all available jobs are claimed exactly once
  - a third worker sees no additional pending claims
- Test owner: [test_postgres_concurrency_contracts.py](/C:/Users/Sandeep/projects/lotus-performance/tests/benchmarks/test_postgres_concurrency_contracts.py)

### Lineage payload claims

- Workload: `20` pending lineage payloads, `2` workers, `10` claims each
- Contract:
  - claims are disjoint across workers
  - all available payloads are claimed exactly once
  - a third worker sees no additional pending claims
- Test owner: [test_postgres_concurrency_contracts.py](/C:/Users/Sandeep/projects/lotus-performance/tests/benchmarks/test_postgres_concurrency_contracts.py)
