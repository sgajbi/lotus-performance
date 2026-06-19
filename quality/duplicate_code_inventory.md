Report date: 2026-06-19
Branch: `lp-cr-1390-security-duplicate-ci-gates`
Command: `python scripts/python_duplicate_code_inventory.py --min-lines 12 --limit 40 --max-groups 15`
Mode: enforced first-party duplicate function-body hotspot regression gate.

## Summary

| Metric | Value |
| --- | ---: |
| Duplicate hotspot groups | 15 |
| Duplicate functions/methods | 32 |
| Files participating in duplication | 14 |
| Total duplicated LOC (reported members) | 792 |
| Max duplicate count in group | 4 |
| Max LOC in duplicate group | 39 |

## Duplicate Hotspots

| Rank | Group count | Body LOC | Instances | Locations |
| ---: | ---: | ---: | ---: | --- |
| 1 | 4 | 22 | 4 | `app/services/inspection/reconciliation.py:249-270`<br>`app/services/inspection/reconciliation.py:277-298`<br>`app/services/inspection/reconciliation.py:305-328`<br>`app/services/inspection/reconciliation.py:363-386` |
| 2 | 2 | 39 | 2 | `app/services/stateful_input_service.py:674-712`<br>`app/services/stateful_input_service.py:774-812` |
| 3 | 2 | 36 | 2 | `app/services/stateful_input_service.py:726-761`<br>`app/services/stateful_input_service.py:826-861` |
| 4 | 2 | 34 | 2 | `app/services/stateful_input_service.py:183-216`<br>`app/services/stateful_input_service.py:320-353` |
| 5 | 2 | 30 | 2 | `app/services/stateful_attribution_input_service.py:1156-1185`<br>`app/services/stateful_contribution_input_service.py:316-345` |
| 6 | 2 | 29 | 2 | `app/services/runtime_recovery_service.py:144-172`<br>`app/services/runtime_recovery_service.py:187-215` |
| 7 | 2 | 28 | 2 | `app/services/queue_metric_builders.py:361-388`<br>`app/services/queue_metric_builders.py:398-425` |
| 8 | 2 | 25 | 2 | `app/services/inspection/source_quality.py:549-573`<br>`app/services/inspection/source_quality.py:614-638` |
| 9 | 2 | 23 | 2 | `app/services/runtime_work_item_service.py:131-153`<br>`app/services/runtime_work_item_service.py:167-189` |
| 10 | 2 | 22 | 2 | `app/services/stateful_input_service.py:954-975`<br>`app/services/stateful_input_service.py:1110-1131` |
| 11 | 2 | 21 | 2 | `app/models/recovery_drill_history.py:163-183`<br>`app/models/runtime_retention_history.py:244-264` |
| 12 | 2 | 21 | 2 | `app/services/runtime_status_lifecycle.py:263-283`<br>`app/services/runtime_status_lifecycle.py:402-422` |
| 13 | 2 | 17 | 2 | `app/services/inspection/reconciliation.py:97-113`<br>`app/services/inspection/source_economics.py:326-342` |
| 14 | 2 | 15 | 2 | `app/services/recovery_drill_history_service.py:155-169`<br>`app/services/runtime_retention_history_service.py:196-210` |
| 15 | 2 | 12 | 2 | `app/services/queue_metric_builders.py:179-190`<br>`app/services/queue_metric_builders.py:445-456` |
