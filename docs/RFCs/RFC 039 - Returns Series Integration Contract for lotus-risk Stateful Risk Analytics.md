# RFC 039 - Returns Series Integration Contract for lotus-risk Stateful Risk Analytics

## Status
Proposed (Refined)

## Date
2026-03-01

## Owners
- lotus-performance (return-series computation and serving owner)
- lotus-risk (primary stateful consumer)
- lotus-core (assignment + reference-data provider)

## 1. Problem Statement
`lotus-risk` is implementing `POST /analytics/risk/calculate` in phased mode:
- Slice 1: stateless input supplied by caller (implemented)
- Slice 2: stateful mode where lotus-risk resolves canonical time series internally (in progress)

Stateful risk analytics requires deterministic return series inputs with audit-grade diagnostics:
- portfolio return series
- benchmark return series (for beta/tracking error/information ratio)
- optional risk-free series (for Sharpe/Sortino under non-constant assumptions)

Current lotus-performance analytics APIs are result-oriented and are not a dedicated cross-service return-series boundary for risk engines.

## 2. Decision
Introduce a dedicated integration endpoint in lotus-performance:
- `POST /integration/returns/series`

This endpoint becomes the canonical return-series supplier for downstream stateful analytics consumers, starting with lotus-risk.

Ownership boundary:
1. lotus-core resolves benchmark assignment and exposes benchmark reference data primitives.
2. lotus-performance computes benchmark daily returns/performance (single-index/composite) and serves canonical series.

## 3. Design Goals
1. Accuracy: deterministic, policy-explicit, no hidden imputation.
2. Scalability: efficient for long windows and repeated requests.
3. Reusability: support risk, reporting, and future analytics domains.
4. Operability: strong diagnostics, provenance, and correlation traceability.
5. Governance: full RFC-0067 compliance (OpenAPI quality + vocabulary inventory + canonical naming).

## 4. Scope
- New integration endpoint and contract models.
- Explicit data-quality policy model and diagnostics model.
- Deterministic error contract with platform-standard envelope.
- Unit/integration characterization tests for correctness and stability.
- RFC-0067 metadata and vocabulary inventory updates.

## 5. Out of Scope
- lotus-risk risk formula implementation changes.
- Stateful simulation impacts (separate RFC track).
- New benchmark methodology logic (composition/rebalancing logic not defined here).

## 6. Contract (Normative)

### 6.1 Endpoint
- Method: `POST`
- Path: `/integration/returns/series`
- Authz: service-to-service integration policy

### 6.2 Request (Normative Fields)
- `portfolio_id: str` required
- `as_of_date: date` required
- `window` required
  - `mode: EXPLICIT | RELATIVE`
  - `from_date`, `to_date` required for `EXPLICIT`
  - `period` required for `RELATIVE` (`MTD|QTD|YTD|ONE_YEAR|THREE_YEAR|FIVE_YEAR|SI|YEAR`)
  - `year` required when `period=YEAR`
- `frequency: DAILY | WEEKLY | MONTHLY` required
- `metric_basis: NET | GROSS` required
- `reporting_currency: str | None` optional
- `series_selection` optional
  - `include_portfolio: bool` default `true`
  - `include_benchmark: bool` default `false`
  - `include_risk_free: bool` default `false`
- `benchmark` optional
  - `benchmark_id: str | None`
  - `benchmark_series_ref: str | None`
- `risk_free` optional
  - `rate_series_ref: str | None`
  - `day_count_basis: ACT_365 | ACT_360 | THIRTY_360` optional
- `data_policy` optional
  - `missing_data_policy: FAIL_FAST | ALLOW_PARTIAL | STRICT_INTERSECTION`
  - `fill_method: NONE | FORWARD_FILL | ZERO_FILL`
  - `calendar_policy: MARKET | BUSINESS | CALENDAR`
  - `max_gap_days: int | None`

### 6.3 Response (Normative Fields)
- `source_service: "lotus-performance"`
- `contract_version: str`
- `portfolio_id: str`
- `as_of_date: date`
- `frequency: DAILY|WEEKLY|MONTHLY`
- `metric_basis: NET|GROSS`
- `resolved_window`
  - `start_date: date`
  - `end_date: date`
  - `resolved_period_label: str | None`
- `series`
  - `portfolio_returns[]: {date, return_value}`
  - `benchmark_returns[]: {date, return_value}` optional
  - `risk_free_returns[]: {date, return_value}` optional
- `provenance`
  - `input_mode: stateful | stateless`
  - `input_fingerprint: str`
  - `calculation_hash: str`
- `diagnostics`
  - `coverage`
    - `requested_points`
    - `returned_points`
    - `missing_points`
    - `coverage_ratio`
  - `gaps[]` (series_type, from_date, to_date, gap_days)
  - `policy_applied` echo
  - `warnings[]`
- `metadata`
  - `generated_at`
  - `correlation_id`
  - `request_id`
  - `trace_id`

## 7. Behavioral Semantics
1. Deterministic ordering: each series strictly ascending by date.
2. Uniqueness: no duplicate dates within a series.
3. Window precedence: explicit windows dominate relative windows if both are provided (invalid request unless policy permits one-mode-only validation).
4. Policy transparency: response must explicitly show applied fill/missing policy.
5. Currency normalization:
- if `reporting_currency` is provided, all series must reflect that currency context and diagnostics must include conversion coverage.
6. Benchmark semantics:
- if benchmark is requested and unresolved, return deterministic failure unless policy allows partial.
7. Correlation propagation:
- consume incoming correlation headers and emit them in response headers and metadata.

## 8. Accuracy and Quant Requirements
1. Return convention explicitness:
- simple returns only in v1; log-return support reserved for v2.
2. Alignment invariants:
- portfolio and benchmark series must be aligned by date under `STRICT_INTERSECTION`.
3. Risk-free handling:
- when `include_risk_free=true`, returned series frequency must match requested output frequency.
4. Numeric policy:
- return values should be decimal-safe in transport and calculation pipelines; no silent binary-float precision loss for monetary-dependent transforms.
5. Reproducibility:
- identical request and upstream data versions must yield semantically identical output and the same `calculation_hash`.
6. Composite benchmark support:
- component weights/rebalances must be applied using effective-dated benchmark definition.
- daily composite return must be computed from component returns/weights under declared methodology.
7. Single-index benchmark support:
- if benchmark currency matches reporting currency, benchmark return equals index return for selected convention.
- if currencies differ, explicit fx normalization must be applied and reported in diagnostics.

## 9. Scalability and Operability Requirements
1. Latency objectives:
- P95 <= 400ms for 1Y daily portfolio-only request under warm cache.
- P95 <= 700ms for 1Y daily portfolio + benchmark request.
2. Caching:
- request fingerprint based deterministic cache key, bounded TTL, policy-aware.
3. Observability:
- metrics for latency, cache hit ratio, upstream call failures, gap frequency, policy usage.
4. Safety:
- upper bounds on maximum date span and point count; return `UNSUPPORTED_CONFIGURATION` when limits exceeded.
5. Series persistence:
- computed portfolio/benchmark/risk-free series must be persisted for downstream reuse (including future composite analytics).
6. Historical lock policy:
- support configurable lock horizon (for example T+90 calendar days) after which series are immutable by default reads.
7. Restatement governance:
- if backdated corrections are allowed, publish explicit restatement versions with lineage and approval metadata; never silently mutate locked history.

## 10. Error Contract
Platform-standard envelope with deterministic codes:
- `INVALID_REQUEST`
- `RESOURCE_NOT_FOUND`
- `INSUFFICIENT_DATA`
- `UNSUPPORTED_CONFIGURATION`
- `SOURCE_UNAVAILABLE`
- `CONTRACT_VIOLATION_UPSTREAM`

No internal stack traces in response payloads.

## 11. RFC-0067 Governance
1. Complete OpenAPI operation metadata (summary, description, tags, success + error responses).
2. Complete schema field metadata (description + realistic example).
3. Update API vocabulary inventory and keep canonical snake_case naming.
4. No alias patterns or legacy term reintroduction in contract models.

## 12. Test Strategy
1. Contract tests:
- request validation and policy constraints
- response schema and metadata guarantees
2. Integration characterization:
- upstream sourcing behavior and deterministic mapping
- benchmark/risk-free optionality and failure policies
3. Determinism tests:
- identical input + fixed upstream snapshot yields same hash and same output ordering
4. Data-quality tests:
- gap detection, fail-fast behavior, strict intersection behavior
5. Performance tests:
- baseline latency characterization for 1Y and 3Y windows

## 13. Consumer Mapping
- Primary: lotus-risk stateful risk-calculate.
- Secondary: lotus-report and lotus-gateway cross-domain analytics composition.
- Future: multi-factor and stress analytics consumers requiring canonical series payloads.

## 14. Dependencies on lotus-core
Lotus-performance stateful sourcing depends on lotus-core analytics timeseries contracts:
1. portfolio analytics timeseries
2. benchmark assignment and return series
3. risk-free reference series

For benchmark/risk-free, lotus-performance requires standardized upstream reference-data contracts (not precomputed benchmark performance):
1. benchmark assignment resolution (`portfolio_id` + `as_of_date` -> benchmark context)
2. benchmark definition and component reference data (single-index/composite)
3. optional risk-free reference series

See upstream dependency RFC:
- `lotus-core/docs/RFCs/RFC 062 - Reference Series Integration Contract for Benchmark and Risk-Free Data.md`

## 15. Acceptance Criteria
1. `POST /integration/returns/series` is implemented and documented.
2. Contract supports portfolio + benchmark (+ optional risk-free) series with explicit policy semantics.
3. Deterministic error mapping and correlation propagation are verified.
4. RFC-0067 gates pass.
5. CI gates pass (`lint`, `typecheck`, tests, coverage, security).
