# RFC 020: Multi-Currency & FX-Aware Analytics (Final)

**Status:** Final (For Approval)
**Owner:** Senior Architect
**Reviewers:** Perf Engine, Risk, Platform
**Related:** All core analytics endpoints, RFC-014 (Envelope), RFC-025 (Reproducibility)

**Current implementation note:** RFC-020 is the strategic target, but endpoint support is currently
bounded and endpoint-specific. Use
[`docs/technical/rfc-020-multi-currency-support-matrix.md`](../technical/rfc-020-multi-currency-support-matrix.md)
as the canonical current support matrix before changing or consuming currency vocabulary.

## 1\. Executive Summary

This document specifies the final design for a comprehensive **Multi-Currency & FX-Aware Analytics** framework. Real-world portfolios hold assets in multiple currencies, and a significant portion of their return and risk comes from foreign exchange rate movements. This RFC extends our entire suite of analytics—TWR, MWR, Contribution, and Attribution—to correctly handle, decompose, and report on the effects of currency.

The core of this enhancement is to decompose every instrument's return into its **local performance** and its **FX contribution**. This framework will be integrated into all existing engines, allowing users to see a clear `local | fx | base` return split for any portfolio. It also introduces a powerful **currency attribution** model (based on Karnosky-Singer) to explain active returns driven by currency decisions.

The API is designed for maximum flexibility and is **fully backward-compatible**. The new functionality is opt-in, ensuring that existing integrations continue to work without modification. This is a foundational upgrade that transforms our service into a true multi-currency analytics platform.

-----

## 2\. Goals & Non-Goals

### Goals

  * Decompose TWR and Contribution into **local, FX, and base currency** components.
  * Provide a robust **currency attribution** model to explain active returns.
  * Support configurable modeling for **currency hedging**.
  * Ensure all calculations are stateless and auditable, integrating with the reproducibility framework.
  * Apply currency awareness consistently across all four core analytics endpoints.

### Non-Goals

  * The API will not source FX rates or other market data; the caller must provide it.
  * Advanced currency options hedging is out of scope for v1.

-----

## 3\. Methodology

The framework is built on the daily decomposition of returns for each instrument.

### 3.1. Core Return Decomposition

For any instrument *j* held in a local currency *c(j)*, its return in the base (reporting) currency, $r^B$, is a combination of its local return, $r^L$, and the return of its currency against the base, $r^X$.

  * **Base Return Formula**:
    $$(1 + r^B_{j,t}) = (1 + r^L_{j,t}) \cdot (1 + r^X_{c(j),t})$$
    This can be approximated as $r^B \\approx r^L + r^X$. The engine calculates the `fx_contribution` for each instrument daily and aggregates it using the same Carino-smoothed linking as the core TWR engine to ensure the components perfectly sum to the total base return.

### 3.2. Modeling Currency Hedges

The framework provides two distinct, mutually exclusive methods for accounting for the impact of currency hedging. The caller must choose one approach to avoid double-counting the hedging effect.

#### Method 1: The Modeling Approach (Using `hedge_ratio`)

This is a high-level approach that models the *net economic effect* of a hedging strategy without requiring the detailed performance of the specific instruments used.

  * **How it Works:** The caller provides a `hedge_ratio` ($h\_t$) between 0.0 and 1.0, representing the portion of the currency exposure that is neutralized. The engine uses this ratio to calculate the *effective* FX return.
    $$r^X_{eff} = (1 - h_t) \cdot r^X_t$$
  * **Caller Responsibility:** When using this method, the caller **must exclude** the specific hedging instruments (e.g., forward contracts, futures) from the `positions_data` array. Providing both will result in double-counting and incorrect results.
  * **Use Case:** Ideal for analyzing the intended impact of a hedging strategy (e.g., "analyze this portfolio assuming a 50% hedge on EUR exposure") without the complexity of modeling individual forward contracts.

#### Method 2: The Explicit Approach (Providing Hedging Instruments)

This is a bottom-up approach that calculates the effect of hedging based on the actual performance of the hedging instruments themselves.

  * **How it Works:** The caller provides the hedging instruments (e.g., a currency forward contract) as individual line items within the `positions_data` array, complete with their own daily market values and cash flows.
  * **Caller Responsibility:** When using this method, the caller **must not** provide a `hedge_ratio` for the currency being hedged (or must set it to `0`).
  * **Use Case:** Ideal when a precise, instrument-by-instrument accounting of all positions is required and the performance data for the specific hedging instruments is available. The engine will naturally compute the offsetting gains or losses from these positions, correctly reflecting their impact in the portfolio's total base currency return.

### 3.3. Currency Attribution

For the Attribution endpoint, the engine implements a Karnosky-Singer style model that decomposes the total active return into four components for each currency bucket *i*:

1.  **Local Allocation (LA)**: Active return from allocating to different local markets.
    $$LA_i = (w^p_i - w^b_i) \cdot r^L_{b,i}$$
2.  **Local Selection (LS)**: Active return from selecting securities within local markets.
    $$LS_i = w^b_i \cdot (r^L_{p,i} - r^L_{b,i})$$
3.  **Currency Allocation (CA)**: Active return from overweighting/underweighting currencies.
    $$CA_i = (w^p_i - w^b_i) \cdot (1+r^L_{b,i}) \cdot r^X_i$$
4.  **Currency Selection (CS)**: A cross-product effect capturing the interaction between local returns and currency movements.
    $$CS_i = w^b_i \cdot (r^L_{p,i} - r^L_{b,i}) \cdot (1+r^X_i)$$

-----

## 4\. API Design

The multi-currency functionality is **opt-in** and designed to be fully backward-compatible.

  * **Standard Mode (Default):** If the `currency_mode` and `report_ccy` fields are omitted from a request, the engine will perform its standard, base-currency-only calculation. No changes are required for existing clients.
  * **Multi-Currency Mode (Activated):** To enable the decomposition, the client must include the `currency_mode`, `report_ccy`, and `fx` blocks in the request. In this mode, all monetary values provided in `daily_data` for each position are expected to be in that position's specified local currency.

### 4.1. Request Format

The following new blocks are added to the shared request envelope for all relevant endpoints.

```jsonc
// Example for a Contribution Request in Multi-Currency Mode
{
  "portfolio_id": "MULTI_CCY_01",
  "portfolio_data": { /* ... portfolio totals, values in base currency ... */ },
  "positions_data": [
    {
      "position_id": "NESTLE_CHF",
      "meta": {
        "sector": "Consumer Staples",
        "currency": "CHF" // Specify the asset's local currency
      },
      "daily_data": [
        // All monetary values below are in the local currency (CHF)
        { "day": 1, "perf_date": "2025-09-07", "begin_mv": 50000, "end_mv": 50250 }
      ]
    },
    {
      "position_id": "SONY_JPY",
      "meta": {
        "sector": "Technology",
        "currency": "JPY" // Specify the asset's local currency
      },
      "daily_data": [
        // All monetary values below are in the local currency (JPY)
        { "day": 1, "perf_date": "2025-09-07", "begin_mv": 8000000, "end_mv": 8040000 }
      ]
    }
  ],

  // --- Multi-Currency Activation and Data Blocks ---
  "currency_mode": "BOTH", // Required. Options: "BASE_ONLY", "LOCAL_ONLY", "BOTH"
  "report_ccy": "USD",     // Required. The portfolio's base reporting currency.
  "fx": {
    "source": "CLIENT_SUPPLIED",
    "fixing": "EOD",
    "rates": [ // Required. Daily FX rates for all foreign currencies against the base.
      { "date": "2025-09-07", "ccy": "CHF", "rate": 1.1250 },
      { "date": "2025-09-07", "ccy": "JPY", "rate": 0.0068 }
    ]
  },
  "hedging": { // Optional.
    "mode": "RATIO",
    "series": [
      { "date": "2025-09-07", "ccy": "CHF", "hedge_ratio": 0.50 } // Hedge 50% of the CHF exposure
    ]
  }
}
```

### 4.2. Response Format

The response for each endpoint will be enhanced to include the currency decomposition.

```jsonc
// Example for a TWR Response in Multi-Currency Mode
{
  "calculation_id": "a4b7e289-7e28-4b7e-8e28-7e284b7e8e28",
  "portfolio_id": "MULTI_CCY_01",

  // --- New Multi-Currency Response Blocks ---
  "portfolio_return": {    // Decomposition of the total portfolio TWR
    "local": 0.0420,       // Return from local asset performance
    "fx": 0.0080,          // Return from currency movements
    "base": 0.050336       // Total return in the base currency (geometrically linked)
  },
  "by_currency": [         // Breakdown of contributions by currency exposure
    { "ccy": "CHF", "weight_avg": 0.45, "local_contrib": 0.021, "fx_contrib": 0.006 },
    { "ccy": "JPY", "weight_avg": 0.20, "local_contrib": -0.004, "fx_contrib": 0.001 }
  ],
  // --- Existing TWR Response Blocks ---
  "breakdowns": { /* ... standard daily/monthly breakdowns of BASE return ... */ },

  // --- Shared Response Footer ---
  "meta": {
    "report_ccy": "USD",
     /* ... other meta fields ... */
  },
  "diagnostics": { /* ... */ },
  "audit": { /* ... */ }
}
```

### 4.3. HTTP Semantics & Errors

  * **200 OK**: Successful computation.
  * **400 Bad Request**: Invalid configuration (e.g., missing `report_ccy` when `currency_mode` is active).
  * **422 Unprocessable Entity**: Request is valid, but FX data is missing for a required currency and date.

-----

## 5\. Architecture & Implementation Plan

1.  **Extend Core Engine**:
      * Modify the daily return calculation in `engine/ror.py` and the main orchestrator in `engine/compute.py` to perform the `local | fx | base` decomposition. The calculation will ingest the new `fx` and `hedging` configurations from the `EngineConfig` object.
2.  **Extend Analytics Modules**:
      * **Contribution**: Enhance `engine/contribution.py` to aggregate and report local vs. fx contributions.
      * **Attribution**: Enhance `engine/attribution.py` to compute the four Karnosky-Singer components.
3.  **Update API Layer**:
      * Add the new request and response models to the appropriate files in the `app/models/` directory.
      * Update all four endpoint functions in `app/api/endpoints/` to handle the new currency-related logic.
4.  **Phased Rollout**:
      * **Phase 1**: Implement the TWR and Contribution extensions.
      * **Phase 2**: Implement the more complex Currency Attribution.
      * **Phase 3**: Implement the MWR FX decomposition.

-----

## 6\. Testing & Validation Strategy

  * **Unit Tests**: The modified engine modules (`ror.py`, `contribution.py`, `attribution.py`) must achieve **100% test coverage**. This will include tests for the base return identity ($1+r^B = (1+r^L)(1+r^X)$), both hedging approaches, and each of the four currency attribution formulas.
  * **Integration Tests**: API-level tests will be created for each of the four main endpoints to validate the end-to-end multi-currency workflow.
  * **Characterization Test**: A test will be created for a multi-currency portfolio, validating the TWR `local|fx|base` split and the full currency attribution breakdown against a reference calculation from a Jupyter notebook.
  * **Overall Coverage**: The overall project test coverage must remain at or above **95%**, consistent with project standards.

-----

## 7\. Acceptance Criteria

The implementation of this RFC is complete when:

1.  This RFC is formally approved by all stakeholders.
2.  All four primary analytics endpoints are fully FX-aware, supporting the new request blocks and returning the specified currency decompositions.
3.  The currency attribution model is fully functional within the `/performance/attribution` endpoint.
4.  The testing and validation strategy is fully implemented, all tests are passing, and the required coverage targets are met.
5.  The characterization test passes, confirming numerical results match the external reference.
6.  New documentation is added to `docs/guides/` and `docs/technical/` explaining the multi-currency framework, currency attribution methodology, and the two valid approaches for modeling hedges, ensuring documentation remains current with the codebase.
