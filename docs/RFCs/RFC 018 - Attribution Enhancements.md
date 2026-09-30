# RFC 18: Attribution Enhancements

**Status:** Final  
**Owner:** Senior Architect  
**Reviewers:** Perf Engine, Risk, Platform  
**Target Release:** v0.4.x  
**Related:** RFC-014 (Cross-Cutting Consistency & Diagnostics Framework), `/performance/attribution`

## 1\. Executive Summary

This document specifies a major upgrade to the `/performance/attribution` endpoint, transforming it from a single-level tool into a flexible, multi-level analytical engine. This RFC introduces support for multiple **Brinson models** (BF and BHB), configurable multi-period **linking methods**, and most importantly, **multi-level hierarchical analysis**. A new policy for handling **zero-weight assets** is also introduced to improve robustness.

These enhancements provide portfolio managers with deeper, more customizable insights into the drivers of active return, allowing them to decompose performance across dimensions like sector, industry, and security in a single, coherent request. This work fully aligns the endpoint with the shared API envelope established in RFC-014, ensuring a consistent and auditable client experience.

-----

## 2\. Current State Analysis

The existing attribution engine is functional but limited in its analytical scope and flexibility.

  * **Single Model/Method:** The engine is hardcoded to use the Brinson-Fachler (BF) model and Menchero geometric linking, preventing users from applying other industry-standard variations.
  * **No Hierarchical Analysis:** The engine can only perform attribution on a single dimension (e.g., `sector`). Analyzing a `sector -> industry` hierarchy requires multiple, separate API calls that are difficult to reconcile.
  * **Implicit Edge Case Handling:** The engine lacks explicit controls for handling common edge cases, such as when a security exists in the portfolio but not in the benchmark, or vice versa.

-----

## 3\. Proposed Enhancements & Methodology

### 3.1 Alignment with API Framework (RFC-014)

As part of the v0.4.x release, the `/performance/attribution` endpoint will fully adopt the cross-cutting consistency framework. All requests will support the shared envelope fields (`precision_mode`, `periods`, `annualization`, etc.), and all responses will include the standard footer containing `meta`, `diagnostics`, and `audit` blocks for improved transparency and auditability.

### 3.2 Brinson Model Variants

The engine will support the two primary Brinson models, selectable via the `model` parameter.

  * **Trigger:** `"model": "BF"` or `"model": "BHB"` in the `AttributionRequest`.
  * **Logic:** The `engine/attribution.py` module will implement a strategy pattern to apply the correct formulas for Allocation and Selection effects. The Brinson-Fachler (`BF`) model remains the default.
      * **Brinson-Fachler (BF):** Allocation is measured against the benchmark's total return: $A\_i = (w\_{pi} - w\_{bi}) \\times (R\_{bi} - R\_b)$.
      * **Brinson-Hood-Beebower (BHB):** Allocation is measured against the benchmark group's return: $A\_i = (w\_{pi} - w\_{bi}) \\times R\_{bi}$.
      * **Selection and interaction:** BF uses benchmark-weighted selection and reports interaction
        separately. BHB uses portfolio-weighted combined selection
        ($S_i = w_{pi} \\times (R_{pi} - R_{bi})$) and reports the separate interaction as zero;
        adding the interaction again would double count active return.

### 3.3 Configurable Multi-Period Linking

Users can choose how single-period effects are linked over time to calculate the total geometric active return.

  * **Trigger:** `"linking": "GEOMETRIC"` or `"linking": "ARITHMETIC"` in the `AttributionRequest`.
  * **Logic:**
      * **`GEOMETRIC` (Default):** Applies the **Menchero linking algorithm** to correctly account for compounding effects, ensuring the sum of attribution effects perfectly reconciles to the geometric active return ($TWR\_{Portfolio} - TWR\_{Benchmark}$). This method is consistent with existing `carino` and `log` options.
      * **`ARITHMETIC`:** Performs a simple arithmetic sum of single-period effects. This is useful for validation but will not reconcile with a compounding return.

### 3.4 Multi-Level Hierarchical Analysis

The endpoint will compute and return attribution results for a full hierarchy in a single call.

  * **Trigger:** Providing an ordered list of dimensions in the `hierarchy` request field (e.g., `["sector", "industry", "security"]`).
  * **Methodology:** The engine will perform a **bottom-up aggregation**.
    1.  Attribution effects (A, S, I) are first calculated at the most granular level specified in the hierarchy.
    2.  The dollar effects for each component are then summed up to the parent levels.
    3.  This bottom-up approach ensures that the total effects at any given level perfectly reconcile to the sum of the effects of their constituent children.

### 3.5 Zero-Weight Policy

A new `zero_weight_policy` field will provide explicit control over how to handle assets present in the portfolio but not the benchmark (or vice versa).

  * **Trigger:** The `zero_weight_policy` field in the `AttributionRequest`.
  * **Policies:**
      * **`drop` (Default):** Any asset not present in both the portfolio and the benchmark is excluded from the calculation.
      * **`carry_forward`:** An asset with zero weight is included. Its return is assumed to be the average return of the group it belongs to. This prevents penalizing a manager for holding an asset not in the index if that asset performed well.
      * **`normalize`:** The weights of the remaining assets in the group are proportionally increased to sum to 100% before calculation.

### 3.6 Explicit Reconciliation Block

To improve transparency, the response will include a dedicated `reconciliation` block. This block will explicitly show that the sum of the calculated attribution effects (Allocation + Selection + Interaction) equals the independently calculated active return, with any residual clearly stated in basis points.

-----

## 4\. API Contract Changes

### 4.1 `AttributionRequest` Additions

```jsonc
{
  // ... RFC-014 Shared Envelope Fields (as_of, periods, etc.) ...
  "model": "BF",                         // "BF" | "BHB"
  "linking": "GEOMETRIC",                // "GEOMETRIC" | "ARITHMETIC"
  "hierarchy": ["sector", "industry"],   // Ordered list for hierarchical rollup
  "zero_weight_policy": "drop",          // "drop" | "carry_forward" | "normalize"
  "emit": {
    "active_reconciliation": true,
    "by_level": true
  }
}
```

### 4.2 `AttributionResponse` Additions

```jsonc
{
  // ... endpoint-specific data ...
  "summary": { "active_return": 1.21 }, // In percent
  "components": { "allocation": 0.48, "selection": 0.65, "interaction": 0.08 },
  "reconciliation": {
    "portfolio_minus_benchmark_pct": 1.21,
    "sum_components_pct": 1.21,
    "residual_bp": 0.0
  },
  "levels": [
    {
      "level": "sector",
      "rows": [ { "key": {"sector": "Tech"}, "A": 0.3, "S": 0.4, "I": 0.1 } ]
    },
    {
      "level": "industry",
      "rows": [ { "key": {"sector": "Tech", "industry": "Software"}, "A": 0.1, "S": 0.2, "I": 0.0 } ]
    }
  ],
  // --- RFC-014 Shared Response Footer ---
  "meta": { /* ... */ },
  "diagnostics": { /* ... */ },
  "audit": { /* ... */ }
}
```

-----

## 5\. Testing Strategy

  * **Unit Tests:** New tests will be added to `tests/unit/engine/test_attribution.py` to:
      * Compare the outputs of the BF and BHB models against a known dataset.
      * Verify that `linking: "ARITHMETIC"` produces a simple sum of single-period effects.
      * Test each of the `zero_weight_policy` options on a curated dataset.
  * **Integration Tests:** A new integration test will be created for a multi-level `hierarchy` request. The test will assert that the sum of dollar effects at a lower level (e.g., `industry`) correctly rolls up to the corresponding parent key in the level above (e.g., `sector`), validating the bottom-up aggregation.

-----

## 6\. Acceptance Criteria

1.  The `/performance/attribution` endpoint is enhanced to support selectable Brinson models, linking methods, and zero-weight policies.
2.  The endpoint correctly processes a `hierarchy` request using bottom-up aggregation and returns a multi-level, nested response.
3.  The endpoint fully implements the RFC-014 shared request envelope and response footer.
4.  The response includes a `reconciliation` block that validates the accuracy of the calculation.
5.  All new and existing unit and integration tests for the attribution feature are passing.
6.  Documentation in **`docs/guides/api_reference.md`** and **`docs/guides/attribution_methodology.md`** is created or updated to reflect the new hierarchical capabilities and configuration options.
7.  This RFC is formally approved before implementation begins.
8.  Calculation hashes use the governed engine methodology identity. The BHB reconciliation
    correction advances that identity so historical results cannot be represented as if they used
    the corrected decomposition.
