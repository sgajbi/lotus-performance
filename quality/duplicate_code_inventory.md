Report date: 2026-06-19
Branch: `lp-cr-1403-runtime-lifecycle-degradation`
Command: `python scripts/python_duplicate_code_inventory.py --min-lines 12 --limit 40 --max-groups 4`
Mode: enforced first-party duplicate function-body hotspot regression gate.

## Summary

| Metric | Value |
| --- | ---: |
| Duplicate hotspot groups | 4 |
| Duplicate functions/methods | 8 |
| Files participating in duplication | 7 |
| Total duplicated LOC (reported members) | 130 |
| Max duplicate count in group | 2 |
| Max LOC in duplicate group | 21 |

## Duplicate Hotspots

| Rank | Group count | Body LOC | Instances | Locations |
| ---: | ---: | ---: | ---: | --- |
| 1 | 2 | 21 | 2 | `app/models/recovery_drill_history.py:163-183`<br>`app/models/runtime_retention_history.py:244-264` |
| 2 | 2 | 17 | 2 | `app/services/inspection/reconciliation.py:228-244`<br>`app/services/inspection/source_economics.py:326-342` |
| 3 | 2 | 15 | 2 | `app/services/recovery_drill_history_service.py:155-169`<br>`app/services/runtime_retention_history_service.py:196-210` |
| 4 | 2 | 12 | 2 | `app/services/queue_metric_builders.py:207-218`<br>`app/services/queue_metric_builders.py:469-480` |
