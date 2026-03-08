# RFC Implementation Status

## Governance Boundary

- Service-specific lotus-performance implementation RFCs are maintained in this repository.
- Cross-cutting platform and multi-service architecture decisions are maintained in:
  `https://github.com/sgajbi/lotus-platform`

This document provides a summary of the implementation status for all RFCs related to the `lotus-performance` service. It also outlines a strategic, sequential roadmap for implementing the remaining features to build a cohesive and powerful analytics suite.

---

## Implemented RFCs

The following RFCs have been **fully implemented** and their features are part of the core application. This status has been verified against the current codebase and API capabilities.

| RFC Number | Title                                                      | Status              |
| :--------- | :--------------------------------------------------------- | :------------------ |
| RFC 001    | Performance Engine V2 - Vectorization & Refactor           | ✅ Fully Implemented |
| RFC 002    | Engine Upgrade - Performance Breakdown API                 | ✅ Fully Implemented |
| RFC 003    | Position Contribution Engine                               | ✅ Fully Implemented |
| RFC 004    | Contribution Engine Hardening & Finalization             | ✅ Fully Implemented |
| RFC 006    | Multi-Level Performance Attribution API                    | ✅ Fully Implemented |
| RFC 014    | Cross-Cutting Consistency & Diagnostics Framework        | ✅ Fully Implemented |
| RFC 015    | TWR Enhancements                                           | ✅ Fully Implemented |
| RFC 016    | MWR Enhancements (XIRR + Modified Dietz)                   | ✅ Fully Implemented |
| RFC 017    | Contribution Enhancements                                  | ✅ Fully Implemented |
| RFC 018    | Attribution Enhancements                                   | ✅ Fully Implemented |
| RFC 019    | Multi-Level Contribution API                               | ✅ Fully Implemented |
| RFC 020    | Multi-Currency & FX-Aware Performance                      | ✅ Fully Implemented |
| RFC 024    | Robustness Policies Framework                              | ✅ Fully Implemented |
| RFC 025    | Deterministic Reproducibility & Drill-Down                 | ✅ Fully Implemented |
| RFC-028    | Unified `snake_case` API Naming & Legacy Alias Removal     | ✅ Fully Implemented |
| RFC 031    | lotus-core Connected TWR Input Mode                               | ✅ Fully Implemented |

---

## Proposed Implementation Roadmap

The following RFCs are not yet implemented. This roadmap presents a logical order for their development, prioritizing foundational capabilities that enable more advanced analytics.

### Phase 0: Vocabulary and Contract Hygiene

1.  **RFC 038 — lotus-performance Domain Vocabulary Alignment with Platform Glossary**
    * **Reasoning:** **Eliminate cross-platform semantic drift first.** Aligns lotus-performance to canonical platform language (`portfolio_id`, `pas-input`) before further contract expansion.

### Phase 1: Foundational Enhancements

0.  **RFC 041 — API Orchestrator, Compute Executor, and PostgreSQL Durable State**
    * **Reasoning:** **Fix the primary runtime boundary before further scale arrives.** This establishes the durable execution model, PostgreSQL-backed operational state, and independent scaling path for heavy analytics without fragmenting the business domain.

1.  **RFC 032 — Real-Time Analytics Surfaces for Iterative Advisory and lotus-manage Simulation**
    * **Reasoning:** **Enable interactive lifecycle UX.** Introduces low-latency analytics panel contracts required for advisor and lotus-manage iterative simulation loops.

2.  **RFC 029 — Unified Multi-Period Analysis Framework**
    * **Reasoning:** **Dramatically improve API efficiency and usability.** This is a top priority as it fundamentally changes how clients perform comparative analysis, reducing multiple redundant calls to a single, optimized request.

3.  **RFC 024 — Robustness Policies**
    * **Reasoning:** **Build on a resilient core.** This is a prerequisite for handling real-world, messy data predictably, making all existing and future calculations more trustworthy.

4.  **RFC 021 — Gross-to-Net Return Decomposition**
    * **Reasoning:** **Provide critical fee transparency.** A foundational feature for any auditable reporting, explaining the impact of fees and costs on performance.

5.  **RFC 023 — Blended & Dynamic Benchmarks**
    * **Reasoning:** **Enable correct active analysis.** Many strategies are measured against dynamic, not static, benchmarks. This is essential for accurate attribution and active analytics.

### Phase 2: Expand Core Analytical Views

6.  **RFC 009 — Exposure Breakdown API**
    * **Reasoning:** **Establish the "present state" view.** This is the first major new analytical feature to build, answering "What am I exposed to?" and serving as a prerequisite for most other portfolio management analytics.

7.  **RFC 013 — Active Analytics API**
    * **Reasoning:** **Unify the active management story.** This API directly connects existing active return analysis with the new active exposure analysis from RFC 009, creating a complete, benchmark-relative view.

8.  **RFC 007 — Asset Allocation Drift Monitoring API**
    * **Reasoning:** **Create an actionable workflow.** This provides the core rebalancing workflow for portfolio managers, turning the insights from RFC 009 into concrete actions.

9.  **RFC 011 — Scenario Analysis & Stress Tests API**
    * **Reasoning:** **Introduce forward-looking risk.** A major expansion of capability that uses the sensitivities aggregated by RFC 009, moving the platform from historical analysis to what *could happen*.

### Phase 3: Deepen and Specialize Analytics

10. **RFC 012 — Risk-Adjusted Returns & Stats API**
    * **Reasoning:** **Deepen performance analysis.** Significantly enhances the "Performance" pillar with industry-standard statistics like Sharpe Ratio, VaR, and drawdown analysis.

11. **RFC 005 — Portfolio Correlation Matrix API**
    * **Reasoning:** **Expand statistical risk.** A complementary feature to RFC 012 that adds a key view on diversification and intra-portfolio risk.

12. **RFC 026 — Attribution Trading Effect**
    * **Reasoning:** **Enhance attribution with trading insights.** A specialized extension to the attribution engine that isolates the impact of in-period trading decisions.

### Phase 4: Add Enabling and Enterprise-Level Features

13. **RFC 008 & 010 — Fixed-Income Metrics & Equity Factor Exposures APIs**
    * **Reasoning:** **Enrich data with specialized models.** These are enabling services that provide deeper, asset-class-specific data (e.g., precise durations, factor exposures) that make the entire suite of tools more powerful.

14. **RFC 022 — Composite & Sleeve Aggregation API**
    * **Reasoning:** **Enable firm-level and GIPS-compliant reporting.** A major enterprise feature that aggregates results from multiple portfolios into composites, representing the pinnacle of the platform's capabilities.

