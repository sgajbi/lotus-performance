# RFC 040 - Returns Series Contract Hardening for lotus-risk Historical Attribution

## Status
Proposed (Implementation Ready)

## Date
2026-03-01

## Owners
- lotus-performance: return-series owner
- lotus-risk: stateful attribution consumer
- lotus-platform: governance owner (RFC-0067)

## 1. Summary
`lotus-risk` historical attribution stateful mode depends on `POST /integration/returns/series`.
This RFC hardens that contract for attribution-grade requirements (deterministic alignment, benchmark support, metadata lineage, and policy transparency).

## 2. Goals
1. Guarantee a stable canonical return-series input contract for stateful attribution.
2. Ensure benchmark series behavior is explicit and deterministic for active risk use cases.
3. Preserve compatibility with existing stateful risk consumers.
4. Enforce complete OpenAPI + vocabulary compliance.

## 3. Non-Goals
1. Implement attribution calculations in lotus-performance.
2. Replace lotus-core as system of record for benchmark definitions/master data.
3. Add simulation-specific return forecasting behavior.

## 4. Endpoint in Scope
- `POST /integration/returns/series`

## 5. Required Request Behavior
Required request semantics:
1. `input_mode=stateful` with `stateful_input.consumer_system` required for service consumers.
2. `window` supports explicit and relative definitions with deterministic resolution.
3. `series_selection` controls inclusion of:
- `portfolio_returns`
- `benchmark_returns`
- `risk_free_returns`
4. `data_policy` is honored and echoed in diagnostics metadata.

## 6. Required Response Behavior
1. `series.portfolio_returns[]` must be present when `include_portfolio=true`.
2. `series.benchmark_returns[]` must be present or deterministic error raised when benchmark is requested.
3. Return rows must be strictly ascending by date with no duplicates.
4. `return_value` is decimal return, not percentage.
5. Response includes:
- `resolved_window`
- `provenance` / `lineage` metadata
- policy and coverage diagnostics

## 7. Attribution-Specific Requirements
1. Active risk attribution readiness requires robust benchmark return handling:
- missing benchmark under strict policy must fail deterministically.
- policy-based partial returns must include explicit warning flags.
2. Portfolio and benchmark date alignment behavior must be explicit and deterministic.
3. Frequency conversion (if requested) must be documented and reproducible.

## 8. Error Model
Use standard Lotus error envelope and deterministic codes:
1. `INVALID_REQUEST`
2. `RESOURCE_NOT_FOUND`
3. `INSUFFICIENT_DATA`
4. `SOURCE_UNAVAILABLE`
5. `UNSUPPORTED_CONFIGURATION`
6. `CONTRACT_VIOLATION_UPSTREAM`

All errors must propagate correlation IDs.

## 9. Testing Requirements
1. Contract tests for request/response shape and field invariants.
2. Characterization tests for:
- deterministic ordering
- alignment behavior
- missing benchmark policies
3. Integration characterization tests with lotus-risk expected payload mapping.

## 10. Governance Requirements
1. Every schema attribute has description + realistic example.
2. API vocabulary inventory updated for any new/changed fields.
3. No legacy aliases or mixed naming conventions.
4. OpenAPI operation grouped under integration domain boundaries.

## 11. Acceptance Criteria
1. lotus-risk can source stateful portfolio returns for attribution without transformation ambiguity.
2. lotus-risk receives benchmark returns with deterministic policy semantics for active-risk decomposition.
3. Contract metadata supports audit, reproducibility, and downstream explainability.
4. RFC-0067 gates pass for OpenAPI quality and vocabulary governance.
