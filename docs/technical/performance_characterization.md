# Performance Characterization

This document records the repo-owned capacity and performance characterization contract for
`lotus-performance`.

## Scope

This characterization currently governs the vectorized engine hot path behind
`engine.compute.run_calculations(...)`.

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
