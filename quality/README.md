# Quality Evidence Pack

## Purpose

This pack contains curated and generated quality evidence for the enterprise backend refactor,
CI gates, scorecards, and release posture.

## Audience

- engineering reviewers checking measurable improvement,
- operators and QA teams checking release evidence,
- agents deciding which quality signal to preserve or improve next.

## Reading Order

1. `quality_scorecard.md`
2. `refactor_health_report.md`
3. `ci_quality_gates.md`
4. the focused inventory for the changed area

## Evidence Types

| Evidence type | Source of truth | Maintenance |
| --- | --- | --- |
| Curated scorecards | `quality_scorecard.md`, `refactor_health_report.md` | Update when a slice changes quality posture. |
| Blocking gate maps | `ci_quality_gates.md` | Update when Make or CI enforcement changes. |
| Report-only inventories | Files such as `complexity_inventory.md` and `coverage_inventory.md` | Refresh with the repo-native command named in the report. |

## Maintenance Notes

- Do not turn report-only evidence into a blocking claim without a deterministic gate and tests.
- Keep before/after numbers factual; do not use scorecards for aspirational readiness language.
- Prefer repo-native targets such as `make quality-baseline`,
  `make quality-observability-readiness-gate`, and `make branch-coverage-baseline`.
