# RFC-049 Slice 10 - QA Regression Pack

Status: implemented and locally validated

Date: 2026-05-12

Branch: `draft/rfc-049-composite-performance-alignment`

## Purpose

Slice 10 converts the composite source-pack QA expectations into durable Lotus regression coverage.
The pack focuses on implementation-backed behavior in the current RFC-049 boundary:

1. persisted member-return facts are the calculation input;
2. asset-weighted composite TWR is the supported calculation method;
3. member contribution, dispersion, lineage, restatement, status, and reason-code evidence are part
   of the contract;
4. unsupported advanced scopes are explicit rather than silently simulated in tests.

## Added Regression Coverage

### Engine and Math

File: `tests/unit/engine/test_composites.py`

Added or strengthened coverage:

1. empty persisted fact set returns `BLOCKED` with `no_member_return_facts` and never returns a fake
   zero return;
2. single-member composite return equals the member return and does not emit dispersion;
3. member beginning-asset weights sum to 1.000000000000 and member contributions reconcile to the
   composite period return;
4. blocked inactive-gap periods do not erase later historical periods and do not fabricate returns;
5. existing coverage already proved asset-weighted return, monthly linking, degraded member facts,
   no ready member facts, nonpositive beginning assets, mixed return views, and mixed reporting
   currencies.

### Persisted Store and Restatement

File: `tests/unit/services/test_composite_calculation_service.py`

Added coverage:

1. calculation reads the durable metadata store rather than ad hoc request payloads;
2. a restated member-return fact replaces the earlier fact for the same composite, portfolio, and
   period;
3. the calculation uses the restated return, beginning assets, calculation id, source fingerprint,
   and restatement version.

Existing coverage already proved unknown composite definition handling and persisted fact reads.

### Model and Governance Validation

File: `tests/unit/models/test_composite_models.py`

Added coverage:

1. reversed membership effective-date windows are rejected;
2. negative beginning assets are rejected at the fact boundary;
3. existing coverage already proved invalid composite lifecycle windows, non-included membership
   reason requirements, degraded fact reason-code requirements, and ready fact validation.

### API Behavior

File: `tests/integration/test_composites_api.py`

Added coverage:

1. empty persisted fact windows return structured `NO_MEMBER_RETURN_FACTS` with HTTP 422;
2. degraded member facts produce a degraded composite response with bounded reason codes and
   excluded-member count;
3. invalid request windows are rejected before calculation;
4. existing coverage already proved persisted-fact calculation, unknown composite 404 behavior, and
   classified inspection artifacts.

The endpoint implementation now uses `core.errors.HTTP_422_UNPROCESSABLE` so FastAPI/Starlette
version drift does not emit deprecation warnings during the regression pack.

## Edge-Case Mapping

| RFC edge case | Current treatment |
| --- | --- |
| Basic asset-weighted return | Covered by engine and API tests. |
| Member contribution to composite return | Covered by weight/contribution reconciliation tests and API response tests. |
| Monthly linking | Covered by existing multi-period engine test. |
| No eligible portfolios | Covered as `no_ready_member_return_facts` and `no_member_return_facts`; membership-policy resolution stays source-owned upstream. |
| One eligible portfolio | Covered by single-member engine test. |
| Terminated portfolio remains historically | Covered by persisted historical facts remaining calculable; final membership-policy source ownership is not duplicated in the calculator. |
| Survivorship-bias prevention | Covered by persisted facts and inactive-gap tests; current membership is not used by the calculator. |
| Grace period | Classified as source-policy input to persisted facts, not an engine calculation rule. |
| Minimum asset threshold | Classified as source-policy input to persisted facts; negative assets are rejected and zero total beginning assets are blocked. |
| Eligible member missing return | Covered by degraded/blocked persisted fact status and reason codes. |
| Invalid member assets | Covered by negative asset model validation and nonpositive composite beginning asset blocking. |
| Negative assets | Covered by model validation. |
| Mixed return view | Covered by existing engine blocker. |
| Missing FX | Unsupported in current scope; mixed reporting currencies are blocked until source-owned FX conversion evidence is implemented. |
| Benchmark active return | Unsupported in current composite TWR scope; benchmark-aware composite analytics remain gated. |
| Benchmark missing | Unsupported in current composite TWR scope and not represented as a supported output. |
| Dispersion | Covered by existing multi-member dispersion behavior and single-member no-dispersion test. |
| One-member dispersion | Covered by single-member no-dispersion test. |
| Inactive gap | Covered by blocked-period/later-history engine test. |
| Duplicate membership | Classified as source-policy validation in membership authority; calculator consumes already-materialized facts. |
| Restated member return | Covered by persisted restatement test. |
| Restated member assets | Covered by persisted restatement test using changed beginning assets. |
| Property-style no-member, missing-member, and weight invariants | Covered by deterministic invariant tests without introducing a new property-test dependency. |
| API status, reason, and error behavior | Covered by integration tests for 200, 404, 422, degraded, and invalid-window behavior. |

## Review Outcome

The added tests are deliberately not broad count inflation. They strengthen the highest-risk
implementation boundaries:

1. no fake zero returns;
2. no hidden request-time calculation payloads;
3. no current-membership survivorship shortcut inside the calculator;
4. no silent restatement overwrite without visible lineage;
5. no mixed fee view or currency result;
6. no warning noise in the clean API regression path.

No production code refactor was required beyond replacing the deprecated 422 constant at the
composite API boundary.

## Validation Evidence

Local validation passed:

1. `python -m ruff check tests\unit\engine\test_composites.py tests\unit\models\test_composite_models.py tests\unit\services\test_composite_calculation_service.py tests\integration\test_composites_api.py`
2. `python -m pytest tests\unit\engine\test_composites.py tests\unit\models\test_composite_models.py tests\unit\services\test_composite_calculation_service.py tests\unit\services\test_composite_inspection_service.py tests\integration\test_composites_api.py -q` - `30 passed`
3. `python -m pytest tests\integration\test_composites_api.py -q` - `6 passed`

## Slice 10 Conclusion

Slice 10 is complete. RFC-049 now has a maintainable composite QA regression pack grounded in the
actual persisted-fact implementation, with explicit unsupported decisions where the source pack
describes behavior outside the current approved composite TWR boundary.
