# Using the Engine as a Standalone Library

The analytics engine can still be used directly from Python, but the standalone usage path should
mirror the implemented engine API rather than older pre-refactor examples.

## Supported pattern

For TWR-style standalone usage:

1. build a pandas `DataFrame` with canonical engine columns
2. construct `engine.config.EngineConfig`
3. call `engine.compute.run_calculations(df, config)`
4. consume the returned `(results_df, diagnostics)` tuple

## Minimal example

```python
from datetime import date

import pandas as pd

from common.enums import PeriodType
from engine.config import EngineConfig
from engine.compute import run_calculations
from engine.schema import PortfolioColumns

input_df = pd.DataFrame(
    [
        {
            PortfolioColumns.DAY.value: 1,
            PortfolioColumns.PERF_DATE.value: date(2025, 1, 1),
            PortfolioColumns.BEGIN_MV.value: 100000.0,
            PortfolioColumns.END_MV.value: 101000.0,
            PortfolioColumns.BOD_CF.value: 0.0,
            PortfolioColumns.EOD_CF.value: 0.0,
            PortfolioColumns.MGMT_FEES.value: 0.0,
        },
        {
            PortfolioColumns.DAY.value: 2,
            PortfolioColumns.PERF_DATE.value: date(2025, 1, 2),
            PortfolioColumns.BEGIN_MV.value: 101000.0,
            PortfolioColumns.END_MV.value: 103000.0,
            PortfolioColumns.BOD_CF.value: 1000.0,
            PortfolioColumns.EOD_CF.value: 0.0,
            PortfolioColumns.MGMT_FEES.value: -15.0,
        },
    ]
)

config = EngineConfig(
    performance_start_date=date(2024, 12, 31),
    report_start_date=date(2025, 1, 1),
    report_end_date=date(2025, 1, 2),
    metric_basis="NET",
    period_type=PeriodType.YTD,
)

results_df, diagnostics = run_calculations(input_df, config)

print(results_df.head())
print(diagnostics)
```

## Notes

- The standalone engine path is a technical usage pattern, not the canonical public API contract.
- Public API users should prefer `/docs` and the request models under `app/models/`.
- For current production runtime behavior, use the API and runtime architecture docs rather than
  assuming the standalone engine path includes executor, lineage, or durable execution features.
