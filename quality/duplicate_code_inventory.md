Report date: 2026-06-19
Branch: `lp-cr-1401-runtime-work-items`
Command: `python scripts/python_duplicate_code_inventory.py --min-lines 12 --limit 40 --max-groups 6`
Mode: enforced first-party duplicate function-body hotspot regression gate.

## Summary

| Metric | Value |
| --- | ---: |
| Duplicate hotspot groups | 6 |
| Duplicate functions/methods | 12 |
| Files participating in duplication | 9 |
| Total duplicated LOC (reported members) | 216 |
| Max duplicate count in group | 2 |
| Max LOC in duplicate group | 22 |

## Duplicate Hotspots

| Rank | Group count | Body LOC | Instances | Locations |
| ---: | ---: | ---: | ---: | --- |
| 1 | 2 | 22 | 2 | `app/services/stateful_input_service.py:968-989`<br>`app/services/stateful_input_service.py:1124-1145` |
| 2 | 2 | 21 | 2 | `app/models/recovery_drill_history.py:163-183`<br>`app/models/runtime_retention_history.py:244-264` |
| 3 | 2 | 21 | 2 | `app/services/runtime_status_lifecycle.py:263-283`<br>`app/services/runtime_status_lifecycle.py:402-422` |
| 4 | 2 | 17 | 2 | `app/services/inspection/reconciliation.py:228-244`<br>`app/services/inspection/source_economics.py:326-342` |
| 5 | 2 | 15 | 2 | `app/services/recovery_drill_history_service.py:155-169`<br>`app/services/runtime_retention_history_service.py:196-210` |
| 6 | 2 | 12 | 2 | `app/services/queue_metric_builders.py:207-218`<br>`app/services/queue_metric_builders.py:469-480` |
