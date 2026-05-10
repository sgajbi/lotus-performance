# RFC-047 Slice 4 - Raw Contribution, Residual, and Smoothing Evidence Contract

| Field | Value |
| --- | --- |
| RFC | RFC-047 - Contribution Carino Methodology Alignment and Evidence Contract |
| Slice | 4 - Raw Contribution, Residual, and Smoothing Evidence Contract |
| Status | Complete for Slice 4 implementation |
| Date | 2026-05-10 |
| Branch | `docs/rfc-contribution-carino-alignment` |

## Purpose

Slice 4 makes the period contribution result explainable from the API response. Before this slice,
support teams could see final contribution totals and broad audit counters, but had to recompute
raw contribution, smoothing residual, and final allocation posture from lineage artifacts. The new
response evidence block makes the raw-versus-smoothed story explicit.

## Implemented Contract

Each resolved period can now include:

`results_by_period.<period>.smoothing_evidence`

Fields:

| Field | Meaning |
| --- | --- |
| `smoothing_method` | Requested method, currently `CARINO` or `NONE`. |
| `status` | Resolved posture: `APPLIED`, `NOT_REQUESTED`, `INVALID_DOMAIN_FALLBACK`, or `NO_CONTRIBUTION_ROWS`. |
| `reason_codes` | Machine-readable support codes such as `CARINO_FACTOR_APPLIED`, `SMOOTHING_NOT_REQUESTED`, `CARINO_INVALID_DAILY_LOG_DOMAIN`, `RAW_CONTRIBUTION_DIFFERS_FROM_LINKED_RETURN`, `SMOOTHED_CONTRIBUTION_RECONCILES`, and `RESIDUAL_ALLOCATED_TO_RECONCILE_PERIOD`. |
| `linked_return` | Portfolio linked return in percentage-point output units. |
| `raw_contribution` | Sum of raw daily contribution before smoothing in percentage-point output units. |
| `smoothed_contribution` | Sum of smoothed daily contribution before residual allocation in percentage-point output units. |
| `final_contribution` | Final period contribution after residual allocation in percentage-point output units. |
| `raw_residual` | Linked return minus raw contribution. |
| `smoothing_residual` | Linked return minus smoothed contribution before residual allocation. |
| `post_allocation_residual` | Linked return minus final contribution. |
| `residual_allocation_applied` | Whether the service allocated period residual back to rows. |
| `residual_allocation_basis` | Allocation basis when residual allocation applied, such as `average_weight` or `selected_average_weight`. |
| `carino_factor_min` / `carino_factor_max` | Factor range when Carino factor evidence is available. |
| `invalid_domain_days` | Count of period days where Carino logarithmic smoothing was not mathematically valid. |

## Implementation

Changes:

1. `app/models/contribution_responses.py`
   - Adds `ContributionSmoothingEvidence`.
   - Adds optional `SinglePeriodContributionResult.smoothing_evidence`.
   - Documents every new field with type, description, and example values.
2. `app/services/contribution_service.py`
   - Adds `_build_contribution_smoothing_evidence(...)`.
   - Emits evidence for both flat and hierarchical contribution paths.
   - Preserves existing final total behavior while exposing pre-allocation raw and smoothed totals.
3. `tests/integration/test_contribution_api.py`
   - Verifies happy-path Carino evidence.
   - Verifies `NONE` smoothing reports `NOT_REQUESTED`.
   - Verifies invalid Carino domain reports `INVALID_DOMAIN_FALLBACK`.
4. Documentation updates:
   - `docs/guides/contribution.md`
   - `docs/methodologies/metrics/metric-contribution-total.md`
   - `docs/technical/contribution-endpoint-certification.md`

## Validation Evidence

Local validation completed on 2026-05-10:

1. `python -m ruff check app/models/contribution_responses.py app/services/contribution_service.py tests/integration/test_contribution_api.py` - passed
2. `python -m ruff format --check app/models/contribution_responses.py app/services/contribution_service.py tests/integration/test_contribution_api.py` - passed
3. `python -m pytest tests/integration/test_contribution_api.py -q` - `35 passed, 1 warning`
4. `python -m pytest tests/unit/docs/test_public_docs_contract.py -q` - `41 passed`
5. `make typecheck` - passed
6. `python scripts/check_monetary_float_usage.py` - passed, `Findings=137, allowlisted=137`
7. `make lint` - passed
8. `python scripts/openapi_quality_gate.py` - passed
9. `python scripts/api_vocabulary_inventory.py --validate-only` - passed

The warning is the pre-existing FastAPI 422 deprecation noted in Slice 2.

## Slice 4 Review

Slice 4 is complete for the current response evidence layer:

1. raw, smoothed, final, and linked contribution figures are visible without recomputation;
2. raw, smoothing, and post-allocation residuals are distinct;
3. invalid-domain and no-smoothing states have explicit status and reason codes;
4. Carino factor range is visible when factors exist;
5. downstream consumers can preserve source-owned evidence in Slice 7 rather than inventing
   smoothing quality locally.

Remaining work:

1. Slice 5 will review source economics and upstream realization.
2. Slice 7 will propagate the new evidence through Gateway and Workbench consumers.
