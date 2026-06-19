Report date: 2026-06-19
Branch: `lp-cr-1397-stateful-currency-support`
Command: `python scripts/python_duplicate_code_inventory.py --min-lines 12 --limit 40 --max-groups 10`
Mode: enforced first-party duplicate function-body hotspot regression gate.

## Summary

| Metric | Value |
| --- | ---: |
| Duplicate hotspot groups | 10 |
| Duplicate functions/methods | 20 |
| Files participating in duplication | 12 |
| Total duplicated LOC (reported members) | 426 |
| Max duplicate count in group | 2 |
| Max LOC in duplicate group | 29 |

## Duplicate Hotspots

| Rank | Group count | Body LOC | Instances | Locations |
| ---: | ---: | ---: | ---: | --- |
| 1 | 2 | 29 | 2 | `app/services/runtime_recovery_service.py:144-172`<br>`app/services/runtime_recovery_service.py:187-215` |
| 2 | 2 | 28 | 2 | `app/services/queue_metric_builders.py:361-388`<br>`app/services/queue_metric_builders.py:398-425` |
| 3 | 2 | 25 | 2 | `app/services/inspection/source_quality.py:549-573`<br>`app/services/inspection/source_quality.py:614-638` |
| 4 | 2 | 23 | 2 | `app/services/runtime_work_item_service.py:131-153`<br>`app/services/runtime_work_item_service.py:167-189` |
| 5 | 2 | 22 | 2 | `app/services/stateful_input_service.py:968-989`<br>`app/services/stateful_input_service.py:1124-1145` |
| 6 | 2 | 21 | 2 | `app/models/recovery_drill_history.py:163-183`<br>`app/models/runtime_retention_history.py:244-264` |
| 7 | 2 | 21 | 2 | `app/services/runtime_status_lifecycle.py:263-283`<br>`app/services/runtime_status_lifecycle.py:402-422` |
| 8 | 2 | 17 | 2 | `app/services/inspection/reconciliation.py:228-244`<br>`app/services/inspection/source_economics.py:326-342` |
| 9 | 2 | 15 | 2 | `app/services/recovery_drill_history_service.py:155-169`<br>`app/services/runtime_retention_history_service.py:196-210` |
| 10 | 2 | 12 | 2 | `app/services/queue_metric_builders.py:179-190`<br>`app/services/queue_metric_builders.py:445-456` |
