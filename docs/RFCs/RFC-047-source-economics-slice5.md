# RFC-047 Slice 5 - Source Economics and Upstream Contract Realization Evidence

| Field | Value |
| --- | --- |
| RFC | RFC-047 - Contribution Carino Methodology Alignment and Evidence Contract |
| Slice | 5 - Source Economics and Upstream Contract Realization |
| Branch | `docs/rfc-contribution-carino-alignment` |
| Date | 2026-05-10 |

## Scope Completed

Slice 5 reviewed the current `lotus-core` analytics input contracts and tightened
`lotus-performance` so contribution source economics are explicit rather than implied.

Implemented changes:

1. Added `source_economics_evidence` to `ContributionResponse`.
2. Added `app/services/contribution_source_economics.py` to classify stateful and stateless
   contribution source posture.
3. Preserved stateful position-row `_source_economics.cash_flow_type_counts` during normalization.
4. Recognized canonical `internal_trade_flow` and `transfer` cash-flow labels in the source
   cash-flow taxonomy.
5. Kept unavailable source-authored component P&L families explicit under
   `unsupported_economics` instead of reconstructing income, tax, FX P&L, corporate-action,
   derivative, cash, or residual P&L locally.

## Upstream Assessment

Reviewed `lotus-core` read-only, including:

1. `src/services/query_service/app/dtos/analytics_input_dto.py`;
2. `src/services/query_service/app/services/analytics_timeseries_service.py`;
3. `src/services/query_service/app/repositories/analytics_timeseries_repository.py`;
4. `docs/architecture/RFC-0083-source-data-product-catalog.md`;
5. `docs/methodologies/source-data-products/*`.

Current `lotus-core` stateful analytics inputs already provide the essential contribution source
facts for the current Lotus methodology:

1. portfolio market-value timeseries;
2. position market-value timeseries;
3. source cash-flow observations with canonical `cash_flow_type`, `flow_scope`, and source
   classification;
4. FX rates for position-to-portfolio and portfolio-to-reporting conversion;
5. selected classification dimensions;
6. snapshot epoch, runtime metadata, paging, request fingerprint, and source-data product metadata;
7. execution-registry upstream snapshot evidence when calls are not mocked.

No `lotus-core` code change was required for this slice. The missing economics are not essential
for current contribution calculation, but they are important supportability truth. They are now
explicitly classified as unsupported/degraded in `lotus-performance` output instead of hidden.

## Response Contract

`ContributionResponse.source_economics_evidence` now reports:

1. input mode and source owner;
2. source contracts used;
3. available economics;
4. unsupported component-P&L families;
5. degraded economics such as unsupported cash-flow labels, missing classification, or missing
   embedded snapshot evidence;
6. cash-flow type counts;
7. upstream snapshot count and endpoint list where available;
8. lineage policy.

The response is intentionally conservative. It does not claim component income, tax, FX P&L,
corporate-action, derivative, cash, loan, liability, or residual economics unless a source-authored
contract supplies them.

## Tests Added or Strengthened

1. `tests/unit/services/test_contribution_source_economics.py`
   - source-rich stateful evidence;
   - source-limited stateful evidence;
   - stateless caller-supplied boundary.
2. `tests/unit/services/test_source_cashflow_taxonomy.py`
   - canonical `internal_trade_flow`;
   - canonical `transfer`.
3. `tests/unit/services/test_stateful_position_row_service.py`
   - internal trade and transfer flows are included in normalized position cash flows.
4. `tests/integration/test_contribution_api.py`
   - top-level source-economics evidence appears for stateless and stateful contribution responses;
   - resolved stateful input fingerprint includes preserved `_source_economics` metadata.

## Validation

Commands run:

```powershell
python -m ruff check app/services/source_cashflow_taxonomy.py app/services/stateful_contribution_input_service.py app/services/contribution_source_economics.py app/models/contribution_responses.py app/services/contribution_service.py tests/unit/services/test_source_cashflow_taxonomy.py tests/unit/services/test_stateful_position_row_service.py tests/unit/services/test_contribution_source_economics.py tests/integration/test_contribution_api.py
python -m ruff format --check app/services/source_cashflow_taxonomy.py app/services/stateful_contribution_input_service.py app/services/contribution_source_economics.py app/models/contribution_responses.py app/services/contribution_service.py tests/unit/services/test_source_cashflow_taxonomy.py tests/unit/services/test_stateful_position_row_service.py tests/unit/services/test_contribution_source_economics.py tests/integration/test_contribution_api.py
python -m pytest tests/unit/services/test_source_cashflow_taxonomy.py tests/unit/services/test_stateful_position_row_service.py tests/unit/services/test_contribution_source_economics.py tests/unit/services/test_contribution_mode_service.py -q
python -m pytest tests/integration/test_contribution_api.py -q
python -m pytest tests/unit/docs/test_public_docs_contract.py tests/unit/docs/test_metric_methodology_docs.py -q
python scripts/openapi_quality_gate.py
python scripts/api_vocabulary_inventory.py --validate-only
make typecheck
make lint
python scripts/check_monetary_float_usage.py
```

Results:

1. ruff check passed.
2. ruff format check passed.
3. unit service pack passed: `20 passed, 2 warnings`.
4. contribution integration pack passed: `35 passed, 1 warning`.
5. docs contract pack passed: `49 passed`.
6. OpenAPI quality gate passed.
7. API vocabulary inventory gate passed.
8. typecheck passed: `Success: no issues found in 161 source files`.
9. lint passed, including monetary-float guard.
10. monetary-float guard passed: `Findings=137, allowlisted=137`.

Parallel execution note: do not run `tests/integration/test_contribution_api.py` concurrently with
unit tests that assert the shared local execution registry. The integration fixture clears the same
local registry tables during setup/teardown; sequential execution is the correct local proof.
