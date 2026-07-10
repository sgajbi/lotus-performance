# RFC 014: Cross-Cutting Consistency & Diagnostics Framework

**Status:** Final  
**Owner:** Senior Architect  
**Reviewers:** Perf Engine, Risk, Platform  
**Target Release:** v0.4.x  
**Related:** RFC-015, RFC-016, RFC-017, RFC-018; Existing endpoints: `/performance/twr`, `/performance/mwr`, `/contribution`, `/performance/attribution`

## 1\. Executive Summary

This document outlines the final specification for a foundational refactor to unify the API surface of our four core performance endpoints: **TWR, MWR, Contribution, and Attribution**. The primary goal is to introduce a shared request envelope and response footer, establishing consistent, predictable behavior for clients. This framework will centralize common controls like precision, period definition, and annualization, and introduce a robust diagnostics and audit block in all responses.

This initiative strengthens correctness, enhances configurability, improves observability, and provides a coherent foundation for the specific enhancements planned in RFCs 015–018, all without introducing breaking changes to existing clients.

-----

## 2\. Current State Analysis

An analysis of the current `sgajbi-lotus-performance` repository reveals a mature but inconsistent API surface across its primary services.

  * **Inconsistent API Contracts:** The request and response models for `/performance/twr`, `/performance/mwr`, `/performance/contribution`, and `/performance/attribution` have evolved independently. They lack common fields for controlling fundamental calculation parameters.
  * **Limited Configurability:** Clients cannot control crucial aspects like calculation precision, annualization logic, or calendar conventions directly via the API.
  * **Minimal Diagnostics:** When calculations succeed but encounter edge cases (e.g., applying a No-Investment-Period rule), this information is not transparently surfaced to the client, complicating validation and debugging.
  * **Lack of Auditability:** Responses do not contain metadata about the calculation itself, such as the engine version, effective dates used, or reconciliation checks, making them difficult to audit.

This RFC directly addresses these gaps by creating a shared, robust framework that all four endpoints will adopt.

-----

## 3\. Design Principles

  * **Consistency:** A client should learn one API pattern and be able to apply it to all performance endpoints. Common parameters should have identical names, structures, and behavior.
  * **Observability:** Every calculation should be auditable and debuggable via the response payload. The `meta`, `diagnostics`, and `audit` blocks are designed to make the engine's behavior transparent.
  * **Configurability:** Common calculation "knobs" that affect multiple endpoints should be exposed uniformly and controlled by the client on a per-request basis.
  * **Backward Compatibility:** The introduction of this framework must **not break existing clients**. All new request fields will be optional, and their default values will replicate the current, established behavior of the endpoints.

-----

## 4\. Target Architecture & Implementation

To implement this shared framework, new, decoupled modules will be created in a top-level `core/` directory, ensuring they can be reused by any component without creating circular dependencies.

### 4.1 New Module Structure

```
core/
  envelope.py           # Pydantic mixins for shared request/response models.
  periods.py            # A unified, vectorized period resolution engine.
  annualize.py          # Common helpers for annualizing returns.
  errors.py             # Shared error taxonomy and custom exceptions.

app/models/
  twr.py                # Will be updated to use mixins from core/envelope.py
  mwr.py                # "
  contribution.py       # "
  attribution.py        # "
```

### 4.2 Shared Request Envelope

A `SharedRequestEnvelope` Pydantic model will be defined in `core/envelope.py`. All four endpoint request models will inherit from it.

```jsonc
// core/envelope.py (conceptual)
{
  "as_of": "2025-08-31",
  "currency": "USD",
  "precision_mode": "FLOAT64",           // "FLOAT64" | "DECIMAL_STRICT"
  "rounding_precision": 6,

  "calendar": {                           // optional; default BUSINESS
    "type": "BUSINESS",                   // "BUSINESS" | "NATURAL"
    "trading_calendar": "NYSE"            // optional, for future use
  },

  "annualization": {                      // optional; controls annualization logic
    "enabled": false,
    "basis": "BUS/252",                   // "BUS/252" | "ACT/365" | "ACT/ACT"
    "periods_per_year": 252               // optional override for basis
  },

  "periods": {                            // optional; normalized period service
    "type": "EXPLICIT",                   // YTD|QTD|MTD|WTD|Y1|Y3|Y5|ITD|ROLLING|EXPLICIT
    "explicit": {"start": "2025-01-01", "end": "2025-08-31"},
    "rolling": {"months": 12}
  },

  "output": {                             // optional; controls output shape
    "include_timeseries": false,
    "include_cumulative": false,
    "top_n": 20
  },

  "flags": {                              // optional; behavioral flags
    "fail_fast": false                    // convert governed warning/degraded completed responses to HTTP 422 when true
  }
}
```

### 4.3 Shared Response Footer

A `SharedResponseFooter` model will be defined. All four endpoint response models will include it.

```jsonc
// core/envelope.py (conceptual)
{
  // ... endpoint-specific data ...
  "meta": {
    "calculation_id": "uuid",
    "engine_version": "0.4.0",
    "precision_mode": "FLOAT64",
    "annualization": {"enabled": false, "basis": "BUS/252"},
    "calendar": {"type": "BUSINESS", "trading_calendar": "NYSE"},
    "periods": {"type": "EXPLICIT", "start": "2025-01-01", "end": "2025-08-31"}
  },
  "diagnostics": {
    "nip_days": 2,
    "reset_days": 1,
    "effective_period_start": "2025-01-02",
    "notes": ["NIP rule V2 applied", "BMV+CF=0 on 2025-03-15"]
  },
  "audit": {
    "sum_of_parts_vs_total_bp": 0.1,
    "residual_applied_bp": 0.0,
    "counts": {"cashflow_days": 9, "fee_days": 3}
  }
}
```

### 4.4 Error Taxonomy

The shared error taxonomy will be implemented in `core/errors.py` and used by the exception handlers in `app/core/handlers.py`.

  * **400 Bad Request**: For validation errors (e.g., schema mismatch, inconsistent dates).
  * **422 Unprocessable Entity**: For requests that are syntactically valid but logically un-processable with the given data (e.g., MWR calculation that fails to converge).
  * **Warnings**: Non-critical issues (e.g., a fallback was used) will be added to
    `diagnostics.notes` or endpoint-specific supportability fields. If `flags.fail_fast` is true,
    completed TWR, MWR, Contribution, and Attribution responses with governed warning, fallback,
    diagnostic-note, degraded supportability, or supportability-reason evidence return HTTP `422`
    with `error_code=FAIL_FAST_SOFT_WARNING` instead of returning a `200` degraded result. Initial
    async `202 Accepted` envelopes are not rejected before execution completes.

-----

## 5\. Implementation Plan

The project will be executed in phases to ensure correctness at each step.

  * **Phase 1: Foundational Modules**

    1.  Create the new `core/` directory.
    2.  Implement `core/envelope.py`, defining the Pydantic models for the shared request and response sections.
    3.  Implement `core/periods.py`, creating the logic to resolve all period types (`YTD`, `ROLLING`, etc.) into start and end dates.
    4.  Implement `core/annualize.py` with helpers to apply various annualization conventions.
    5.  Implement `core/errors.py` with the new error taxonomy.
    6.  Ensure all new modules have 100% unit test coverage.

  * **Phase 2: API & Engine Integration**

    1.  Refactor the request/response models for TWR, MWR, Contribution, and Attribution in `app/models/` to inherit from the shared models in `core/envelope.py`.
    2.  Create a typed `Context` object that flows from the API layer down into the engine, carrying the new configuration settings (precision, periods, annualization).
    3.  Update the API endpoints in `app/api/endpoints/` to populate the `Context` from the request and to construct the shared response footer with metadata from the calculation.
    4.  Refactor the engine functions (e.g., `engine.compute.run_calculations`) to accept the `Context` and apply the specified logic (e.g., use `core/periods.py` to determine date ranges).

-----

## 6\. Testing & Validation Strategy

  * **Unit Tests:** All new functions within the `core/` modules must have 100% unit test coverage. This includes tests for every period type, annualization basis, and precision mode.
  * **Integration Tests:** New integration tests will be added for each of the four endpoints to specifically validate the new envelope functionality. For example, a test will call the TWR endpoint with `annualization.enabled=true` and assert that the result is correctly annualized.
  * **Backward Compatibility Tests:** All existing integration tests for the four endpoints will be run against the new code. They must continue to pass without modification to prove that the default behavior remains unchanged, satisfying the backward compatibility requirement.

-----

## 7\. Acceptance Criteria

The implementation of this RFC will be considered complete when the following criteria are met:

1.  All new modules (`core/envelope.py`, `core/periods.py`, `core/annualize.py`, `core/errors.py`) are created and have 100% unit test coverage.
2.  The four endpoints (`/performance/twr`, `/performance/mwr`, `/contribution`, `/performance/attribution`) correctly process requests containing the new shared envelope fields and return responses containing the new shared footer.
3.  All existing integration tests pass, confirming backward compatibility.
4.  New integration tests that specifically target the new functionality (e.g., annualization, rolling periods) pass successfully.
5.  All relevant documentation in the `docs/` directory, especially `docs/guides/api_reference.md`, is updated to reflect the new shared API parameters and response blocks for all four endpoints.
6.  This RFC is formally approved by project stakeholders via a pull request review **before** the first line of code for Phase 1 is merged.
