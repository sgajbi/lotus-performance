Report date: 2026-06-19
Branch: `lp-cr-1406-history-snapshot-builders`
Command: `python scripts/python_duplicate_code_inventory.py --min-lines 12 --limit 40 --max-groups 1`
Mode: enforced first-party duplicate function-body hotspot regression gate.

## Summary

| Metric | Value |
| --- | ---: |
| Duplicate hotspot groups | 1 |
| Duplicate functions/methods | 2 |
| Files participating in duplication | 1 |
| Total duplicated LOC (reported members) | 24 |
| Max duplicate count in group | 2 |
| Max LOC in duplicate group | 12 |

## Duplicate Hotspots

| Rank | Group count | Body LOC | Instances | Locations |
| ---: | ---: | ---: | ---: | --- |
| 1 | 2 | 12 | 2 | `app/services/queue_metric_builders.py:207-218`<br>`app/services/queue_metric_builders.py:469-480` |
