# RFC 048 Slice 8 - QA Regression Pack

Date: 2026-05-11

Branch: `feat/rfc-048-attribution-industry-alignment`

## Scope

Slice 8 converted the supplied attribution QA regression pack into implementation-backed Lotus
coverage. The slice focused on high-value regression risks that are in the approved RFC 048 product
scope and explicitly avoided adding superficial tests for unsupported capabilities.

## Adopted QA Cases

| Source QA case | Lotus treatment | Evidence |
| --- | --- | --- |
| Case A: basic Brinson-Fachler reconciliation | Adopted as deterministic unit coverage using the industry pack values and Lotus decimal/percentage output boundary. | `test_calculate_single_period_brinson_fachler_matches_industry_regression_pack_case_a` |
| Active contribution reconciliation | Adopted inside the Case A test as an internal calculation invariant because the current API does not expose active-contribution rows as first-class response fields. | Same test; validates portfolio contribution, benchmark contribution, and active contribution reconcile before effect totals. |
| Portfolio-only and benchmark-only segment union | Adopted as order-independent engine coverage proving the union of segment keys is retained and does not depend on source row order. | `test_attribution_segment_union_and_order_independence_for_portfolio_and_benchmark_only_groups` |
| Missing classification and negative weights | Already covered by Slice 3 supportability evidence tests; retained as implementation-backed coverage rather than duplicated. | `test_attribution_supportability_evidence_flags_alignment_and_source_quality_edges` |
| Material residual | Already covered at supportability-policy level. | `test_residual_materiality_policy_classifies_review_and_material_breaks`; `test_attribution_supportability_warns_for_material_residual_without_coverage_gap` |
| Invalid multi-period return chain | Adopted as a new engine behavior and regression test. Linked attribution now surfaces `linking_invalid_return_chain` instead of silently treating an invalid chain as clean linked attribution. | `test_attribution_linking_flags_invalid_return_chain_from_regression_pack` |
| Currency-attribution gaps and skipped linking | Existing test retained as coverage for degraded linking and unavailable currency attribution evidence. | `test_attribution_supportability_evidence_flags_currency_and_linking_gaps` |

## Explicit Non-Goals Or Source-Limited Cases

| Source QA case | Decision |
| --- | --- |
| Interaction folded into selection | Not implemented in RFC 048. The engine preserves allocation, selection, and interaction separately for auditability. Folding can be a downstream display choice only after a future approved contract change. |
| Derivative low-market-value/high-P&L attribution | Source-limited. RFC 048 does not claim derivative exposure attribution or derivative-specific P&L buckets. |
| Gross/net mismatch, fee effect, and tax effect separation | Source-limited. Current request and output label the metric basis, but fee/tax attribution is not claimed. |
| Group internal transfer elimination and child benchmark aggregation | Out of scope. RFC 048 remains portfolio-level attribution; group/composite calculation is not claimed. |
| Restatement cache invalidation | Out of scope for this calculation-methodology slice; runtime execution and lineage stores remain covered by existing execution tests. |

## Implementation

The implementation added one code-level hardening improvement from the QA pack:

1. When linked attribution is requested and any portfolio or benchmark period return is less than or
   equal to `-100%`, `aggregate_attribution_results` now marks
   `supportability_evidence.linking_status` as `invalid_return_chain`.
2. The period emits controlled reason code `linking_invalid_return_chain`.
3. The period status becomes `partial`, preserving single-period evidence while blocking a clean
   linked-attribution claim.
4. The API model now includes `linking_invalid_return_chain` and `invalid_return_chain` as governed
   response literals.
5. `docs/standards/monetary-float-allowlist.json` was refreshed because the response literal
   addition shifted existing allowlisted percentage-weight response fields; no new monetary float
   usage was introduced.
6. `docs/guides/attribution.md` documents the posture for developers, operations, and downstream
   consumers.

This is intentionally conservative. It does not invent a smoothing method for invalid return
chains, and it does not hide the issue behind a residual-only signal.

## Validation Evidence

```powershell
python -m ruff format app\models\attribution_responses.py engine\attribution.py engine\attribution_supportability.py tests\unit\engine\test_attribution.py
# 4 files left unchanged.

python -m pytest tests\unit\engine\test_attribution.py tests\unit\engine\test_attribution_supportability.py tests\unit\models\test_attribution_models.py tests\unit\app\test_attribution_openapi_contract.py -q
# 51 passed.

python -m ruff check app\models\attribution_responses.py engine\attribution.py engine\attribution_supportability.py tests\unit\engine\test_attribution.py
# Passed.

python -m pytest tests\unit\engine\test_attribution.py tests\unit\engine\test_attribution_supportability.py tests\unit\models\test_attribution_models.py tests\unit\app\test_attribution_openapi_contract.py tests\unit\docs\test_public_docs_contract.py -q
# 93 passed.

python scripts\api_vocabulary_inventory.py --validate-only
# API vocabulary inventory gate passed (no drift).

python -m pytest tests\integration\test_attribution_api.py -q
# 25 passed.

make check
# ruff, format check, monetary-float guard, no-alias guard, mypy, OpenAPI quality gate,
# API vocabulary inventory, domain-product validation, and 1232 unit tests passed.
```

## Review Decision

Slice 8 is complete after full repo-native validation and GitHub checks pass. The test changes cover
real formula, reconciliation, segment-union, supportability, and linking risks. Unsupported source
QA scenarios remain explicitly bounded rather than converted into misleading product claims.
