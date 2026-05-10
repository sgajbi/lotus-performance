# RFC-046 Slice 4 Daily TWR Calculation Evidence

| Field | Value |
| --- | --- |
| RFC | RFC-046 - TWR Industry Methodology Alignment, Evidence Contract, and Data Product Hardening |
| Slice | 4 - Daily TWR Calculation Evidence Contract |
| `lotus-performance` branch | `feat/rfc-046-twr-industry-evidence` |

## Implementation

Slice 4 adds API-visible daily calculation evidence to portfolio daily TWR breakdown rows. The
evidence is intentionally curated product evidence, not raw engine debug data. It is returned
independently of `output.include_timeseries`, while raw `daily_data` remains an optional diagnostic
drill-down controlled by that flag.

The response model now exposes `calculation_evidence` on daily portfolio breakdown rows with:

- `calculation_method`
- `denominator_basis`
- `flow_timing_convention`
- `begin_mv`
- `end_mv`
- `bod_cf`
- `eod_cf`
- `external_inflows`
- `external_outflows`
- `management_fees`
- `adjusted_capital`
- `performance_pnl`
- `daily_return`
- `status`
- `reason_codes`
- `warnings`

The denominator basis is `absolute_begin_mv_plus_bod_cf`. Beginning-of-day flows adjust invested
capital. End-of-day flows are neutralized from performance P&L but do not adjust the denominator.
For NET calculations, management fees are included in performance P&L to match the existing engine
calculation path.

## Edge Coverage

| Scenario | Evidence added |
| --- | --- |
| No external flow | Daily evidence proves beginning value, ending value, adjusted capital, performance P&L, and daily return. |
| Deposit-neutralized day | Daily evidence proves beginning-of-day deposit treatment, adjusted capital, external inflow, and neutralized return. |
| Withdrawal-neutralized day | Daily evidence records negative external flows as absolute outflow evidence. |
| Same-day deposit and withdrawal | Integration coverage proves beginning-of-day inflow and end-of-day outflow are separated and neutralized correctly. |
| Denominator basis | OpenAPI and integration tests assert the `absolute_begin_mv_plus_bod_cf` denominator basis. |

## Contract Posture

This is an additive response contract change. No downstream repository change is required for Slice
4 because the existing downstream contract consumers are not required to parse the new field to
continue functioning. Later RFC-046 downstream realization slices must decide whether Gateway,
Workbench, reporting, or AI surfaces should consume and display this evidence as product value.

## Validation

Slice 4 validation completed:

- `python -m pytest tests/integration/test_performance_api.py::test_calculate_twr_endpoint_legacy_path_and_diagnostics tests/integration/test_performance_api.py::test_twr_daily_calculation_evidence_handles_same_day_deposit_and_withdrawal tests/integration/test_performance_api.py::test_twr_respects_include_timeseries_flag tests/integration/test_response_attribute_certification.py::test_twr_response_attributes_tie_to_deterministic_stateless_inputs tests/unit/app/test_twr_openapi_contract.py tests/unit/models/test_responses_models.py tests/unit/docs/test_public_docs_contract.py -q`
  - Passed: 52 tests.
- `python -m pytest tests/unit/app/test_twr_openapi_contract.py tests/unit/models/test_responses_models.py tests/unit/docs/test_public_docs_contract.py tests/integration/test_performance_api.py tests/integration/test_response_attribute_certification.py -q`
  - Passed: 90 tests, with one existing `HTTP_422_UNPROCESSABLE_ENTITY` deprecation warning in `stateful_benchmark_input_service.py`.
- `python -m ruff check app/models/responses.py app/services/twr_service.py tests/integration/test_performance_api.py tests/integration/test_response_attribute_certification.py tests/unit/app/test_twr_openapi_contract.py tests/unit/models/test_responses_models.py tests/unit/docs/test_public_docs_contract.py`
  - Passed.
- `python -m ruff format --check .`
  - Passed.
- `make lint`
  - Passed, including `monetary-float-guard` with no allowlist update.
- `make typecheck`
  - Passed.
- `python scripts/openapi_quality_gate.py`
  - Passed.
- `make api-vocabulary-gate`
  - Passed, no vocabulary drift.
- `python scripts/no_alias_contract_guard.py`
  - Passed.
- `git diff --check`
  - Passed, with only existing Git line-ending normalization warnings on edited Markdown files.
