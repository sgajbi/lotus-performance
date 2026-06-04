## Summary

| Metric | Value |
| --- | ---: |
| Router and middleware oversized function findings | 8 |
| Oversized router functions | 8 |
| Oversized middleware functions | 0 |

## Findings

| Rank | Kind | File | Function | Lines |
| ---: | --- | --- | --- | ---: |
| 1 | router | `app/api/endpoints/performance.py:337` | `calculate_twr_endpoint` | 151 |
| 2 | router | `app/api/endpoints/benchmark.py:63` | `calculate_benchmark_endpoint` | 149 |
| 3 | router | `app/api/endpoints/contribution.py:129` | `calculate_contribution_endpoint` | 127 |
| 4 | router | `app/api/endpoints/performance.py:715` | `calculate_attribution_endpoint` | 108 |
| 5 | router | `app/api/endpoints/returns_series.py:118` | `get_returns_series` | 92 |
| 6 | router | `app/api/endpoints/runtime_retention_history.py:138` | `run_runtime_retention_cleanup` | 90 |
| 7 | router | `app/api/endpoints/performance.py:544` | `calculate_mwr_endpoint` | 89 |
| 8 | router | `app/api/endpoints/runtime_recoveries.py:27` | `get_runtime_recoveries` | 85 |
