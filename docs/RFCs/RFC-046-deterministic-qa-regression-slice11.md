# RFC-046 Slice 11 Deterministic QA Regression Pack

| Field | Value |
| --- | --- |
| RFC | RFC-046 - TWR Industry Methodology Alignment, Evidence Contract, and Data Product Hardening |
| Slice | 11 - Deterministic QA Regression Pack |
| `lotus-performance` branch | `feat/rfc-046-twr-industry-evidence` |

## Implementation

Slice 11 reviews the applicable industry TWR QA cases against the current Lotus implementation and
adds one missing endpoint-level regression: an arithmetic-sum anti-test proving that daily returns
are geometrically linked rather than summed.

New test:

- `tests/integration/test_performance_api.py::test_twr_industry_qa_links_daily_returns_instead_of_summing_them`
  - two daily returns of `+10%` and `-10%`
  - arithmetic sum is `0%`
  - Lotus period and cumulative TWR correctly return `-1%`
  - daily calculation evidence remains calculated, linkable, and reason-coded as
    `FLOW_NEUTRALIZED_DAILY_RETURN`

## Industry QA Mapping

| Industry QA case | Lotus test evidence | RFC-046 decision |
| --- | --- | --- |
| Geometric linking instead of arithmetic summing | `tests/integration/test_performance_api.py::test_twr_industry_qa_links_daily_returns_instead_of_summing_them`; `tests/integration/test_response_attribute_certification.py` | Adopted and endpoint-pinned. |
| Deposits at beginning of day | `tests/integration/test_performance_api.py::test_calculate_twr_endpoint_legacy_path_and_diagnostics`; `tests/unit/engine/test_compute.py::test_run_calculations_treats_ordinary_subscription_as_continuous_compounding` | Adopted. Beginning-of-day flows adjust invested capital. |
| Withdrawals at end of day | `tests/integration/test_performance_api.py::test_twr_daily_calculation_evidence_handles_same_day_deposit_and_withdrawal` | Adopted. End-of-day flows are neutralized from performance P&L and excluded from denominator. |
| Same-day deposit and withdrawal evidence | `tests/integration/test_performance_api.py::test_twr_daily_calculation_evidence_handles_same_day_deposit_and_withdrawal` | Adopted. |
| Zero adjusted capital | `tests/unit/services/test_twr_daily_calculation_evidence.py::test_daily_calculation_evidence_zero_adjusted_capital_is_not_calculated` | Adopted. |
| Negative adjusted capital | `tests/unit/services/test_twr_daily_calculation_evidence.py::test_daily_calculation_evidence_records_negative_and_near_zero_denominator_semantics` | Adopted with warning evidence; Lotus uses absolute denominator policy and preserves signed input evidence. |
| Near-zero adjusted capital | `tests/unit/services/test_twr_daily_calculation_evidence.py::test_daily_calculation_evidence_records_negative_and_near_zero_denominator_semantics` | Adopted with warning evidence. |
| Full loss or below-full-loss return | `tests/unit/services/test_twr_daily_calculation_evidence.py::test_daily_calculation_evidence_records_full_loss_and_below_full_loss_linkability` | Adopted. Rows become `not_linkable`. |
| Reset and no-investment episode evidence | `tests/unit/services/test_twr_daily_calculation_evidence.py::test_daily_calculation_evidence_records_reset_and_no_investment_reason_codes`; `tests/integration/test_performance_api.py::test_twr_reports_reset_events_when_requested` | Adopted. |
| Long/short or leveraged exposure continuity where portfolio TWR supports it | Existing engine characterization under `tests/unit/engine/test_compute.py` plus RFC-046 supported-feature boundary docs | Adopted only as portfolio exposure behavior, not sleeve TWR. |
| Benchmark calendar gap | `tests/unit/services/test_twr_benchmark_supportability.py::test_twr_benchmark_supportability_reports_calendar_and_vendor_series_warnings` | Adopted through supportability evidence. |
| Benchmark no-overlap | `tests/unit/services/test_twr_benchmark_supportability.py::test_twr_benchmark_supportability_reports_no_overlap_and_empty_benchmark_dates` | Adopted through supportability evidence. |
| Missing FX decomposition / base-only benchmark evidence | `tests/unit/services/test_twr_benchmark_supportability.py::test_twr_benchmark_supportability_reports_base_only_cross_currency_evidence`; `tests/unit/services/test_stateless_benchmark_input_service.py::test_normalize_stateless_component_observations_rejects_cross_currency_price_points_without_fx` | Adopted. Missing cross-currency FX is rejected or explicitly supportability-coded depending on input mode. |
| Source-quality degraded states | `tests/integration/test_performance_api.py` source-quality supportability assertions; `tests/unit/services/test_source_quality_evidence.py`; `tests/unit/services/test_twr_inspection_source_quality.py` | Adopted. |
| Composite, group, or sleeve TWR | `docs/guides/twr.md`, `wiki/Supported-Features.md`, `docs/RFCs/RFC-046-composite-boundary-slice8.md` | Out of scope. Not promoted as supported by RFC-046. |

## Validation

Slice 11 validation commands:

- `python -m pytest tests/integration/test_performance_api.py::test_twr_industry_qa_links_daily_returns_instead_of_summing_them -q`
  - Result: `1 passed`

Broader validation:

- `python -m pytest tests/integration/test_performance_api.py::test_twr_industry_qa_links_daily_returns_instead_of_summing_them tests/integration/test_performance_api.py::test_twr_daily_calculation_evidence_handles_same_day_deposit_and_withdrawal tests/integration/test_performance_api.py::test_calculate_twr_endpoint_legacy_path_and_diagnostics tests/unit/services/test_twr_daily_calculation_evidence.py tests/unit/services/test_twr_benchmark_supportability.py tests/unit/services/test_source_quality_evidence.py -q`
  - Result: `18 passed`
- `python -m pytest tests/unit/docs/test_public_docs_contract.py -q`
  - Result: `41 passed`
- `make lint`
  - Result: passed, including monetary-float guard with `135` findings and `135` allowlisted findings
- `make typecheck`
  - Result: `Success: no issues found in 159 source files`
- `python scripts/openapi_quality_gate.py`
  - Result: passed
- `python scripts/api_vocabulary_inventory.py --validate-only`
  - Result: passed with no vocabulary drift
- `python scripts/no_alias_contract_guard.py`
  - Result: passed
- `git diff --check`
  - Result: passed, with line-ending warnings only
