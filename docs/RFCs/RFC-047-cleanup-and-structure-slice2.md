# RFC-047 Slice 2 - Cleanup and Contribution Module Structure Evidence

| Field | Value |
| --- | --- |
| RFC | RFC-047 - Contribution Carino Methodology Alignment and Evidence Contract |
| Slice | 2 - Cleanup and Contribution Module Structure |
| Status | Complete for Slice 2 implementation |
| Date | 2026-05-10 |
| Branch | `docs/rfc-contribution-carino-alignment` |
| Commit | Slice 2 commit in this branch |

## Purpose

Slice 2 prepares contribution for the methodology and evidence-contract slices without changing
business behavior. The main cleanup need found in the baseline was that `engine/contribution.py`
mixed three responsibilities in one module:

1. preparing portfolio and position engine frames,
2. calculating daily raw contributions,
3. applying Carino smoothing mechanics.

Keeping Carino mechanics embedded in the daily contribution function would make Slice 3 formula
correction and deterministic proof harder to review. The slice therefore isolates smoothing into a
focused module while preserving the current RFC-047 baseline behavior.

## Implemented Cleanup

| Area | Action | Outcome |
| --- | --- | --- |
| Contribution smoothing structure | Added `engine/contribution_smoothing.py`. | Carino factor calculation, domain validation, factor series generation, and smoothing application now live in a dedicated module. |
| Contribution engine readability | Updated `engine/contribution.py` to call `apply_contribution_smoothing(...)`. | Daily raw contribution and smoothing responsibilities are no longer interleaved in the same block. |
| Compatibility for existing tests | Re-exported existing private helper names from `engine/contribution.py`. | Existing tests and any local internal imports keep working while the implementation gains a clearer module boundary. |
| Behavior stability | Preserved the current Carino baseline formula and residual behavior. | Slice 3 remains the explicit methodology-correction slice; Slice 2 does not hide a formula change inside cleanup. |

## Review Decisions

The following cleanup items were reviewed and deliberately left for later RFC-047 slices:

1. `app/services/contribution_service.py` remains large because its period slicing, reset-aware
   average-weight shadow evidence, async execution, supportability, diagnostics, and audit behavior
   are tightly coupled to existing response contracts. Refactoring it before the evidence contract
   lands would create churn without reducing current correctness risk.
2. Documentation and wiki structure are not changed in Slice 2. Durable audience-facing
   contribution material will be rewritten after the actual formula, evidence, data-product, and
   downstream behavior is implemented, so the wiki does not get ahead of implementation truth.
3. The existing deprecated FastAPI `HTTP_422_UNPROCESSABLE_ENTITY` warning is a broader service
   hygiene issue across several services. It is recorded as observed hygiene debt but not changed
   in this slice because it is not contribution-structure-specific and should be addressed in a
   targeted platform/API error-code cleanup.

## Validation Evidence

Local validation completed on 2026-05-10:

1. `python -m ruff check engine/contribution.py engine/contribution_smoothing.py tests/unit/engine/test_contribution.py` - passed
2. `python -m ruff format --check engine/contribution.py engine/contribution_smoothing.py` - passed
3. `python -m pytest tests/unit/engine/test_contribution.py -q` - `13 passed`
4. `python -m pytest tests/integration/test_contribution_api.py -q` - `34 passed, 1 warning`
5. `git diff --check` - passed

The warning is the existing FastAPI 422 deprecation described above and is not introduced by this
slice.

## Slice 2 Review

The change materially improves maintainability without changing contribution output:

1. future Carino formula changes can be made in one focused module;
2. deterministic factor tests can target smoothing directly;
3. daily raw contribution calculation remains separate from smoothing application;
4. no dead code or duplicate docs were added;
5. no wiki/source documentation claims were promoted ahead of implementation proof.

Slice 2 is complete and ready for the methodology correction slice.
