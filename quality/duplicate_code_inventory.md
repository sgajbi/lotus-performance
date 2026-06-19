Report date: 2026-06-19
Branch: `lp-cr-1404-inspection-stateful-fetch`
Command: `python scripts/python_duplicate_code_inventory.py --min-lines 12 --limit 40 --max-groups 3`
Mode: enforced first-party duplicate function-body hotspot regression gate.

## Summary

| Metric | Value |
| --- | ---: |
| Duplicate hotspot groups | 3 |
| Duplicate functions/methods | 6 |
| Files participating in duplication | 5 |
| Total duplicated LOC (reported members) | 96 |
| Max duplicate count in group | 2 |
| Max LOC in duplicate group | 21 |

## Duplicate Hotspots

| Rank | Group count | Body LOC | Instances | Locations |
| ---: | ---: | ---: | ---: | --- |
| 1 | 2 | 21 | 2 | `app/models/recovery_drill_history.py:163-183`<br>`app/models/runtime_retention_history.py:244-264` |
| 2 | 2 | 15 | 2 | `app/services/recovery_drill_history_service.py:155-169`<br>`app/services/runtime_retention_history_service.py:196-210` |
| 3 | 2 | 12 | 2 | `app/services/queue_metric_builders.py:207-218`<br>`app/services/queue_metric_builders.py:469-480` |
