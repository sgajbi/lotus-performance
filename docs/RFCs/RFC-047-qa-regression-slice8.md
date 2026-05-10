# RFC 047 Slice 8 - QA Regression Pack And Test Pyramid Upgrade

## Scope Completed

Slice 8 converted the contribution source-document QA pack into implementation-backed Lotus tests and an evidence matrix. The added tests are endpoint-level because the risk is contract behavior, not isolated helper behavior.

## New Regression Tests

Added to `tests/integration/test_contribution_api.py`:

1. `test_contribution_endpoint_treats_external_deposit_as_non_performance`
   - Proves an external deposit increases market value without creating performance or contribution.
2. `test_contribution_endpoint_assigns_income_to_generating_asset`
   - Proves income economics are assigned to the generating asset classification when source metadata supplies `income_pnl`.
3. `test_contribution_endpoint_assigns_net_fee_drag_to_fee_bucket`
   - Proves net fee drag is carried by the explicit fee bucket and represented as negative contribution.
4. `test_contribution_endpoint_preserves_missing_classification_as_unclassified`
   - Proves missing classification is exposed as `Unclassified`, not dropped or guessed.
5. `test_contribution_endpoint_preserves_short_position_inverse_sign_behavior`
   - Proves short-sleeve negative weights and inverse contribution sign are preserved through the API.

## RFC QA Pack Coverage Matrix

| Required edge | Proof |
| --- | --- |
| Basic single-period contribution | `tests/integration/test_contribution_api.py::test_contribution_endpoint_happy_path_and_envelope` |
| Internal buy trade is not portfolio external flow | `tests/e2e/test_workflow_journeys.py::test_e2e_balanced_internal_position_flows_keep_flow_residual_silent` |
| External deposit is not performance | `tests/integration/test_contribution_api.py::test_contribution_endpoint_treats_external_deposit_as_non_performance` |
| Income assigned to generating asset or income bucket | `tests/integration/test_contribution_api.py::test_contribution_endpoint_assigns_income_to_generating_asset` |
| Fee bucket in net contribution | `tests/integration/test_contribution_api.py::test_contribution_endpoint_assigns_net_fee_drag_to_fee_bucket` |
| Short position sign behavior | `tests/integration/test_contribution_api.py::test_contribution_endpoint_preserves_short_position_inverse_sign_behavior` |
| Raw multi-period mismatch | `tests/unit/engine/test_contribution.py::test_raw_daily_contributions_can_fail_multi_period_linkage_until_carino_applied` |
| Carino smoothing deterministic example | `tests/unit/engine/test_contribution.py::test_carino_industry_example_links_positive_and_negative_returns` |
| Zero period return | `tests/integration/test_contribution_api.py::test_contribution_endpoint_treats_external_deposit_as_non_performance` |
| Zero total linked return | `tests/integration/test_contribution_api.py::test_contribution_endpoint_no_smoothing`; engine zero-capital tests in `tests/unit/engine/test_contribution.py` |
| Invalid period return | `tests/integration/test_contribution_api.py::test_contribution_endpoint_smoothing_evidence_reports_invalid_carino_domain` |
| Missing classification -> `Unclassified` | `tests/integration/test_contribution_api.py::test_contribution_endpoint_preserves_missing_classification_as_unclassified` |
| Partial hierarchy -> explicit partial/Other/residual posture | `tests/integration/test_contribution_api.py::test_contribution_endpoint_hierarchy_respects_multiple_resolved_periods`; `test_contribution_endpoint_hierarchy_keeps_position_contribution_detail`; `test_contribution_endpoint_hierarchy_top_n_rolls_excluded_rows_into_other` |
| FX/local/base contribution behavior | `tests/integration/test_contribution_api.py::test_contribution_endpoint_multi_currency`; `test_contribution_stateful_converts_non_base_cash_flows_using_explicit_fx_metadata`; Workbench fixture-backed UI tests in `lotus-workbench` PR `sgajbi/lotus-workbench#177` |
| Async execution and lineage evidence | `tests/integration/test_contribution_api.py::test_contribution_async_result_retrieval`; `test_contribution_lineage_flow`; `tests/e2e/test_workflow_journeys.py::test_e2e_contribution_lineage_roundtrip` |
| Downstream Gateway/Workbench preservation | `lotus-gateway` PR `sgajbi/lotus-gateway#206`; `lotus-workbench` PR `sgajbi/lotus-workbench#177`; Slice 7 evidence `docs/RFCs/RFC-047-api-contract-downstream-slice7.md` |

## Validation Evidence

Local validation:

1. `python -m pytest tests/integration/test_contribution_api.py -q`
   - Result: `40 passed`, `1` existing deprecation warning from `HTTP_422_UNPROCESSABLE_ENTITY`.
2. `python -m pytest tests/unit/engine/test_contribution.py tests/unit/services/test_contribution_source_economics.py tests/unit/models/test_contribution_models.py -q`
   - Result: `36 passed`.
3. `python -m pytest tests/e2e/test_workflow_journeys.py -q`
   - Result: `21 passed`.
4. `python -m ruff check tests/integration/test_contribution_api.py`
   - Result: passed.

## Critical Review

What improved:

1. The contribution test suite now covers source-document economic edge cases as API behavior.
2. The new tests assert totals, hierarchy classification, source-economics supportability, and sign behavior instead of only checking HTTP success.
3. Existing e2e coverage already proves async, lineage, reset-heavy, and downstream-consistency behavior, so this slice did not duplicate those paths.

Remaining risk:

1. Live front-office stack proof belongs to later implementation-proof and closure slices after all QA and docs slices are complete.
2. The existing deprecation warning for FastAPI `HTTP_422_UNPROCESSABLE_ENTITY` is unrelated to contribution correctness and should be handled in a focused platform/framework cleanup slice if it becomes policy-relevant.
