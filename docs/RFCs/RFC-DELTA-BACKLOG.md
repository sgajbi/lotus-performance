# RFC Delta Backlog (lotus-performance)

Generated: `2026-03-04`

Status values:
- `open`
- `done`
- `deferred`

## Open Deltas

### RFC-001-D01
- Status: `open`
- Priority: P1
- Source RFC: `RFC-001`
- Delta: Replace benchmark-only runtime measurement with enforceable trend/SLO checks for vectorized engine regressions.
- Why still relevant: RFC-001 acceptance depends on measurable performance guarantees, not only benchmark execution.
- Evidence:
  - `tests/benchmarks/test_engine_performance.py` runs benchmark but does not assert contractual thresholds.
- Proposed action: Add a non-flaky CI governance pattern (trend-based threshold + alert).

### RFC-004-D01
- Status: `open`
- Priority: P1
- Source RFC: `RFC-004`
- Delta: Implement adjusted average-weight denominator excluding NIP days and pre-final-reset days per RFC formula.
- Why still relevant: Current average-weight behavior can diverge in reset-heavy periods.
- Evidence:
  - `app/api/endpoints/contribution.py` and `engine/contribution.py` aggregate simple mean for average weight.
- Proposed action: Implement adjusted denominator path and add targeted tests.

### RFC-004-D02
- Status: `open`
- Priority: P2
- Source RFC: `RFC-004`
- Delta: Close explicit contribution hardening-governance acceptance markers in docs/CI references.
- Why still relevant: Engineering behavior is improved, but RFC closure evidence is not crisply tracked.
- Evidence:
  - RFC calls out explicit hardening closure, but no RFC-specific closure marker exists.
- Proposed action: Add closure evidence and criteria mapping in RFC/index.

### RFC-007-D01
- Status: `open`
- Priority: P1
- Source RFC: `RFC-007`
- Delta: Rebaseline and implement allocation drift API with explicit ownership boundary.
- Why still relevant: Capability is absent but still strategically valuable.
- Evidence:
  - No allocation drift endpoint/engine/model artifacts.
- Proposed action: Deliver minimal phase-1 drift snapshot API or formally archive/re-home.

### RFC-008-D01
- Status: `open`
- Priority: P2
- Source RFC: `RFC-008`
- Delta: Resolve fixed-income metrics ownership and define phased contract.
- Why still relevant: RFC exists but no implementation footprint.
- Evidence:
  - No fixed-income endpoint/model/engine modules.
- Proposed action: Confirm owner (lotus-performance vs lotus-risk) and implement or archive.

### RFC-009-D01
- Status: `open`
- Priority: P1
- Source RFC: `RFC-009`
- Delta: Implement base exposure breakdown API (net/gross/long/short).
- Why still relevant: Exposure foundation is required by downstream analytics proposals.
- Evidence:
  - No exposure endpoint/model/engine artifacts.
- Proposed action: Build phase-1 exposure endpoint with clear namespace.

### RFC-014-D01
- Status: `open`
- Priority: P1
- Source RFC: `RFC-014`
- Delta: Enforce consistent `flags.fail_fast` behavior across TWR/MWR/Contribution/Attribution.
- Why still relevant: Contract field exists, but uniform runtime behavior is not fully explicit.
- Evidence:
  - Shared envelope includes `flags.fail_fast`, but endpoint parity is incomplete.
- Proposed action: Define strict fail-fast policy and implement endpoint-wide.

### RFC-014-D02
- Status: `open`
- Priority: P1
- Source RFC: `RFC-014`
- Delta: Ensure attribution response diagnostics/audit completeness matches other core endpoints.
- Why still relevant: Shared footer parity remains incomplete.
- Evidence:
  - `app/models/attribution_responses.py` allows optional diagnostics/audit but endpoint output is lighter than TWR/MWR.
- Proposed action: Populate and test full diagnostics/audit blocks for attribution.

### RFC-016-D01
- Status: `closed`
- Priority: P1
- Source RFC: `RFC-016`
- Delta: Implement true Modified Dietz as a distinct method path from Simple Dietz.
- Closure: `mwr_method="MODIFIED_DIETZ"` now uses dated cash-flow weights, while
  `mwr_method="DIETZ"` keeps midpoint weighting. XIRR fallback emits `method="MODIFIED_DIETZ"`.
- Evidence:
  - `engine/mwr.py`
  - `tests/unit/engine/test_mwr.py`
  - `tests/integration/test_mwr_api.py`
  - `docs/methodologies/metrics/metric-mwr-dietz.md`

### RFC-018-D01
- Status: `open`
- Priority: P2
- Source RFC: `RFC-018`
- Delta: Close hierarchy/multi-level attribution parity and diagnostics alignment.
- Why still relevant: Base model/linking controls exist, but RFC scope is broader.
- Evidence:
  - `app/models/attribution_requests.py` supports model/linking; full RFC scope remains partially closed.
- Proposed action: Add explicit hierarchical acceptance tests and closure notes.

### RFC-019-D01
- Status: `open`
- Priority: P2
- Source RFC: `RFC-019`
- Delta: Add explicit reconciliation-governance tests for hierarchy totals and lookthrough fallback policies.
- Why still relevant: Multi-level controls exist but closure criteria can be strengthened.
- Evidence:
  - `ContributionRequest` includes `hierarchy`, `emit`, `lookthrough`; reconciliation governance remains implicit.
- Proposed action: Add reconciliation characterization suite and policy-level diagnostics assertions.

### RFC-020-D01
- Status: `open`
- Priority: P2
- Source RFC: `RFC-020`
- Delta: Standardize multi-currency behavior contract for MWR and endpoint-wide policy consistency.
- Why still relevant: TWR/Contribution/Attribution are FX-aware; MWR remains pre-converted input model.
- Evidence:
  - FX decomposition implemented in `engine/ror.py`, `engine/contribution.py`, `engine/attribution.py`; MWR guide states pre-converted currency requirement.
- Proposed action: Clarify and enforce MWR policy in schema/docs/tests.

### RFC-021-D01
- Status: `open`
- Priority: P1
- Source RFC: `RFC-021`
- Delta: Implement gross-to-net decomposition bridge and cost component outputs.
- Why still relevant: Only NET/GROSS basis exists today; no bridge decomposition.
- Evidence:
  - No `engine/costs.py` or gross-to-net bridge API artifacts.
- Proposed action: Phase 1 mgmt-fee bridge, then add advanced cost components.

### RFC-022-D01
- Status: `in_progress_via_rfc_049`
- Priority: P2
- Source RFC: `RFC-022`
- Delta: Retire RFC-022 as an implementation source and deliver the approved composite-performance
  scope through RFC-049.
- Why still relevant: No runtime implementation exists yet, but the ownership and delivery direction
  is now governed by RFC-049 rather than the older stateless `/composites/*` wrapper design.
- Evidence:
  - No `/composites/*` endpoints or `engine/composite.py`.
- Proposed action: Keep this delta open only as a tracking pointer until RFC-049 is implemented,
  merged, and promoted through implementation-backed supported-feature and wiki material. Do not
  implement RFC-022 directly.

### RFC-023-D01
- Status: `open`
- Priority: P2
- Source RFC: `RFC-023`
- Delta: Implement blended/dynamic benchmark engine behavior beyond basic benchmark-series retrieval.
- Why still relevant: Return-series benchmark support exists but dynamic benchmark composition does not.
- Evidence:
  - `returns_series` endpoint and core benchmark retrieval exist; no `engine/benchmarks.py` dynamic blend logic.
- Proposed action: Add benchmark composition module and integration tests.

### RFC-026-D01
- Status: `open`
- Priority: P2
- Source RFC: `RFC-026`
- Delta: Add attribution trading-effect methodology options and outputs.
- Why still relevant: RFC scope is not implemented in current attribution surface.
- Evidence:
  - No trading-effect method controls/output models in attribution path.
- Proposed action: Implement minimal method set and validation tests.

### RFC-028-D01
- Status: `open`
- Priority: P1
- Source RFC: `RFC-028`
- Delta: Eliminate remaining legacy naming drift and enforce no-alias behavior end-to-end.
- Why still relevant: Canonicalization tooling exists but migration is incomplete.
- Evidence:
  - Tooling exists in `scripts/no_alias_contract_guard.py`; residual legacy terms remain in docs/contracts.
- Proposed action: Complete migration and make no-alias checks mandatory in CI gate.

### RFC-031-D01
- Status: `open`
- Priority: P1
- Source RFC: `RFC-031`
- Delta: Implement or formally archive/re-home `/performance/twr/pas-input` contract.
- Why still relevant: RFC indicates implemented status but endpoint is absent.
- Evidence:
  - No `/performance/twr/pas-input` route in runtime code (`main.py`, endpoint modules).
- Proposed action: Correct status mismatch and execute explicit decision.

### RFC-032-D01
- Status: `open`
- Priority: P3
- Source RFC: `RFC-032`
- Delta: Define compact real-time analytics panel contract and latency budget.
- Why still relevant: Proposed UX-focused surface has not started implementation.
- Evidence:
  - No dedicated panel-style endpoints in current API.
- Proposed action: Scope MVP contract with lotus-manage/lotus-gateway consumers.

### RFC-033-D01
- Status: `open`
- Priority: P3
- Source RFC: `RFC-033`
- Delta: Implement reproducible year-history readiness workflow or move to platform automation repo.
- Why still relevant: Proposal exists but no dedicated repo workflow artifacts are tracked.
- Evidence:
  - No explicit lotus-performance readiness automation profile in this repository.
- Proposed action: Decide ownership and add machine-readable readiness artifacts.

### RFC-034-D01
- Status: `open`
- Priority: P2
- Source RFC: `RFC-034`
- Delta: After connected-mode enablement, refactor to lotus-performance-owned compute path for connected TWR.
- Why still relevant: RFC direction depends on RFC-031, which is not in code.
- Evidence:
  - No connected TWR endpoint path currently exists.
- Proposed action: Sequence behind RFC-031 closure.

### RFC-035-D01
- Status: `open`
- Priority: P2
- Source RFC: `RFC-035`
- Delta: Implement or re-home `/analytics/positions` ownership transition.
- Why still relevant: Contract-level direction exists without implementation.
- Evidence:
  - No `/analytics/positions` endpoint/model in runtime code.
- Proposed action: Confirm service ownership and execute phased transition plan.

### RFC-038-D01
- Status: `open`
- Priority: P1
- Source RFC: `RFC-038`
- Delta: Complete glossary-aligned vocabulary migration across API/docs/tests.
- Why still relevant: This is prerequisite hygiene for stable cross-service integration.
- Evidence:
  - Vocabulary tooling present; migration drift remains in current docs/contracts.
- Proposed action: Execute phased replacement with compatibility window and strict removal milestone.

### RFC-043-D01
- Status: `done`
- Priority: P0
- Source RFC: `RFC-043`
- Delta: Add reset-reason characterization and shadow diagnostics for `NCTRL_1..4`, `sod_reset`, `account_performance_reset`, and reset-relative `NIP` day accounting.
- Why done: Reset/NIP characterization and reset-relative day diagnostics are now implemented and exposed through both performance and contribution surfaces.
- Evidence:
  - `engine/rules.py` implements `NCTRL_1..4` and `NIP`, but `PERF_RESET` currently aggregates only `NCTRL_1..4`.
  - `engine/compute.py` now records `candidate_canonical_reset_days`, `reset_delta_days`, `nip_days_since_last_reset`, and `valid_days_since_last_reset`.
  - `engine/diagnostics.py`, `core/envelope.py`, `app/models/performance_diagnostics.py`
  - `tests/unit/engine/test_compute.py`, `tests/unit/models/test_performance_diagnostics_models.py`, `tests/integration/test_performance_api.py`
- Proposed action: Keep the characterization signals stable and use them as rollout evidence.

### RFC-043-D02
- Status: `deferred`
- Priority: P0
- Source RFC: `RFC-043`
- Delta: Implement canonical reset aggregation including explicit reset reasons and decide the retained role of `NCTRL_4`.
- Why deferred: The engine now has explicit reset-reason characterization and overlap diagnostics, but active canonical reset promotion was intentionally not switched on because it materially changed TWR behavior before enough evidence existed.
- Evidence:
  - `engine/rules.py` still keeps the production reset path centered on active `NCTRL_*` behavior.
  - `engine/compute.py` and `app/services/contribution_service.py` now expose `candidate_canonical_reset_days`, `reset_delta_days`, `nctrl4_exclusive_reset_days`, `account_reset_shadow_days`, and `sod_reset_shadow_days`.
  - `tests/unit/engine/test_compute.py` characterizes candidate-vs-active reset deltas.
- Proposed action: Revisit only after broader non-prod evidence shows the candidate canonical reset model is economically better and stable across cross-surface tie-out.

### RFC-043-D03
- Status: `deferred`
- Priority: P0
- Source RFC: `RFC-043`
- Delta: Replace legacy `NIP` behavior with a canonical stricter rule and add reset-relative `valid_days` accounting.
- Why deferred: Reset-relative `valid_days` accounting is implemented, but the stricter canonical `NIP` rule remains shadow-only pending more evidence before a hard behavioral cutover.
- Evidence:
  - `engine/rules.py` still supports the active/shadow `NIP` comparison path.
  - `engine/compute.py` now emits `nip_rule_delta_days`, `nip_days_since_last_reset`, and `valid_days_since_last_reset`.
  - `tests/unit/engine/test_compute.py` and `tests/integration/test_performance_api.py` cover those diagnostics.
- Proposed action: Keep the stricter `NIP` rule shadowed until canonical reset semantics are finalized.

### RFC-043-D04
- Status: `done`
- Priority: P1
- Source RFC: `RFC-043`
- Delta: Align contribution average-weight methodology with reset-aware and `NIP`-adjusted valid-day semantics.
- Why done: The reset-aware denominator, promotion telemetry, guarded rollout mode, per-period methodology status, readiness artifact, and decision checker are all implemented.
- Evidence:
  - `app/services/contribution_service.py` implements reset-aware shadow denominator logic, blocker classification, and `CONTRIBUTION_RESET_AWARE_AVERAGE_WEIGHT_MODE`.
  - `app/models/contribution_responses.py` exposes `average_weight_methodology_status`.
  - `scripts/contribution_rollout_readiness_report.py`, `scripts/generate_seeded_contribution_rollout_artifacts.py`, `scripts/contribution_rollout_decision_check.py`
  - `tests/unit/app/test_request_path_runtime_settings.py`, `tests/integration/test_contribution_api.py`, `tests/e2e/test_workflow_journeys.py`
- Proposed action: Continue operational validation and use the readiness artifacts for rollout decisions.

### RFC-043-D05
- Status: `done`
- Priority: P1
- Source RFC: `RFC-043`
- Delta: Strengthen grouped-return and cross-surface tie-out so contribution, TWR, returns-series, and attribution reconcile through reset boundaries.
- Why done: The implementation now characterizes grouped-return reset alignment, fixes reset-aware contribution top-line and daily-series tie-out for reset-heavy cases, and adds end-to-end reconciliation coverage for those paths.
- Evidence:
  - `app/services/contribution_service.py` now uses reset-aware period portfolio return, residual-adjusted daily series, reset-alignment counters, and timeseries tie-out diagnostics.
  - `tests/e2e/test_workflow_journeys.py` includes reset-heavy and multi-position reconciliation scenarios.
  - `tests/integration/test_contribution_api.py` covers API-surface methodology status and promotion behavior.
- Proposed action: Keep the cross-surface scenarios green and extend them only when new methodology changes are proposed.

### RFC-043-D06
- Status: `deferred`
- Priority: P2
- Source RFC: `RFC-043`
- Delta: Decide whether to retain current Carino smoothing as an intentional deviation or implement a richer long/short smoothing framework.
- Why deferred: Carino is now domain-safe and explicitly governed, but the richer long/short smoothing framework has not been adopted and is not required for the current rollout posture.
- Evidence:
  - `engine/contribution.py` keeps Carino smoothing with invalid-domain fallback.
  - `app/services/contribution_service.py` reports `carino_invalid_domain_days`.
  - `tests/unit/engine/test_contribution.py` and `tests/e2e/test_workflow_journeys.py` cover the fallback behavior.
- Proposed action: Revisit only if business acceptance requires richer smoothing parity.

### RFC-040-D01
- Status: `open`
- Priority: P2
- Source RFC: `RFC-040`
- Delta: Add attribution-grade hardening invariants for `POST /integration/returns/series`.
- Why still relevant: Core endpoint exists; attribution-specific hardening remains partially complete.
- Evidence:
  - `app/api/endpoints/returns_series.py` includes diagnostics/coverage, but RFC-040 hardening scope is broader.
- Proposed action: Add deterministic alignment checks and attribution-consumer contract tests.

## Completed / Deferred

### Done

### RFC-001-D02
- Status: `done`
- Priority: P2
- Source RFC: `RFC-001`
- Delta: Standalone engine usage documentation.
- Why done: Documentation exists and is discoverable.
- Evidence:
  - `docs/guides/standalone_engine_usage.md`
- Closure action: Keep doc in sync with adapter/engine contract.

### RFC-015-D01
- Status: `done`
- Priority: P3
- Source RFC: `RFC-015`
- Delta: Legacy-name compatibility strategy disposition.
- Why done: Superseded by RFC-028 no-alias governance direction and tracked there.
- Evidence:
  - `docs/RFCs/RFC-028 - Unified snake_case API Naming & Legacy Alias Removal.md`
- Closure action: Maintain as superseded historical note.

### RFC-024-D01
- Status: `done`
- Priority: P2
- Source RFC: `RFC-024`
- Delta: Robustness policies framework implementation.
- Why done: Policies, docs, and tests are present.
- Evidence:
  - `engine/policies.py`, `tests/unit/engine/test_policies.py`, `docs/guides/robustness_policies.md`
- Closure action: Keep policy contracts backward-compatible.

### RFC-025-D01
- Status: `done`
- Priority: P2
- Source RFC: `RFC-025`
- Delta: Deterministic reproducibility and lineage drill-down foundation.
- Why done: Canonical hash and lineage services are implemented and tested.
- Evidence:
  - `core/repro.py`, `app/services/lineage_service.py`, `tests/unit/core/test_repro.py`, `tests/integration/test_lineage_api.py`
- Closure action: Preserve artifact contract stability.

### RFC-029-D01
- Status: `done`
- Priority: P2
- Source RFC: `RFC-029`
- Delta: Unified multi-period request/response framework.
- Why done: `analyses`-based multi-period flow is live across endpoints.
- Evidence:
  - `app/models/requests.py`, `core/periods.py`, `app/api/endpoints/performance.py`, `tests/integration/test_multi_period_summary.py`
- Closure action: Maintain period resolver correctness across edge dates.

### RFC-030-D01
- Status: `done`
- Priority: P2
- Source RFC: `RFC-030`
- Delta: Integration capabilities contract endpoint.
- Why done: Endpoint and tests are implemented.
- Evidence:
  - `app/api/endpoints/integration_capabilities.py`, `tests/integration/test_integration_capabilities_api.py`
- Closure action: Version and feature key governance.

### RFC-036-D01
- Status: `done`
- Priority: P1
- Source RFC: `RFC-036`
- Delta: Enforce 99% coverage gate in local and CI paths.
- Why done: Fail-under gates are set to 99.
- Evidence:
  - `Makefile`, `.github/workflows/pr-merge-gate.yml`
- Closure action: Keep gate strict as test suite evolves.

### RFC-037-D01
- Status: `done`
- Priority: P2
- Source RFC: `RFC-037`
- Delta: E2E wave for resilience/lineage/capabilities workflows.
- Why done: Extended E2E workflow file includes these journeys.
- Evidence:
  - `tests/e2e/test_workflow_journeys.py`
- Closure action: Track pyramid ratio as suite grows.

### RFC-039-D01
- Status: `done`
- Priority: P1
- Source RFC: `RFC-039`
- Delta: Canonical returns-series integration contract for stateful consumers.
- Why done: Endpoint, models, integration client, and tests are in place.
- Evidence:
  - `app/api/endpoints/returns_series.py`, `app/models/returns_series.py`, `app/services/core_integration_service.py`, `tests/integration/test_returns_series_api.py`
- Closure action: Keep consumer compatibility and diagnostic guarantees.

### Deferred

### RFC-005-D01
- Status: `deferred`
- Priority: P3
- Source RFC: `RFC-005`
- Delta: Correlation matrix ownership.
- Why deferred: Archived and migrated to lotus-risk scope.
- Evidence:
  - `docs/RFCs/RFC 005 - Portfolio Correlation Matrix API.md`
- Proposed action: Track in lotus-risk only.

### RFC-010-D01
- Status: `deferred`
- Priority: P3
- Source RFC: `RFC-010`
- Delta: Equity factor exposures in lotus-performance.
- Why deferred: Archived and migrated to lotus-risk scope.
- Evidence:
  - `docs/RFCs/RFC 010 - Equity Factor Exposures API.md`
- Proposed action: Track in lotus-risk only.

### RFC-011-D01
- Status: `deferred`
- Priority: P3
- Source RFC: `RFC-011`
- Delta: Scenario analysis in lotus-performance.
- Why deferred: Archived and migrated to lotus-risk scope.
- Evidence:
  - `docs/RFCs/RFC 011 - Scenario Analysis API.md`
- Proposed action: Track in lotus-risk only.

### RFC-012-D01
- Status: `deferred`
- Priority: P3
- Source RFC: `RFC-012`
- Delta: Risk-adjusted returns in lotus-performance.
- Why deferred: Archived and migrated to lotus-risk scope.
- Evidence:
  - `docs/RFCs/RFC 012 - Risk-Adjusted Returns API.md`
- Proposed action: Track in lotus-risk only.

### RFC-013-D01
- Status: `deferred`
- Priority: P3
- Source RFC: `RFC-013`
- Delta: Active analytics in lotus-performance.
- Why deferred: Archived and migrated to lotus-risk scope.
- Evidence:
  - `docs/RFCs/RFC 013 - Active Analytics API.md`
- Proposed action: Track in lotus-risk only.
