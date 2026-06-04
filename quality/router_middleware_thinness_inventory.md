## Summary

| Metric | Value |
| --- | ---: |
| Router and middleware oversized function findings | 9 |
| Oversized router functions | 9 |
| Oversized middleware functions | 0 |

## Findings

| Rank | Kind | File | Function | Lines |
| ---: | --- | --- | --- | ---: |
| 1 | router | `app/api/endpoints/integration_capabilities.py:483` | `get_integration_capabilities` | 376 |
| 2 | router | `app/api/endpoints/performance.py:337` | `calculate_twr_endpoint` | 151 |
| 3 | router | `app/api/endpoints/benchmark.py:63` | `calculate_benchmark_endpoint` | 149 |
| 4 | router | `app/api/endpoints/contribution.py:129` | `calculate_contribution_endpoint` | 127 |
| 5 | router | `app/api/endpoints/performance.py:715` | `calculate_attribution_endpoint` | 108 |
| 6 | router | `app/api/endpoints/returns_series.py:118` | `get_returns_series` | 92 |
| 7 | router | `app/api/endpoints/runtime_retention_history.py:138` | `run_runtime_retention_cleanup` | 90 |
| 8 | router | `app/api/endpoints/performance.py:544` | `calculate_mwr_endpoint` | 89 |
| 9 | router | `app/api/endpoints/runtime_recoveries.py:27` | `get_runtime_recoveries` | 85 |
