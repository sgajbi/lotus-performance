# RFC 022: Composite & Sleeve Aggregation API (Historical)

**Status:** Superseded by RFC 049 for execution planning
**Owner:** Senior Architect
**Reviewers:** Perf Engine, Risk, Platform, Compliance
**Related:** All core analytics endpoints, RFC-025 (Reproducibility), RFC-049

## Supersession Notice

RFC 022 is retained as historical context only. It is not the current implementation plan for
composite performance.

RFC 049 is the approved execution artifact for composite performance because it reflects the current
Lotus architecture, platform governance, and data-mesh standards. RFC 049 replaces the RFC 022
assumption that composite analytics can be delivered as stateless `/composites/*` wrappers over all
core engines. The approved direction is:

1. composite performance starts with composite TWR, not broad composite MWR, contribution,
   attribution, or sleeve/carve-out promotion;
2. composite calculation requires explicit source authority, effective-dated membership governance,
   persisted member-return facts, batch/recalculation controls, lineage, inspector support, exports,
   and data-product certification;
3. composite support remains unsupported until RFC 049 is implemented, validated, documented, and
   promoted through implementation-backed supported-feature material.

Do not implement RFC 022 directly. Use RFC 049 for all composite-performance delivery decisions.

## 1\. Executive Summary

This document specifies the final design for a new, enterprise-grade **Composite & Sleeve Aggregation** capability. This feature is a major evolution of the platform, extending its analytical power from individual portfolios to firm-level, strategy-based composites. This is a critical requirement for asset management firms seeking to report performance in a manner consistent with the Global Investment Performance Standards (GIPS).

The framework introduces a new set of endpoints under `/composites/*` that wrap our core analytics engines (TWR, MWR, Contribution, Attribution). It allows users to define a composite's membership, including rules for inclusion/exclusion, significant cash flows, and discretionary status. The engine supports the two primary GIPS-accepted calculation methods: the **Aggregate Method** (building a single virtual portfolio) and the **Asset-Weighted Average Method**.

This API will produce not only the composite's performance but also key GIPS-aware statistics like the number of portfolios, composite assets, and return dispersion. This is a foundational feature for institutional-level reporting, providing a robust, auditable, and reproducible way to aggregate performance across a firm's strategies.

## 2\. Goals & Non-Goals

### Goals

  * Provide a stateless API to aggregate performance and analytics for a group of portfolios (a composite).
  * Support both the **Aggregate** and **Asset-Weighted Average** calculation methods.
  * Implement GIPS-aware rules for portfolio inclusion/exclusion and significant cash flows.
  * Calculate and return standard composite statistics, including asset-weighted return dispersion.
  * Handle **sleeves (carve-outs)** with dedicated cash allocations.
  * Apply consistently across TWR, MWR, Contribution, and Attribution.

### Non-Goals

  * The API will not serve as a persistent, firm-wide registry of composites.
  * It will not automatically generate GIPS-compliant marketing presentations or disclosures.
  * It is not a substitute for a firm's formal compliance system but provides the necessary calculation tools.

## 3\. Methodology

The engine follows a multi-step process: first resolving the composite's membership for the period, then calculating the result using the chosen method.

### 3.1. Membership Resolution

For each period, the engine determines which member portfolios are included in the composite based on a set of rules:

  * **Eligibility**: A portfolio must be marked as `discretionary` (if required), be within its `join` and `leave` dates, and meet any `min_aum` threshold.
  * **Significant Cash Flow (SCF) Policy**: If a portfolio experiences a cash flow exceeding a percentage threshold, it can be temporarily excluded for that period to avoid distorting performance, as defined by the `scf_policy.treatment`.

### 3.2. Composite Calculation Methods

  * **Aggregate Method (Default)**: This method is the most robust. The engine constructs a single **virtual composite portfolio** by summing the market values, cash flows, and fees of all included members on a daily basis. The standard TWR (or other) calculation is then run on this single, aggregated data panel. This naturally handles all intra-period cash flows and membership changes.
  * **Asset-Weighted Average Method**: This method calculates the return for each member portfolio individually for a given period (e.g., monthly). The composite's return for that period is then the asset-weighted average of the individual member returns. The weights are typically the beginning-of-period market values. These periodic composite returns are then geometrically linked to get the total return.

### 3.3. Sleeve (Carve-Out) Handling

For sleeves to be compliant, they must be managed with their own cash allocation. The `cash_allocation_method` in the request ensures this is handled correctly. If `exclude_from_parent` is true, the sleeve's assets and flows are removed from the parent account's data before it is considered for any composite, preventing double-counting.

### 3.4. GIPS-Aware Statistics

  * **Dispersion**: For any period where the composite contains a minimum number of portfolios (e.g., 6), the engine calculates the cross-sectional standard deviation of the member returns to measure how consistently the strategy was applied.

## 4\. API Design

### 4.1. Endpoints

A new set of wrapper endpoints will be created:

  * `POST /composites/twr`
  * `POST /composites/mwr`
  * `POST /composites/contribution`
  * `POST /composites/attribution`

### 4.2. Request Schema (Pydantic)

```json
{
  "as_of": "2025-12-31",
  "periods": { "type": "YTD" },
  "composite": {
    "id": "GLOBAL_EQUITY_USD",
    "method": "AGGREGATE",
    "currency": "USD",
    "members": [
      {
        "portfolio_id": "PORT_001",
        "join": "2023-01-01",
        "leave": null,
        "discretionary": true,
        "min_aum": 1000000,
        "scf_policy": {
          "enabled": true,
          "threshold_pct": 10.0,
          "treatment": "TEMP_EXCLUDE"
        }
      }
    ],
    "gips": { "compliant": true }
  },
  "twr": { /* The underlying TWR request for the aggregated data */
    "metric_basis": "NET",
    "frequencies": ["monthly", "yearly"]
  }
}
```

### 4.3. Response Schema (TWR Example)

```json
{
  "composite_id": "GLOBAL_EQUITY_USD",
  "method": "AGGREGATE",
  "currency": "USD",
  "summary": {
    "n_portfolios": 14,
    "composite_assets_eop": 487000000.00,
    "return_period": 0.0841,
    "three_year_ann_stddev": 0.164,
    "dispersion": {
      "stddev_equal_weight": 0.021,
      "min": -0.041,
      "max": 0.112
    }
  },
  "membership": {
    "included": [ { "portfolio_id": "PORT_001", "weight_bop": 0.083, "reason": "OK" } ],
    "excluded": [ { "portfolio_id": "PORT_099", "reason": "SCF_TEMP_EXCLUDE" } ]
  },
  "breakdowns": { /* Standard TWR breakdowns for the composite */ },
  "meta": { ... },
  "diagnostics": { ... },
  "audit": { ... }
}
```

### 4.4. HTTP Semantics & Errors

  * **200 OK**: Successful computation.
  * **400 Bad Request**: Invalid composite specification.
  * **409 Conflict**: An exclusivity violation is detected (e.g., a portfolio is in two composites where it should not be).
  * **422 Unprocessable Entity**: Request is valid, but data is insufficient (e.g., no members qualify for the period).

## 5\. Architecture & Implementation Plan

1.  **Create New Modules**:
      * `engine/composite.py`: To house the logic for membership resolution, panel aggregation, and dispersion calculation.
      * `app/models/composite_common.py`: To define the shared request/response models.
      * `app/api/endpoints/composites.py`: To define the new `/composites/*` router and endpoints.
2.  **Implementation**: The composite endpoints will act as wrappers. They will first call the `engine/composite.py` module to resolve membership and create the single, aggregated data panel. This panel will then be passed to the existing single-portfolio engines (`engine/compute.py`, `engine/attribution.py`, etc.) for the final calculation.

## 6\. Testing & Validation Strategy

  * **Unit Tests**: The new `engine/composite.py` module must achieve **100% test coverage**. This includes tests for all membership rules (join/leave, SCF, min AUM), the two aggregation methods, and sleeve cash allocation logic.
  * **Integration Tests**: API-level tests will be created for each of the four `/composites/*` endpoints, validating the end-to-end flow and the GIPS-aware summary statistics.
  * **Characterization Test**: A test will be created for a multi-portfolio composite over several years with membership changes. The output will be validated against a reference calculation from a GIPS-compliant system or a detailed reference spreadsheet.
  * **Overall Coverage**: The overall project test coverage must remain at or above **95%**.

## 7\. Acceptance Criteria

The implementation of this RFC is complete when:

1.  This RFC is formally approved by all stakeholders.
2.  All new modules and endpoints are created and fully integrated.
3.  The `/composites/twr` endpoint is fully functional, supporting both aggregation methods and all specified GIPS-aware logic.
4.  The other composite endpoints (`mwr`, `contribution`, `attribution`) are functional using the `Aggregate Method`.
5.  The testing and validation strategy is fully implemented, all tests are passing, and the required coverage targets are met.
6.  New documentation is added to `docs/guides/` and `docs/technical/` for the Composite Aggregation API.
