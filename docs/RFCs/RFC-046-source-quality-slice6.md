# RFC-046 Slice 6 Stateful Source Classification and Data Quality Evidence

| Field | Value |
| --- | --- |
| RFC | RFC-046 - TWR Industry Methodology Alignment, Evidence Contract, and Data Product Hardening |
| Slice | 6 - Stateful Source Classification and Data Quality Evidence |
| `lotus-performance` branch | `feat/rfc-046-twr-industry-evidence` |

## Implementation

Slice 6 preserves source-quality evidence from stateful `PortfolioTimeseriesInput` normalization
and exposes it in `calculation_supportability.source_quality_evidence`.

The supportability evidence records:

- source owner and source product (`lotus-core`, `PortfolioTimeseriesInput`)
- input mode (`stateful`)
- raw source observation count
- normalized valuation-point count
- skipped observation count
- unsupported cash-flow label count
- duplicate-date source conflict count
- latest source observation date and requested report end date
- bounded warning codes
- upstream source classification counts when supplied by the source product

The calculation engine remains separate from inspection. Slice 6 does not merge RFC-045
inspection responsibilities into the calculation path; it preserves the source-quality evidence
needed for front-office supportability, operations triage, and downstream data-product consumers.

## Warning Codes

| Warning | Meaning |
| --- | --- |
| `MISSING_VALUATION_POINTS` | One or more upstream observations could not be normalized because required valuation fields were missing or invalid. |
| `UNSUPPORTED_CASHFLOW_LABELS` | One or more cash-flow labels were unsupported for TWR economics and were skipped from TWR cash-flow normalization. |
| `SOURCE_DATE_CONFLICTS` | Duplicate source observations for the same date carried conflicting valuation values. |
| `STALE_SOURCE_OBSERVATIONS` | The latest normalized source observation predates the requested report end date. |

## Supportability Policy

Stale source observations keep the existing `stale_source_observations` supportability reason and
`stale` state. Non-stale source-quality warnings degrade supportability to
`calculation_quality_issue`, so consumers can distinguish a complete clean calculation from a
calculation that completed with source-quality reservations.

## Validation

Slice 6 validation completed:

- `python -m pytest tests/unit/services/test_source_quality_evidence.py tests/unit/services/test_calculation_supportability_service.py tests/integration/test_performance_api.py::test_twr_supports_stateful_input_mode tests/integration/test_performance_api.py::test_twr_stateful_supportability_exposes_source_quality_warnings -q`
  - Passed: 8 tests.
- `python -m pytest tests/integration/test_performance_api.py tests/integration/test_response_attribute_certification.py tests/unit/app/test_twr_openapi_contract.py tests/unit/docs/test_public_docs_contract.py tests/unit/models/test_responses_models.py tests/unit/services/test_source_quality_evidence.py tests/unit/services/test_calculation_supportability_service.py -q`
  - Passed: 97 tests, with one existing `HTTP_422_UNPROCESSABLE_ENTITY` deprecation warning.
- `make lint`
  - Passed, including monetary-float guard with no allowlist update.
- `make typecheck`
  - Passed.
- `make coverage-gate`
  - Passed: unit 1,197 passed, integration 274 passed, e2e 21 passed, combined coverage 99%.
- `python scripts/openapi_quality_gate.py`
  - Passed.
- `make api-vocabulary-gate`
  - Passed after regenerating `docs/standards/api-vocabulary/lotus-performance-api-vocabulary.v1.json` for the new supportability vocabulary.
- `python scripts/no_alias_contract_guard.py`
  - Passed.
- `git diff --check`
  - Passed, with only Git line-ending normalization warnings on edited files.
