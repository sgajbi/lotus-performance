# RFC Review Index

Generated: `2026-03-04`

Status vocabulary for review loop:
- Draft
- Approved
- Implemented
- Partially Implemented
- Deprecated
- Archived

Implementation classification vocabulary:
- Fully implemented and aligned
- Partially implemented (requires enhancement)
- Outdated (requires revision)
- No longer relevant to this repository

| RFC | Title | Current Doc Status | Review Status | Implementation Classification | Evidence (code/tests/docs) | Next Actions |
| --- | --- | --- | --- | --- | --- | --- |
| RFC-001 | Performance Engine V2 - Vectorization & Architectural Refactor | Draft | Partially Implemented | Partially implemented (requires enhancement) | `engine/compute.py`, `engine/rules.py`, `engine/config.py`, `tests/benchmarks/test_engine_performance.py` | Close benchmark-governance delta and promote explicit performance SLO checks |
| RFC-002 | Engine Upgrade - Performance Breakdown API | Draft | Implemented | Fully implemented and aligned | `app/api/endpoints/performance.py`, `engine/breakdown.py`, `engine/periods.py`, `tests/integration/test_performance_api.py`, `tests/unit/engine/test_breakdown.py` | Keep contract and regression tests green |
| RFC-003 | Position Contribution Engine | Draft | Implemented | Fully implemented and aligned | `app/api/endpoints/contribution.py`, `engine/contribution.py`, `tests/integration/test_contribution_api.py`, `tests/unit/engine/test_contribution.py` | Keep as baseline for enhancement RFCs |
| RFC-004 | Contribution Engine Hardening & Finalization | Draft | Partially Implemented | Partially implemented (requires enhancement) | Residual attribution in `app/api/endpoints/contribution.py` and `engine/contribution.py`; tests in `tests/integration/test_contribution_api.py` | Implement adjusted-weight denominator and hardening closure deltas |
| RFC-005 | Portfolio Correlation Matrix API | Archived | Archived | No longer relevant to this repository | Stub in `docs/RFCs/RFC 005 - Portfolio Correlation Matrix API.md` points to lotus-risk migration | Keep as archived pointer |
| RFC-006 | Multi-Level Performance Attribution API | Implemented | Implemented | Fully implemented and aligned | `app/api/endpoints/performance.py`, `engine/attribution.py`, `tests/integration/test_attribution_api.py`, `tests/unit/engine/test_attribution.py` | Keep as implemented baseline |
| RFC-007 | Asset Allocation Drift Monitoring API | Draft | Draft | Outdated (requires revision) | No allocation-drift endpoint/model/engine artifacts in `app/api/endpoints`, `app/models`, `engine` | Rebaseline ownership/scope and implement phase-1 drift contract |
| RFC-008 | Fixed-Income Metrics API | Draft | Draft | Outdated (requires revision) | No fixed-income endpoint/model/engine artifacts found | Resolve ownership with lotus-risk and phase implementation |
| RFC-009 | Exposure Breakdown API | Draft | Draft | Outdated (requires revision) | No exposure endpoint/model/engine/test artifacts in repository | Rebaseline contract and build base exposure capability |
| RFC-010 | Equity Factor Exposures API | Archived | Archived | No longer relevant to this repository | Stub points to lotus-risk migration location | Keep archived pointer only |
| RFC-011 | Scenario Analysis API | Archived | Archived | No longer relevant to this repository | Stub points to lotus-risk migration location | Keep archived pointer only |
| RFC-012 | Risk-Adjusted Returns API | Archived | Archived | No longer relevant to this repository | Stub points to lotus-risk migration location | Keep archived pointer only |
| RFC-013 | Active Analytics API | Archived | Archived | No longer relevant to this repository | Stub points to lotus-risk migration location | Keep archived pointer only |
| RFC-014 | Cross-Cutting Consistency & Diagnostics Framework | Partially Implemented | Partially Implemented | Partially implemented (requires enhancement) | `core/envelope.py`, `core/periods.py`, `core/annualize.py`, `core/errors.py`, endpoint/model/test evidence | Close fail-fast and attribution diagnostics/audit parity deltas |
| RFC-015 | TWR Enhancements | Implemented | Implemented | Fully implemented and aligned | `engine/breakdown.py`, `engine/compute.py`, `app/api/endpoints/performance.py`, `tests/integration/test_performance_api.py` | Keep implemented baseline |
| RFC-016 | MWR Enhancements (XIRR + Modified Dietz) | Final (For Approval) | Partially Implemented | Partially implemented (requires enhancement) | `app/api/endpoints/performance.py` (`/performance/mwr`), `engine/mwr.py`, `tests/unit/engine/test_mwr.py`, `docs/methodologies/metrics/metric-mwr-dietz.md` | Implement distinct Modified Dietz path (currently same path as Dietz) and lock diagnostics behavior |
| RFC-017 | Contribution Enhancements | Final (For Approval) | Implemented | Fully implemented and aligned | `app/models/contribution_requests.py` (`weighting_scheme`, `smoothing`, `emit`), `engine/contribution.py`, `tests/unit/engine/test_contribution.py`, `docs/guides/contribution.md` | Keep enhancement behavior stable and add targeted reconciliation characterization tests |
| RFC-018 | Attribution Enhancements | Final | Partially Implemented | Partially implemented (requires enhancement) | `app/models/attribution_requests.py` (`model`, `linking`), `common/enums.py`, `engine/attribution.py`, `tests/integration/test_attribution_api.py` | Close multi-level/hierarchy and diagnostics parity deltas |
| RFC-019 | Multi-Level Contribution API | Final (For Approval) | Partially Implemented | Partially implemented (requires enhancement) | `app/models/contribution_requests.py` (`hierarchy`, `emit`, `lookthrough`), `engine/contribution.py`, `tests/integration/test_contribution_api.py` | Add explicit hierarchy reconciliation and lookthrough-governance closure tests |
| RFC-020 | Multi-Currency & FX-Aware Performance | Final (For Approval) | Partially Implemented | Partially implemented (requires enhancement) | `engine/ror.py`, `engine/contribution.py`, `engine/attribution.py`, `tests/integration/test_performance_api.py`, `tests/integration/test_attribution_api.py`, `docs/guides/multi_currency.md` | Clarify/extend MWR multi-currency semantics and enforce endpoint-wide policy consistency |
| RFC-021 | Gross-to-Net Return Decomposition | Final (For Approval) | Draft | Outdated (requires revision) | NET/GROSS basis exists in `app/models/requests.py` and `engine/ror.py`; no `engine/costs.py` bridge implementation | Rebaseline to implemented fee scope and plan phased gross-to-net bridge |
| RFC-022 | Composite & Sleeve Aggregation API | Final (For Approval) | Draft | Outdated (requires revision) | No `/composites/*` API surface, no `engine/composite.py` | Decide ownership (this repo vs another service) and archive or phase implementation |
| RFC-023 | Blended & Dynamic Benchmarks | Final (For Approval) | Partially Implemented | Partially implemented (requires enhancement) | Benchmark return-series support in `app/api/endpoints/returns_series.py` and `app/services/core_integration_service.py`; no `engine/benchmarks.py` dynamic blend engine | Implement blended/dynamic benchmark composition logic or split into a separate RFC |
| RFC-024 | Robustness Policies Framework | Final (For Approval) | Implemented | Fully implemented and aligned | `engine/policies.py`, `tests/unit/engine/test_policies.py`, `docs/guides/robustness_policies.md`, policy wiring in endpoint flows | Keep as policy baseline and monitor drift |
| RFC-025 | Deterministic Reproducibility & Drill-Down | Final (For Approval) | Implemented | Fully implemented and aligned | `core/repro.py`, `app/services/lineage_service.py`, `app/api/endpoints/lineage.py`, tests in `tests/unit/core/test_repro.py` and lineage integrations | Keep reproducibility contract and lineage artifacts stable |
| RFC-026 | Attribution Trading Effect | Final (For Approval) | Draft | Outdated (requires revision) | No trading-effect method controls/artifacts in `engine/attribution.py` or API models | Define minimal trading-effect slice and implement method selection |
| RFC-028 | Unified snake_case API Naming & Legacy Alias Removal | Final | Partially Implemented | Partially implemented (requires enhancement) | Canonical validation tooling exists (`scripts/no_alias_contract_guard.py`, `scripts/api_vocabulary_inventory.py`); legacy naming terms still present in docs/RFCs and contracts | Complete migration and enforce no-alias gate across API/docs/tests |
| RFC-029 | Unified Multi-Period Analysis Framework | Final (For Approval) | Implemented | Fully implemented and aligned | `app/models/requests.py` (`analyses`), `core/periods.py`, multi-period usage in `app/api/endpoints/performance.py`, `tests/integration/test_multi_period_summary.py` | Keep as foundation for all analytics endpoints |
| RFC-030 | Integration Capabilities Contract API | Accepted | Implemented | Fully implemented and aligned | `app/api/endpoints/integration_capabilities.py`, `tests/integration/test_integration_capabilities_api.py`, E2E coverage in `tests/e2e/test_workflow_journeys.py` | Keep capability keys/versioning stable |
| RFC-031 | PAS Connected TWR Input Mode | Implemented (doc) | Draft | Outdated (requires revision) | No `/performance/twr/pas-input` endpoint in runtime routers (`main.py`, `app/api/endpoints`) | Correct doc status and either implement or archive/relocate RFC |
| RFC-032 | Real-Time Analytics Surfaces for Iterative Advisory and DPM Simulation | Proposed | Draft | Outdated (requires revision) | No panel-specific iterative endpoints currently present | Define minimal panel contract and bounded latency SLO, then phase implementation |
| RFC-033 | PAS Year-History Readiness for PA and UI | Proposed | Draft | Outdated (requires revision) | Readiness proposal exists, but no dedicated cross-service readiness workflow artifacts in this repo | Move to platform automation standard or implement explicit readiness profile |
| RFC-034 | PA Ownership of PAS-Connected TWR Calculation | Draft | Draft | Outdated (requires revision) | No PAS-input endpoint/path (`/performance/twr/pas-input`) implemented | Sequence with RFC-031; implement PA-owned compute path after connected mode exists |
| RFC-035 | PA-Owned Position Analytics Contract (PAS-Backed Transition) | Draft | Draft | Outdated (requires revision) | No `/analytics/positions` endpoint/models/services in current code | Decide if this belongs in lotus-performance or lotus-manage/lotus-risk and re-home accordingly |
| RFC-036 | Enforce 99 Percent Coverage Gate | Approved | Implemented | Fully implemented and aligned | `Makefile` fail-under 99 and `.github/workflows/ci.yml` coverage gate at 99 | Keep gate enforced in CI and local workflows |
| RFC-037 | E2E Pyramid Wave 3 - Resilience and Lineage Workflow Coverage | Approved | Implemented | Fully implemented and aligned | `tests/e2e/test_workflow_journeys.py` includes lineage, resilience, capabilities, authz and contract scenarios | Keep E2E suite aligned with evolving contracts |
| RFC-038 | PA Domain Vocabulary Alignment with Platform Glossary | Proposed | Partially Implemented | Partially implemented (requires enhancement) | Vocabulary inventory and no-alias scripts exist; residual legacy naming still present in docs/contracts | Complete canonical term migration and keep strict vocabulary gate |
| RFC-039 | Returns Series Integration Contract for lotus-risk Stateful Risk Analytics | Proposed (Refined) | Implemented | Fully implemented and aligned | `app/api/endpoints/returns_series.py`, `app/models/returns_series.py`, `app/services/core_integration_service.py`, `tests/integration/test_returns_series_api.py` | Keep compatibility contract for lotus-risk consumers |
| RFC-040 | Returns Series Contract Hardening for lotus-risk Historical Attribution | Proposed (Implementation Ready) | Partially Implemented | Partially implemented (requires enhancement) | Strong base exists in `returns_series.py` diagnostics/coverage/gaps; attribution-specific hardening requirements are only partially encoded | Add attribution-targeted invariants and governance checks |

## Loop Execution Notes

- Review in small batches (3-7 RFCs per loop).
- For each RFC, gather concrete evidence from implementation modules, tests, OpenAPI contracts, and runbooks.
- Update `Review Status`, `Implementation Classification`, `Evidence`, and `Next Actions` per reviewed RFC.
