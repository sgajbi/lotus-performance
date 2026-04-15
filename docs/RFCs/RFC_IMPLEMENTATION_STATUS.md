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
| RFC 041    | API Orchestrator, Compute Executor, and PostgreSQL Durable State  | ✅ Fully Implemented |

---

## Proposed Implementation Roadmap

The following RFCs are not yet implemented. This roadmap presents a logical order for their development, prioritizing foundational capabilities that enable more advanced analytics.

### Phase 0: Vocabulary and Contract Hygiene

1.  **RFC 038 — lotus-performance Domain Vocabulary Alignment with Platform Glossary**
    * **Reasoning:** **Eliminate cross-platform semantic drift first.** Aligns lotus-performance to canonical platform language (`portfolio_id`, `pas-input`) before further contract expansion.

2.  **RFC 045 — TWR Inspection and Supportability Contract**
    * **Reasoning:** **Separate analytics calculation from supportability triage before hardening stateful validation further.** Establishes an inspector architecture for source-quality diagnostics, reconciliation, and production support findings without overloading the core TWR endpoint.
    * **Current state:** **Slices 1-5 are delivered and the source-economics hardening lane has advanced materially.** The durable inspection contract, async runtime path, artifact plumbing, operator/capability wiring, calculation-consistency checks, source-quality/plausibility checks, stateful portfolio-position reconciliation checks, and machine-readable platform-consumption contract now exist. Runtime check-family failures after subject resolution are now preserved as explicit `INSPECTION_CHECK_FAMILY_FAILED` findings, so completed families remain reviewable instead of being erased by a later partial failure. The newest follow-on evidence slices detect benchmark/relative block pairing drift, relative breakdown bucket-alignment drift, fee-classified and external cash-flow classification loss, fee and external normalization mismatches, duplicate raw source signals, positive fee sign anomalies, unsupported beginning-of-day fee timing, mixed fee BOD/EOD timing on the same valuation date, detailed and explicit mixed external BOD/EOD timing on the same valuation date, malformed portfolio observation date identities, malformed `cash_flows` collection shapes, malformed detailed cash-flow row shapes, conflicting explicit fee or external source totals, external timing-bucket contradictions, non-canonical `cash_flow_type` labels, governed alias labels such as `management_fee`, unsupported labels such as `dividend`, unexplained position begin-value carry-forward breaks, bounded canonical balanced-mandate daily move outliers, top-day return concentration across sufficiently long inspected windows, repeated same-direction daily move patterns, and monthly single-day movement dominance. Stateful portfolio and position valuation normalization now share the source cash-flow taxonomy so canonical fee economics, including operational expenses emitted as `cash_flow_type="fee"` with `source_classification="EXPENSE"`, are preserved in `mgmt_fees` rather than generic cash-flow buckets. A support-facing check inventory document now describes the active inspector findings and artifacts. The next slice is realistic stateful fixture characterization and canonical live-validation evidence.
    * **Resume note, 2026-04-15:** Pause broad RFC continuation and revalidate canonical stateful TWR after lotus-core commit `f73a345` normalized analytics cash-book economics. The refreshed source-economics characterization now proves the prior canonical defect dates remain clean when deposit, operational fee, and withdrawal source rows tie to normalized valuation points, with persisted `source_classification="EXPENSE"` emitted as `cash_flow_type="fee"` with `flow_scope="operational"`. Live control-plane validation for `PB_SG_GLOBAL_BAL_001` as-of `2026-04-10` is now repeatable through `scripts/validate_canonical_twr_inspection.py`, which probes the query-control-plane analytics-input POST routes, runs stateful TWR, and fails on source-economics or reconciliation regressions.
    * **Runtime note, 2026-04-15:** Completed lineage payloads retain their durable request JSON in the metadata database so API containers can inspect resolved stateful TWR requests even when lineage files were materialized by a separate worker container filesystem. Runtime retention remains responsible for deleting terminal lineage records and payloads together.
    * **Inspection-window note, 2026-04-15:** Existing-calculation inspections scope source-quality, source-economics, and reconciliation checks to the executed TWR master window from response metadata. For example, a YTD calculation against an inception-sourced stateful request is inspected from the YTD master start, not from historical pre-period observations retained in the resolved lineage payload.
    * **Artifact note, 2026-04-15:** Inspection artifact download falls back to the retained durable lineage payload when the API container cannot see files materialized by the lineage-worker container. This keeps support artifacts retrievable in the repo-local multi-container Docker runtime.
    * **Mandate-plausibility note, 2026-04-15:** Source-quality inspection now adds a bounded warning for `PB_SG_GLOBAL_BAL_001` when canonical balanced private-banking daily moves are at least `2.00%` but below the active generic extreme-move threshold. The rule is deliberately scoped to the governed canonical portfolio until explicit mandate profiles are introduced.
    * **Fee-timing note, 2026-04-15:** Source-economics inspection now preserves beginning-of-day fee-classified cash-flow rows as `FEE_CASHFLOW_TIMING_BUCKET_UNSUPPORTED` evidence. The amount still participates in fee normalization checks, but the unsupported timing bucket is routed to `lotus-core` as upstream contract evidence.
    * **Fee-mixed-timing note, 2026-04-15:** Source-economics inspection now warns when fee-classified rows occupy both BOD and EOD buckets for the same valuation date, preserving the full operational-fee timing story instead of surfacing only the BOD unsupported-timing sample.
    * **Malformed-cashflow-collection note, 2026-04-15:** Source-economics inspection now warns when `cash_flows` is present but not a list, preserving malformed upstream collection shape as source-contract evidence instead of treating it as an empty detailed-cash-flow collection.
    * **Malformed-cashflow-row note, 2026-04-15:** Source-economics inspection now warns when a `cash_flows` list contains non-object rows, preserving malformed row shape as source-contract evidence while still interpreting other valid rows on the same date.
    * **Malformed-observation-date note, 2026-04-15:** Source-economics inspection now warns when a portfolio observation is missing a usable ISO `valuation_date`, preserving malformed observation identity as upstream contract evidence instead of silently dropping the row.
    * **External-timing note, 2026-04-15:** Source-economics inspection now warns when detailed external-flow rows occupy both BOD and EOD buckets for the same valuation date. This preserves timing-sensitive transaction-story evidence without treating mixed timing as an automatic normalization defect.
    * **Return-concentration note, 2026-04-15:** Source-quality inspection now warns when the top three absolute daily moves explain at least 80% of total absolute movement across an inspected window with at least 20 interpretable daily moves.
    * **Repeated-move note, 2026-04-15:** Source-quality inspection now warns on at least three consecutive same-direction daily moves where each absolute move is at least 1.00%, preserving repeated source-pattern evidence without treating alternating volatility as the same defect.
    * **Monthly-dominance note, 2026-04-15:** Source-quality inspection now warns when one day explains at least 75% of total absolute movement in a month with at least 10 interpretable daily moves.
    * **Relative-alignment note, 2026-04-15:** Calculation-consistency inspection now flags relative breakdown rows whose period label or date window does not align with the corresponding portfolio and benchmark buckets before doing row-level relative arithmetic.
    * **Benchmark-relative pairing note, 2026-04-15:** Calculation-consistency inspection now flags benchmark blocks without relative-performance blocks and relative-performance blocks without benchmark blocks, making incomplete benchmarked TWR response contracts explicit.

### Phase 1: Foundational Enhancements

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

