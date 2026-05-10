# RFC-046 Slice 5 Denominator, Linkability, Reset, and Episode Semantics

| Field | Value |
| --- | --- |
| RFC | RFC-046 - TWR Industry Methodology Alignment, Evidence Contract, and Data Product Hardening |
| Slice | 5 - Denominator, Linkability, Reset, and Episode Semantics |
| `lotus-performance` branch | `feat/rfc-046-twr-industry-evidence` |

## Implementation

Slice 5 strengthens the daily TWR evidence contract added in Slice 4. The engine denominator policy
is unchanged: Lotus calculates daily TWR with the absolute value of beginning market value plus
beginning-of-day external cash flow. The implementation now exposes the semantics required to make
that policy explainable to private banking, operations, controls, and downstream product consumers.

Daily portfolio `calculation_evidence` now includes:

- `signed_adjusted_capital`, the raw beginning market value plus beginning-of-day flow before the
  absolute denominator policy is applied.
- `linkability_status`, explaining whether the row is `linkable`, `reset_boundary`,
  `not_calculated`, or `not_linkable`.
- `episode_status`, explaining whether the row is an `open` TWR episode day, a `reset_boundary`, a
  `no_investment` day, or `not_in_period`.

The response reason and warning codes now characterize denominator and linking edge cases:

| Condition | Reason or warning evidence |
| --- | --- |
| Zero adjusted capital | `ZERO_ADJUSTED_CAPITAL`, `not_calculated`, `not_calculated` linkability |
| Negative signed adjusted capital | `NEGATIVE_ADJUSTED_CAPITAL_INPUT` warning while preserving the absolute denominator policy |
| Near-zero adjusted capital | `NEAR_ZERO_ADJUSTED_CAPITAL` warning |
| Before effective period start | `BEFORE_EFFECTIVE_PERIOD_START`, `not_in_period`, `not_calculated` linkability |
| Reset day | `RESET_DAY`, `reset_boundary` episode and linkability |
| No-investment period | `NO_INVESTMENT_PERIOD`, `no_investment`, `not_calculated` linkability |
| Full withdrawal day | `FULL_WITHDRAWAL_DAY` |
| Refunding day | `REFUNDING_DAY` |
| `-100%` daily return | `FULL_LOSS_RETURN`, `not_linkable` |
| Less than `-100%` daily return | `BELOW_FULL_LOSS_RETURN`, `not_linkable` |

## Inspector Alignment

The calculation-consistency inspector now certifies both the numeric and semantic parts of daily
TWR evidence. It validates `signed_adjusted_capital`, `adjusted_capital`, external flow split,
daily return, and daily period return. It also flags missing or inconsistent semantic evidence,
including linkability status, episode status, required reason codes, and required warning codes.

This is deliberately stricter than a response-shape test. The inspector now protects the Lotus
product contract from returning a mathematically correct daily return with an incomplete or
misleading explanation.

## Denominator Decision

No denominator formula change was made in Slice 5. The RFC required characterization before policy
change, and the implementation-backed tests did not prove the current policy incorrect. Instead,
Slice 5 makes the current absolute denominator policy auditable by exposing both the signed input
and the applied denominator, with explicit warnings where reviewer attention is required.

## Validation

Slice 5 validation completed:

- `python -m pytest tests/unit/services/test_twr_daily_calculation_evidence.py tests/unit/services/test_twr_inspection_calculation_consistency.py tests/unit/models/test_responses_models.py -q`
  - Passed: 21 tests.
- `python -m pytest tests/unit/services/test_twr_daily_calculation_evidence.py tests/unit/services/test_twr_inspection_calculation_consistency.py tests/unit/app/test_twr_openapi_contract.py tests/unit/models/test_responses_models.py tests/unit/docs/test_public_docs_contract.py tests/integration/test_performance_api.py::test_calculate_twr_endpoint_legacy_path_and_diagnostics tests/integration/test_performance_api.py::test_twr_daily_calculation_evidence_handles_same_day_deposit_and_withdrawal tests/integration/test_performance_api.py::test_twr_respects_include_timeseries_flag tests/integration/test_response_attribute_certification.py::test_twr_response_attributes_tie_to_deterministic_stateless_inputs -q`
  - Passed: 77 tests.
- `make lint`
  - Passed, including monetary-float guard with no allowlist update.
- `make typecheck`
  - Passed.
- `make coverage-gate`
  - Passed: unit 1,194 passed, integration 273 passed, e2e 21 passed, combined coverage 99%.
- `python scripts/openapi_quality_gate.py`
  - Passed.
- `make api-vocabulary-gate`
  - Passed, no vocabulary drift.
- `python scripts/no_alias_contract_guard.py`
  - Passed.
- `git diff --check`
  - Passed, with only Git line-ending normalization warnings on edited Markdown files.
