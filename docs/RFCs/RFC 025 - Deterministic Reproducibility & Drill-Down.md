# RFC 025: Reproducibility & Drill-Down Framework (Final)

**Status:** Final
**Owner:** Senior Architect
**Date:** September 8, 2025
**Related:** All core analytics endpoints, RFC-024 (Robustness)

## 1\. Executive Summary

This document specifies the final design for a new, platform-wide **Reproducibility & Drill-Down Framework**. To be considered enterprise-grade, our analytics must be transparent, auditable, and perfectly reproducible. This framework introduces the foundational components to achieve this by moving to an **asynchronous store-and-retrieve** model for data lineage.

Two main features will be implemented:

1.  A **Deterministic Calculation Hash**: A unique, verifiable fingerprint (`calculation_hash`) will be included in every API response. This hash is a pure function of all inputs, settings, and the engine version, providing an immutable link between a request and its result.
2.  **Async Data Lineage Capture**: After a successful calculation, a background task will capture the original request, the final response, and a detailed breakdown of all intermediate daily calculations. This data bundle will be stored and linked to the unique `calculation_id`. A new endpoint will provide URLs to retrieve these artifacts, allowing users to review every calculation detail in CSV format.

This framework moves our service beyond being a "black box" calculator to a transparent and trustworthy analytical engine.

-----

## 2\. Goals & Non-Goals

### Goals

  * Ensure all calculations are deterministic and can be exactly reproduced.
  * Introduce a `calculation_hash` in all API responses for audit and caching purposes.
  * Asynchronously capture a complete lineage bundle (request, response, detailed calculations) for every request.
  * Provide a standardized, secure endpoint to retrieve URLs for downloading the lineage artifacts.
  * Ensure the lineage capture process has no performance impact on the primary API response time.

### Non-Goals

  * The v1 storage mechanism will be the local filesystem; a migration to a dedicated cloud storage service is a future enhancement.
  * The lineage retrieval endpoint will provide URLs but will not handle user authentication or authorization in v1.

-----

## 3\. Methodology

### 3.1. Canonicalization & Hashing

To guarantee that the same logical request always produces the same result and hash, all inputs are first converted into a canonical string format before hashing.

  * **Canonicalization Rules**: A strict set of rules is applied to the request payload, including sorting all object keys, normalizing timestamps, and standardizing number formats. Arrays are intentionally preserved in request order because valuation points, cash flows, benchmark observations, period lists, and lineage rows can carry source sequence, business ordering, or evidence ordering semantics. Order-insensitive behavior is allowed only when an endpoint mapper explicitly sorts a named field by a stable business key before hashing.
  * **Calculation Hash**: The final hash is calculated as `sha256(canonical_json(request) + engine_version)`. Including the engine version ensures that if the underlying logic changes, the hash also changes.

### 3.2. Data Lineage Capture & Retrieval

The drill-down capability is achieved by storing and retrieving a complete record of the calculation.

  * **Asynchronous Capture**: Immediately after a successful API response is sent to the user, a `BackgroundTask` is executed. This task takes the original request, the final response, and the detailed intermediate DataFrame(s) from the engine. It serializes them to JSON and CSV formats and saves them to a storage location using the `calculation_id` as the unique identifier. This ensures no impact on API latency.
  * **Artifact Granularity**: The framework will create multiple CSV files as needed to provide full transparency. For example, a multi-level contribution calculation will generate separate CSVs for the portfolio's TWR details, the daily contributions of each position, and summary data for each hierarchy level.
  * **URL-Based Retrieval**: A separate endpoint allows users to retrieve the locations of these stored artifacts. It does not return the data directly but provides URLs for download, decoupling the API from the storage and download process.

-----

## 4\. API Design

### 4.1. Request & Response Additions

The `meta` block in all primary API responses will be extended to include the `calculation_hash`.

**Response Addition:**

```json
{
  "meta": {
    "calculation_id": "a4b7e289-7e28-4b7e-8e28-7e284b7e8e28",
    "calculation_hash": "sha256:5a2c...",
    "input_fingerprint": "sha256:b3e1...",
    "engine_version": "0.5.0"
  }
}
```

### 4.2. Lineage Endpoint

A new endpoint will be created to retrieve the artifact URLs.

  * `GET /performance/lineage/{calculation_id}`

### 4.3. Lineage Response Schema

The lineage endpoint will respond with a JSON object containing a dictionary of artifact names and their corresponding download URLs. The keys will vary depending on the calculation type.

**Example for TWR:**

```json
{
  "calculation_id": "a4b7e289-7e28-4b7e-8e28-7e284b7e8e28",
  "calculation_type": "TWR",
  "timestamp_utc": "2025-09-08T12:45:00Z",
  "artifacts": {
    "request_payload.json": "http://[hostname]/lineage/a4b7.../request.json",
    "response_payload.json": "http://[hostname]/lineage/a4b7.../response.json",
    "twr_calculation_details.csv": "http://[hostname]/lineage/a4b7.../twr_calculation_details.csv"
  }
}
```

**Example for MWR:**

```json
{
  "calculation_id": "c6d9e4a1-9e4a-4d9a-a9e4-9e4a4d9aa9e4",
  "calculation_type": "MWR",
  "timestamp_utc": "2025-09-08T12:47:00Z",
  "artifacts": {
    "request_payload.json": "http://[hostname]/lineage/c6d9.../request.json",
    "response_payload.json": "http://[hostname]/lineage/c6d9.../response.json",
    "mwr_cashflow_schedule.csv": "http://[hostname]/lineage/c6d9.../mwr_cashflow_schedule.csv"
  }
}
```

**Example for Multi-Level Contribution:**

```json
{
  "calculation_id": "b5c8f390-8f39-4c8e-9f39-8f394c8e9f39",
  "calculation_type": "Contribution",
  "timestamp_utc": "2025-09-08T12:50:00Z",
  "artifacts": {
    "request_payload.json": "http://[hostname]/lineage/b5c8.../request.json",
    "response_payload.json": "http://[hostname]/lineage/b5c8.../response.json",
    "portfolio_twr.csv": "http://[hostname]/lineage/b5c8.../portfolio_twr.csv",
    "positions_daily_contribution.csv": "http://[hostname]/lineage/b5c8.../positions_daily_contribution.csv",
    "level_1_sector_summary.csv": "http://[hostname]/lineage/b5c8.../level_1_sector_summary.csv"
  }
}
```

**Example for Attribution:**

```json
{
  "calculation_id": "d8e1a2b3-a2b3-4e1a-b2b3-a2b34e1ab2b3",
  "calculation_type": "Attribution",
  "timestamp_utc": "2025-09-08T12:52:00Z",
  "artifacts": {
    "request_payload.json": "http://[hostname]/lineage/d8e1.../request.json",
    "response_payload.json": "http://[hostname]/lineage/d8e1.../response.json",
    "aligned_panel.csv": "http://[hostname]/lineage/d8e1.../aligned_panel.csv",
    "single_period_effects.csv": "http://[hostname]/lineage/d8e1.../single_period_effects.csv"
  }
}
```

### 4.4. HTTP Semantics & Errors

  * **200 OK**: Successful retrieval of artifact URLs.
  * **404 Not Found**: The lineage data for the given `calculation_id` does not exist, either because the ID is invalid or the background task has not yet completed.

-----

## 5\. Architecture & Implementation Plan

1.  **Create Canonicalization Module**: Develop a utility in `core/repro.py` to produce a canonical JSON string from a Pydantic model.
2.  **Create Lineage Service & Storage Abstraction**: Implement `app/services/lineage_service.py` and a storage interface that initially targets the local filesystem.
3.  **Integrate Hashing & Async Tasks**: Modify all primary API endpoints to generate the `calculation_hash` and to schedule the `lineage_service.capture()` method as a `BackgroundTask`.
4.  **Implement Lineage Endpoint**: Create a new router `app/api/endpoints/lineage.py` with the `GET /performance/lineage/{calculation_id}` endpoint. This endpoint will interact with the storage layer to generate and return the artifact URLs.

-----

## 6\. Testing & Validation Strategy

  * **Unit Tests**: The new `core/repro.py` and `app/services/lineage_service.py` modules must have **100% test coverage**. This includes testing deterministic object-key canonicalization, ordered-array sensitivity for sequence-bearing request evidence, and the serialization to JSON and CSV formats.
  * **Integration Tests**:
      * Add tests to assert that primary API responses now contain the `calculation_hash`.
      * Add tests for the lineage endpoint, including a happy path test and a `404 Not Found` test.
      * An end-to-end test will perform a calculation, then immediately call the lineage endpoint to verify that the correct artifact URLs are returned.
  * **Property-Based Testing**: Use property-based tests only for fields with an explicit schema-aware business-key sorting rule. The current general canonicalizer must prove that shuffling sequence-bearing input arrays changes the final `calculation_hash` rather than silently treating ordered evidence as an unordered set.
  * **Overall Coverage**: Overall project test coverage must remain at or above **95%**.

-----

## 7\. Acceptance Criteria

The implementation of this RFC is complete when:

1.  This RFC is formally approved.
2.  All primary analytics endpoints include the `calculation_hash` in their response `meta` block.
3.  The hashing logic is proven to be deterministic: object-key order is canonicalized, ordered arrays remain part of hash identity, and any future order-insensitive field has an explicit business-key sorting rule plus tests.
4.  A background task successfully captures and stores the request, response, and detailed calculation CSV(s) for all primary analytics types.
5.  The new `GET /performance/lineage/{calculation_id}` endpoint is implemented and correctly returns a JSON payload with URLs for all stored artifacts.
6.  The testing and validation strategy is fully implemented, all tests pass, and coverage targets are met.
7.  New documentation is added to the `docs/` directory explaining the reproducibility framework and how to use the lineage endpoint, ensuring project documentation stays current.
