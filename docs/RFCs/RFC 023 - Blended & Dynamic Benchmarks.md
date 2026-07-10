# RFC 023: Blended & Dynamic Benchmarks (Superseded For API Contract)

**Status:** Superseded by RFC-042 for current API contract
**Owner:** Senior Architect
**Reviewers:** Perf Engine, Risk, Platform
**Related:** All active analytics endpoints, RFC-018 (Attribution), RFC-020 (FX)

## Current Implementation Baseline

This RFC is historical design context, not current implementation truth. The supported production
contract is documented in
[`docs/technical/rfc-023-benchmark-contract-baseline.md`](../technical/rfc-023-benchmark-contract-baseline.md)
and in RFC-042.

Current lotus-performance benchmark support uses `benchmark_id`, `input_mode`, `return_source`,
`stateless_input.component_observations`, `stateless_input.component_price_points`,
`stateless_input.benchmark_return_points`, and lotus-core-sourced stateful benchmark composition.
The older free-form `benchmark_spec` request block, `POST /benchmarks/resolve` helper endpoint, and
RFC-023 dynamic blend engine plan are not implemented public API contracts.

Future dynamic benchmark work must extend the RFC-042 core-sourced benchmark architecture or define
a separately approved endpoint/use-case slice. Do not implement RFC-023 as written.

## 1\. Executive Summary

This document specifies the final design for a new, powerful **Blended & Dynamic Benchmarks Framework**. A significant number of investment strategies are not measured against a single, static index but against a **blended benchmark** (e.g., 60% equities, 40% bonds) that **rebalances periodically** or has **policy weights that change over time**. Calculating accurate active performance against such a benchmark is a complex but critical requirement.

This framework introduces a single, stateless `benchmark_spec` object that allows users to precisely define these dynamic benchmarks within any analytics request. The engine will resolve this specification into a daily series of **effective weights and returns**, accounting for scheduled rebalancing, intra-period drift, and policy changes.

This is a foundational enhancement that dramatically increases the accuracy and relevance of our entire active analytics suite (Attribution, Active Analytics, etc.). By computing the correct, time-varying benchmark, we ensure that all active metrics are meaningful and that performance attribution reconciles exactly.

## 2\. Goals & Non-Goals

### Goals

  * Provide a single, stateless specification (`benchmark_spec`) for defining blended and dynamic benchmarks.
  * Support common rebalancing policies, including periodic (monthly, quarterly), drift-based, and scheduled policy changes.
  * Resolve the specification into a daily time series of effective benchmark weights and returns.
  * Seamlessly integrate the resolved benchmark into all relevant analytics endpoints (Attribution, Active Analytics, TWR).
  * Ensure all calculations are deterministic and auditable.

### Non-Goals

  * The API will not source market data for benchmark components; the caller must provide all return series.
  * The service will not provide tools for optimizing or constructing benchmark blends.

## 3\. Methodology

The core of the framework is an engine that evolves a set of benchmark weights over time according to a defined policy.

### 3.1. Weight Evolution

The engine starts with an initial set of component weights. Between rebalancing dates, the weights are allowed to **drift** with the performance of the underlying components.

  * **Drift Calculation**: The weight of component *i* on day *t*, given the weight on the last rebalance date *b*, is:
    $$w_{i,t} = \frac{w_{i,b} \cdot \prod_{u=b+1}^{t}(1+r_{i,u})}{\sum_j w_{j,b} \cdot \prod_{u=b+1}^{t}(1+r_{j,u})}$$

### 3.2. Rebalancing Policies

On specific dates, the drifted weights are reset to their target policy weights. The rebalancing trigger is determined by the `rebalance.mode`:

  * **`NONE`**: Weights are fixed at their initial values and drift for the entire period.
  * **`M`, `Q`, `A`**: Weights are reset to their target values at the beginning of each Month, Quarter, or Year.
  * **`DRIFT`**: Weights are reset to target only when the drift of any single component exceeds a specified threshold (e.g., `max_abs_bp: 300`).
  * **`SCHEDULED`**: Weights are reset to specific, user-defined values on explicit dates, allowing for policy changes over time (e.g., moving from a 70/30 to a 60/40 blend).

### 3.3. Benchmark Return Calculation

The total benchmark return on any given day *t* is the weighted average of the component returns for that day, using the **effective weights from the prior day** ($w\_{i, t-1}$) to reflect that the return is earned on the capital weighted at the start of the day.

  * **Benchmark Daily Return**: $R^{bm}*t = \\sum\_i w^{eff}*{i, t-1} \\cdot r\_{i,t}$

## 4\. API Design

### 4.1. Request Additions (`benchmark_spec` block)

The `benchmark_spec` object can be included in any analytics request that requires a benchmark.

```json
{
  "benchmark_spec": {
    "id": "BALANCED_60_40_USD",
    "currency": "USD",
    "components": [
      { "id": "SPX_TR", "kind": "INDEX", "weight": 0.60 },
      { "id": "AGG_TR", "kind": "INDEX", "weight": 0.40 }
    ],
    "rebalance": {
      "mode": "Q",
      "day": "START"
    },
    "data": {
      "series": [
        {"id": "SPX_TR", "observations": [ {"date": "2025-01-31", "ret": 0.021}, ... ]},
        {"id": "AGG_TR", "observations": [ {"date": "2025-01-31", "ret": 0.006}, ... ]}
      ]
    }
  }
}
```

### 4.2. Optional Helper Endpoint

A helper endpoint will be provided to allow users to resolve a benchmark independently.
`POST /benchmarks/resolve`

### 4.3. Response Additions (Attribution Example)

Analytics responses will echo the resolved benchmark's summary.

```json
{
  "benchmark": {
    "id": "BALANCED_60_40_USD",
    "return_total": 0.0512,
    "weights_eop": { "SPX_TR": 0.603, "AGG_TR": 0.397 }
  },
  "benchmark_components": [
    { "id": "SPX_TR", "weight_avg": 0.601, "return": 0.084, "contrib": 0.0506 },
    { "id": "AGG_TR", "weight_avg": 0.399, "return": 0.0015, "contrib": 0.0006 }
  ],
  "diagnostics": {
    "rebalance_events": [ { "date": "2025-04-01", "reason": "Q_START" } ]
  },
  ...
}
```

### 4.4. HTTP Semantics & Errors

  * **200 OK**: Successful computation.
  * **400 Bad Request**: Invalid `benchmark_spec` (e.g., weights don't sum to 1, unknown rebalance mode).
  * **422 Unprocessable Entity**: Request is valid, but data is insufficient (e.g., missing return series for a component).

## 5\. Architecture & Implementation Plan

1.  **Create New Module**:
      * `engine/benchmarks.py`: To house the core logic for resolving the `benchmark_spec` into a daily time series of effective weights and returns.
2.  **Integrate with Core Engines**:
      * Modify the primary analytics engines (`Attribution`, `Active Analytics`, etc.) to accept the resolved benchmark series from the new benchmark engine as their input. They will no longer directly consume static `benchmark_groups_data`.
3.  **Implement API Layer**:
      * Add the `/benchmarks/resolve` helper endpoint.
      * Modify the existing analytics endpoints to accept the `benchmark_spec` object.

## 6\. Testing & Validation Strategy

  * **Unit Tests**: The new `engine/benchmarks.py` module must achieve **100% test coverage**. Tests will validate the weight evolution formula and the logic for each rebalancing policy (`M`, `Q`, `DRIFT`, `SCHEDULED`).
  * **Integration Tests**: API-level tests will be created for the `/benchmarks/resolve` endpoint. Further tests on the `Attribution` endpoint will validate that active returns calculated using a dynamic benchmark are correct.
  * **Characterization Test**: A test will be created for a multi-year period with a 60/40 benchmark that rebalances quarterly and undergoes a policy shift to 70/30 halfway through. The resulting daily effective weights and total benchmark TWR will be validated against a reference Excel or Python notebook.
  * **Overall Coverage**: The overall project test coverage must remain at or above **95%**.

## 7\. Acceptance Criteria

The implementation of this RFC is complete when:

1.  This RFC is formally approved by all stakeholders.
2.  The `benchmark_spec` object is fully supported as an input to all relevant analytics endpoints.
3.  The benchmark engine correctly implements all specified rebalancing policies.
4.  The `Attribution` and `Active Analytics` endpoints correctly calculate active metrics against the resolved dynamic benchmark, with reconciliation checks passing.
5.  The testing and validation strategy is fully implemented, all tests are passing, and the required coverage targets are met.
6.  New documentation is added to `docs/guides/` and `docs/technical/` explaining how to define and use dynamic benchmarks.
