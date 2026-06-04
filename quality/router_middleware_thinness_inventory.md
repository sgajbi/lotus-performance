## Summary

| Metric | Value |
| --- | ---: |
| Router and middleware oversized function findings | 5 |
| Oversized router functions | 5 |
| Oversized middleware functions | 0 |

## Findings

| Rank | Kind | File | Function | Lines |
| ---: | --- | --- | --- | ---: |
| 1 | router | `app/api/endpoints/performance.py:332` | `calculate_twr_endpoint` | 151 |
| 2 | router | `app/api/endpoints/benchmark.py:63` | `calculate_benchmark_endpoint` | 149 |
| 3 | router | `app/api/endpoints/contribution.py:129` | `calculate_contribution_endpoint` | 127 |
| 4 | router | `app/api/endpoints/performance.py:624` | `calculate_attribution_endpoint` | 108 |
| 5 | router | `app/api/endpoints/returns_series.py:118` | `get_returns_series` | 92 |
