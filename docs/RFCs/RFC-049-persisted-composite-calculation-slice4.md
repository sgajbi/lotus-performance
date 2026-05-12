# RFC 049 Slice 4 - Persisted Composite Calculation Foundation

Status: completed

Branch: `draft/rfc-049-composite-performance-alignment`

PR: `sgajbi/lotus-performance#162`

Completed: 2026-05-12

## Purpose

Slice 4 adds the first composite calculation implementation over persisted member-return facts. It
does not add public endpoints yet. The objective is to prove the core calculation contract before
exposing runtime, operator, Gateway, or Workbench surfaces.

## Implementation

| Area | Files | Outcome |
| --- | --- | --- |
| Composite engine | `engine/composites.py` | Added asset-weighted composite TWR calculation over persisted `CompositeMemberReturnFact` records. |
| Composite calculation service | `app/services/composite_calculation_service.py` | Added service boundary that reads persisted facts from `CompositeMetadataStore` and runs the composite engine. |
| Engine tests | `tests/unit/engine/test_composites.py` | Proves asset weighting, geometric linking, member contribution weights, degraded member exclusion, no-ready-fact blocking, and nonpositive beginning-asset blocking. |
| Service tests | `tests/unit/services/test_composite_calculation_service.py` | Proves definition lookup and calculation from persisted facts. |

## Domain Decisions

1. Composite returns are calculated from persisted member-return facts only.
2. Composite return output uses decimal ratios, not percentage-point units, inside the engine. Public
   API slices can convert presentation units explicitly.
3. The first supported method is beginning-asset weighted member return aggregation followed by
   geometric linking across periods.
4. Degraded or blocked member-return facts are excluded from the period calculation and surfaced as
   degraded reason-code evidence; a period with no ready facts is blocked.
5. Periods with nonpositive composite beginning assets are blocked rather than coerced.
6. Equal-weight member-return dispersion is calculated when at least two ready member facts exist.

## Current Capability Boundary

This slice adds internal calculation capability only:

1. no public composite API exists yet;
2. no batch worker or recalculation API exists yet;
3. no composite inspector/export model exists yet;
4. no supported composite feature claim is promoted yet;
5. downstream Gateway and Workbench changes wait until public contract slices exist.

## Validation

```powershell
python -m ruff check engine\composites.py app\services\composite_calculation_service.py tests\unit\engine\test_composites.py tests\unit\services\test_composite_calculation_service.py
python -m pytest tests\unit\engine\test_composites.py tests\unit\services\test_composite_calculation_service.py tests\unit\models\test_composite_models.py tests\unit\services\test_composite_metadata_store.py tests\unit\services\test_durable_metadata_bootstrap.py -q
git diff --check
```

Result:

- Ruff targeted check -> passed.
- Composite engine/service/model/store/bootstrap tests -> 14 passed.
- `git diff --check` -> passed.
