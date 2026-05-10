# RFC 048 Slice 3 - Attribution Methodology and Engine Contract Evidence

| Field | Value |
| --- | --- |
| RFC | RFC-048 - Attribution Industry Methodology Alignment and Evidence Contract |
| Slice | 3 - Attribution Methodology and Engine Contract |
| Status | Complete |
| Date | 2026-05-11 |
| Branch | `feat/rfc-048-attribution-industry-alignment` |

## Purpose

Slice 3 promotes attribution from a numeric-only calculation result to a supportable methodology
contract. The slice keeps existing Brinson-Fachler, Brinson-Hood-Beebower, hierarchy, currency, and
top-down linking formulas intact while adding controlled status, reason-code, residual-materiality,
and support-safe evidence outputs.

## Implementation Summary

| Area | Implementation |
| --- | --- |
| Controlled period status | `SinglePeriodAttributionResult` now exposes `status`, `reason_codes`, and detailed `reasons` using bounded vocabulary. |
| Residual materiality | `Reconciliation` now includes `residual_materiality` with warning/material thresholds, classification, absolute residual, and operations treatment. |
| Supportability policy | Added `engine/attribution_supportability.py` so status, reason-code, and residual policy are isolated from core formula code. |
| Alignment evidence | Attribution alignment now preserves portfolio/benchmark observation presence and missing benchmark return evidence before numeric fill. |
| Edge semantics | Portfolio-only, benchmark-only, unclassified, missing benchmark return, negative weight, zero exposure, unavailable currency evidence, linking scaling skip, residual watch, and material residual are emitted through controlled reason codes. |
| Daily evidence | Period aggregation emits `attribution_supportability_evidence.csv` into lineage with support-safe flags and no raw account, client, trace, correlation, request, or payload identifiers. |
| Request semantics | `BenchmarkObservation.return_base` now accepts `null` to represent unavailable benchmark return evidence instead of rejecting the request before supportability can classify the condition. |
| API vocabulary governance | `scripts/api_vocabulary_inventory.py` now preserves nullable scalar types instead of cataloging them as generic objects. |
| Monetary-float governance | Regenerated `docs/standards/monetary-float-allowlist.json` through the governed guard after approved percentage-return float findings moved line numbers. |

## Methodology Decisions

1. Existing Brinson-Fachler and Brinson-Hood-Beebower formulas remain unchanged.
2. Existing top-down linking behavior remains unchanged; Slice 3 adds `linking_scaling_skipped`
   evidence when arithmetic active return is zero and scaling cannot be applied.
3. Interaction folding remains rejected for RFC 048: allocation, selection, and interaction remain
   explicit source-authored fields so downstream consumers do not infer or fold effects locally.
4. Residual classification is intentionally bounded:
   - `immaterial`: absolute residual below `0.001` percentage points, `no_action`;
   - `watch`: absolute residual from `0.001` to below `0.01` percentage points, `review`;
   - `material`: absolute residual at or above `0.01` percentage points, `investigate`.

## Tests Added Or Strengthened

| Test | Coverage |
| --- | --- |
| `test_residual_materiality_policy_classifies_review_and_material_breaks` | Residual policy thresholds and operations treatment. |
| `test_attribution_supportability_evidence_flags_alignment_and_source_quality_edges` | Portfolio-only, benchmark-only, unclassified, missing benchmark return, negative weights, and lineage evidence flags. |
| `test_attribution_supportability_evidence_flags_currency_and_linking_gaps` | Currency attribution unavailable and linking scaling skip reason codes. |
| `tests/unit/engine/test_attribution_supportability.py` | Direct supportability-policy coverage for empty evidence, nullable fallback, zero exposure, residual watch, and material residual warning paths. |
| `test_single_period_attribution_result_schema_documents_status_reason_and_materiality_fields` | Response schema descriptions for status, reasons, evidence, and residual materiality. |
| `test_attribution_endpoint_emits_controlled_status_reason_and_supportability_evidence` | End-to-end API payload exposes source-owned status/reasons/evidence and lineage artifact. |
| `test_api_vocabulary_inventory_preserves_nullable_scalar_type` | API vocabulary generator keeps nullable numeric fields typed as numeric vocabulary rather than generic object vocabulary. |
| Existing attribution happy-path tests | Prove unchanged Brinson totals, group context, currency attribution, hierarchy, async, and stateful behavior still pass. |

## Validation Evidence

Local validation completed on 2026-05-11:

1. `python -m ruff format app\models\attribution_requests.py app\models\attribution_responses.py engine\attribution.py engine\attribution_supportability.py tests\unit\engine\test_attribution.py tests\unit\models\test_attribution_models.py tests\integration\test_attribution_api.py` - passed
2. `python -m ruff check app\models\attribution_requests.py app\models\attribution_responses.py engine\attribution.py engine\attribution_supportability.py tests\unit\engine\test_attribution.py tests\unit\models\test_attribution_models.py tests\integration\test_attribution_api.py` - passed
3. `python -m pytest tests\unit\engine\test_attribution.py tests\unit\models\test_attribution_models.py tests\integration\test_attribution_api.py -q` - `67 passed`
4. `python -m pytest tests\unit\engine\test_attribution.py tests\unit\models\test_attribution_models.py tests\unit\scripts\test_api_vocabulary_inventory.py tests\integration\test_attribution_api.py tests\unit\docs\test_public_docs_contract.py -q` - `110 passed`
5. `python scripts\openapi_quality_gate.py` - passed
6. `python scripts\api_vocabulary_inventory.py --output docs\standards\api-vocabulary\lotus-performance-api-vocabulary.v1.json` - regenerated the repo-owned vocabulary inventory for new attribution fields
7. `python scripts\api_vocabulary_inventory.py --validate-only` - passed
8. `make api-vocabulary-gate` - passed
9. `make no-alias-gate` - passed
10. `git diff --check` - passed
11. `python scripts\check_monetary_float_usage.py --update-allowlist` - regenerated approved baseline after line-sensitive attribution percentage-return findings moved
12. `python scripts\check_monetary_float_usage.py` - passed, `Findings=137, allowlisted=137`
13. `python -m pytest tests\unit\engine\test_attribution.py tests\unit\engine\test_attribution_supportability.py --cov=engine.attribution_supportability --cov-report=term-missing -q` - passed with `100%` coverage for `engine/attribution_supportability.py`
14. `make check` - passed, including ruff, format check, monetary-float guard, no-alias guard, mypy, OpenAPI quality gate, API vocabulary gate, domain data-product contract validation, and `1225` unit tests

## Slice 3 Review

The implementation is intentionally additive at the response layer and conservative at the formula
layer. It does not move attribution conclusions upstream into `lotus-core`, does not add unsupported
factor, derivative, sleeve, or composite calculations, and does not require downstream consumers to
reconstruct totals or statuses.

The main remaining RFC work is downstream contract realization, OpenAPI certification, data-product
promotion, stateful source alignment review, documentation productization, live proof, and final
hardening.
