# Lotus Performance Router And Middleware Thinness Inventory

Report date: 2026-06-19
Branch: `lp-cr-1388-source-economics-raw-sampling`
Mode: enforced router/middleware thinness inventory; zero findings are blocked by CI.

## Purpose

This report captures oversized router and middleware functions so HTTP adapter and middleware code
stays thin. The current threshold is enforced as a regression gate because the measured inventory is
clean.

## Command

```powershell
python scripts/python_router_middleware_thinness_inventory.py --threshold 80 --limit 50 --max-findings 0
```

## Summary

| Metric | Value |
| --- | ---: |
| Router and middleware oversized function findings | 0 |
| Oversized router functions | 0 |
| Oversized middleware functions | 0 |

## Findings

| Rank | Kind | File | Function | Lines |
| ---: | --- | --- | --- | ---: |

## Gate Posture

`make quality-router-thinness-gate` enforces `--threshold 80 --max-findings 0` in local checks,
Feature Lane, PR Merge Gate, and Main Releasability.
