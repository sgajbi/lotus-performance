# RFC 045 - TWR Inspection and Supportability Contract

- Status: Proposed
- Date: 2026-04-15
- Owners: Performance Analytics Service
- Requires Approval From:
  - lotus-performance maintainers
  - lotus-core maintainers
  - lotus-platform maintainers
- Related:
  - RFC-014
  - RFC-015
  - RFC-025
  - RFC-029
  - RFC-041
  - RFC-042
  - RFC-043
  - RFC-044
  - lotus-platform/context/playbooks/TWR-INVESTIGATION-PLAYBOOK.md

## Summary

`lotus-performance` should add a dedicated TWR inspection and supportability contract.

The service should continue to calculate TWR for the inputs it receives, even when those inputs are
later shown to have upstream quality problems. The calculation contract and the supportability
contract should be separate.

The new contract should introduce:

1. a dedicated inspection endpoint family,
2. an internal inspector subsystem,
3. structured findings and ownership routing,
4. durable asynchronous inspection execution,
5. artifact-backed evidence suitable for support, platform validation, and future agent use.

This RFC does not widen the mathematical scope of the TWR engine. It defines how
`lotus-performance` should inspect, explain, and operationally qualify TWR results without
overloading `POST /performance/twr`.

## Why This Is Next

Recent investigation of the governed canonical portfolio `PB_SG_GLOBAL_BAL_001` showed that TWR can
be mathematically coherent while still being operationally untrustworthy because source economics are
not supportable.

Concrete examples observed during investigation:

1. on 2026-03-05, one deposit of `40,000` was present in the source transaction story, while
   `portfolio_timeseries.bod_cashflow` reflected `80,000`,
2. on 2026-03-12, one fee of `275` was present, while `portfolio_timeseries.eod_cashflow` reflected
   `-550` and `fees` reflected `550`,
3. on 2026-03-26, one withdrawal of `25,000` was present, while `portfolio_timeseries.eod_cashflow`
   reflected `-50,000`,
4. on 2026-02-28, position rows for the same portfolio date were served across multiple epochs while
   the portfolio aggregate was tied to a later epoch,
5. on 2026-03-26, the latest coherent position total and the served portfolio total differed by
   roughly `36,189.681`.

Those examples matter because they establish a boundary truth:

1. the TWR engine can still produce a mechanically consistent return,
2. the benchmark-relative arithmetic can still tie,
3. but the result can remain economically implausible because the stateful source inputs are not
   supportable.

That is a service-design gap, not only a debugging gap.

## Problem Statement

`lotus-performance` currently has no first-class inspection surface that answers the operational
question:

1. should this TWR result be treated as supportable,
2. if not, what exactly is wrong,
3. which repository owns the defect,
4. and what evidence proves that claim.

This creates five concrete problems:

1. support teams must perform manual cross-repo investigation to explain implausible numbers,
2. heavy triage logic is likely to leak into the normal TWR endpoint path,
3. canonical validation and production support risk diverging into separate bespoke scripts,
4. calculation truth and supportability truth are not separated in the public contract,
5. durable evidence for incident review, automation, and future agent workflows remains ad hoc.

## Goals

1. Keep `POST /performance/twr` focused on return calculation and engine-native diagnostics.
2. Add a separate TWR inspection contract for supportability and triage.
3. Reuse the durable execution, result, and lineage posture already introduced by RFC-041.
4. Support inspection of both:
   - an existing TWR calculation,
   - and a proposed TWR request.
5. Emit structured, machine-readable findings with explicit ownership routing.
6. Materialize durable evidence artifacts that can back support, platform validation, and agent
   workflows.
7. Make inspection failure semantics explicit and truthful.
8. Provide a foundation for a canonical TWR validator without creating a separate permanent script
   architecture.

## Non-Goals

1. This RFC does not make TWR fail closed when inspection finds poor source quality.
2. This RFC does not change TWR methodology, formulas, reset handling, or benchmark arithmetic.
3. This RFC does not make `lotus-performance` repair or mutate `lotus-core` source data.
4. This RFC does not add heavyweight reconciliation payloads to every normal TWR response.
5. This RFC does not define a universal cross-analytics inspector for every endpoint in one slice.
6. This RFC does not require a new repository or a new standalone infrastructure service.

## Current State

Today `lotus-performance` already has useful ingredients:

1. durable execution and async result handling through RFC-041,
2. calculation lineage and artifact materialization,
3. TWR diagnostics for reset, NIP, policy, and metadata behavior,
4. an established investigation sequence in
   `lotus-platform/context/playbooks/TWR-INVESTIGATION-PLAYBOOK.md`.

What it does not yet have:

1. a public inspection contract,
2. a durable runtime type for TWR inspection,
3. structured supportability findings,
4. ownership-aware triage outputs,
5. a canonical service-owned validator surface that platform automation can call.

## Decision

`lotus-performance` will introduce a dedicated TWR inspection subsystem and endpoint family.

The first implementation will:

1. stay inside `lotus-performance`,
2. reuse RFC-041 durable runtime patterns,
3. run asynchronously by default for stateful inspection,
4. produce a narrow verdict vocabulary,
5. produce bounded structured findings with evidence and ownership,
6. keep the normal TWR endpoint stable.

The central design rule is:

1. the engine answers what the return is,
2. the inspector answers whether the result is operationally supportable and why.

## State Model and Invariants

This RFC establishes the following invariants.

1. TWR calculation truth and TWR supportability truth must remain separate contracts.
2. A successful TWR calculation must not imply a supportable result.
3. Inspection must not silently mutate or reinterpret the original calculation result.
4. Inspection findings must be attributable to bounded evidence, not only free-text commentary.
5. Ownership routing must be explicit enough to distinguish:
   - `lotus-performance` calculation defects,
   - `lotus-core` source-quality or reconciliation defects,
   - documentation or contract drift.
6. Inspection artifacts must not overwrite or replace the original calculation lineage artifacts.
7. Heavy stateful reconciliation must run through durable async execution rather than request-local
   threads or one-off scripts.
8. Inspection failure must remain explicit; a failed inspection must not be presented as a clean
   supportability result.

## Public Contract Direction

### Endpoint Family

The initial endpoint family should be:

1. `POST /performance/inspections/twr`
2. `GET /performance/inspections/{inspection_id}`
3. `GET /performance/inspections/{inspection_id}/artifacts/{artifact_name}`

This mirrors the repository's existing posture of:

1. submission,
2. durable async processing,
3. status polling,
4. artifact retrieval.

### Request Modes

The contract should support two subject modes.

#### Mode 1: Inspect an existing calculation

Use this when the caller wants to inspect the exact TWR result that was already produced.

Illustrative request:

```json
{
  "subject_type": "twr_calculation",
  "subject_calculation_id": "4cbe76b7-c011-4c07-93b3-88e670e13f79",
  "inspection_profile": "support_triage"
}
```

This should be the preferred production-support path because it guarantees identity with the
calculation under investigation.

#### Mode 2: Inspect a proposed request

Use this when the caller wants supportability inspection against a fresh TWR request.

Illustrative request:

```json
{
  "subject_type": "twr_request",
  "request": {
    "input_mode": "stateful",
    "portfolio_id": "PB_SG_GLOBAL_BAL_001",
    "report_end_date": "2026-04-10",
    "metric_basis": "NET",
    "analyses": [
      { "period": "YTD", "frequencies": ["daily", "monthly"] }
    ],
    "include_benchmark": true,
    "stateful_input": {}
  },
  "inspection_profile": "canonical_validation"
}
```

For this mode, the service may calculate the subject first if a matching calculation does not yet
exist, but the inspection record must still remain a distinct inspection artifact and execution
identity.

### Response Shape

The top-level response should be an inspection record, not a generic diagnostics envelope.

Required fields:

1. `inspection_id`
2. `subject_type`
3. subject identity fields such as `subject_calculation_id`
4. `status`
5. `verdict`
6. `findings`
7. `owner_summary`
8. `evidence_summary`
9. `related_lineage`
10. `artifacts`

Illustrative response:

```json
{
  "inspection_id": "9d000001-1111-4222-8333-abcdefabcdef",
  "subject_type": "twr_calculation",
  "subject_calculation_id": "4cbe76b7-c011-4c07-93b3-88e670e13f79",
  "portfolio_id": "PB_SG_GLOBAL_BAL_001",
  "status": "complete",
  "verdict": "not_supportable",
  "findings": [
    {
      "code": "PORTFOLIO_POSITION_RECONCILIATION_GAP",
      "severity": "high",
      "category": "portfolio_position_reconciliation",
      "owner_repo": "lotus-core",
      "summary": "Portfolio totals do not reconcile to the latest coherent position state.",
      "explanation": "The served aggregate exceeds the latest position total by a persistent unexplained amount across the inspected window.",
      "recommended_action": "Review portfolio aggregation and epoch promotion behavior in lotus-core.",
      "evidence": {
        "max_gap_amount": 36189.681,
        "gap_dates": ["2026-02-28", "2026-03-26"]
      }
    }
  ],
  "owner_summary": {
    "primary_owner_repo": "lotus-core",
    "secondary_owner_repos": ["lotus-performance"]
  },
  "evidence_summary": {
    "largest_daily_move_pct": 14.762594,
    "returned_observation_count": 100,
    "expected_business_dates_count": 72
  },
  "related_lineage": {
    "calculation_id": "4cbe76b7-c011-4c07-93b3-88e670e13f79",
    "lineage_path": "/performance/lineage/4cbe76b7-c011-4c07-93b3-88e670e13f79"
  },
  "artifacts": {
    "findings_json": "/performance/inspections/9d000001-1111-4222-8333-abcdefabcdef/artifacts/findings.json",
    "reconciliation_csv": "/performance/inspections/9d000001-1111-4222-8333-abcdefabcdef/artifacts/reconciliation.csv"
  }
}
```

## Verdict Model

The top-level verdict should remain intentionally small:

1. `supportable`
2. `supportable_with_warnings`
3. `not_supportable`
4. `inspection_failed`

Semantics:

1. `supportable` means no high-signal evidence undermines operational trust in the result,
2. `supportable_with_warnings` means the result is still usable but notable caveats exist,
3. `not_supportable` means the result should not be treated as operationally trustworthy,
4. `inspection_failed` means the inspection process itself could not complete truthfully.

The verdict is not a statement about whether the TWR engine succeeded.

## Findings Contract

Each finding should include:

1. `code`
2. `severity`
3. `category`
4. `owner_repo`
5. `summary`
6. `explanation`
7. `recommended_action`
8. structured `evidence`

### Severity Set

Recommended severity values:

1. `info`
2. `warning`
3. `high`
4. `critical`

### Category Set

Initial categories:

1. `math_consistency`
2. `source_quality`
3. `economic_plausibility`
4. `portfolio_position_reconciliation`
5. `epoch_coherence`
6. `cashflow_classification`
7. `benchmark_consistency`
8. `documentation_drift`
9. `inspection_runtime`

The first slice should prefer a small stable taxonomy over an exhaustive one.

## Inspection Profiles

Inspection should be profile-driven rather than one undefined heavy mode.

Initial profiles:

1. `support_triage`
   - intended for production support and incident review,
2. `canonical_validation`
   - intended for governed canonical portfolio validation,
3. `deep_reconciliation`
   - intended for heavier source-state reconciliation and artifact capture.

Profile semantics must be explicit in code and docs so inspection cost and behavior stay bounded.

## Architecture Direction

### Subsystem Boundary

Introduce a dedicated inspection namespace, for example:

1. `app/api/endpoints/inspections.py`
2. `app/models/inspection_requests.py`
3. `app/models/inspection_responses.py`
4. `app/services/inspection/`

This should be an orchestration subsystem, not a new engine embedded inside core TWR calculation
logic.

### Core Internal Components

#### 1. `TWRInspectorService`

Responsible for:

1. subject orchestration,
2. check execution sequencing,
3. finding synthesis,
4. artifact production,
5. durable inspection status updates.

#### 2. `InspectionSubjectResolver`

Responsible for:

1. resolving existing calculations or proposed requests,
2. binding related calculation and lineage identifiers,
3. resolving portfolio and benchmark context,
4. preparing the exact subject inputs used by the inspector.

#### 3. `TWRInspectionChecks`

Responsible for bounded reusable check families:

1. calculation consistency,
2. source quality,
3. economic plausibility,
4. reconciliation.

#### 4. `InspectionFindingSynthesizer`

Responsible for:

1. transforming raw check outputs into findings,
2. deriving verdicts from bounded rules,
3. assigning ownership summaries,
4. constructing compact evidence summaries.

#### 5. `InspectionArtifactBuilder`

Responsible for:

1. machine-readable findings,
2. reconciliation tables,
3. anomaly summaries,
4. support briefs or markdown narratives when needed.

### Runtime Reuse Through RFC-041

Inspection should be implemented as a new durable runtime family, for example:

1. `TWR_INSPECTION`

That allows inspection to:

1. run through the existing durable executor model,
2. expose truthful async status and polling,
3. materialize artifacts durably,
4. survive process restarts and worker boundaries,
5. integrate cleanly with existing observability and lineage patterns.

This RFC explicitly rejects:

1. request-local background threads,
2. one-off diagnostic scripts as the long-term architecture,
3. inspection logic coupled directly into the normal TWR request path.

## Inspection Stage Model

The durable inspection record should expose explicit stages:

1. `subject_resolution`
2. `subject_materialization`
3. `math_reconciliation`
4. `source_quality_assessment`
5. `economic_plausibility_assessment`
6. `cross_source_reconciliation`
7. `finding_synthesis`
8. `artifact_materialization`

These stages matter operationally because support failures often happen before a verdict exists.

## Check Families

### 1. Calculation Consistency Checks

These remain closest to `lotus-performance` responsibility.

Initial checks:

1. `relative_performance = portfolio - benchmark`,
2. benchmark block inside TWR matches benchmark-only output over the same window,
3. requested bucket breakdowns link coherently into the served period return,
4. multi-period and cumulative arithmetic are internally coherent.

Expected ownership when these fail:

1. usually `lotus-performance`,
2. or documentation drift if the implementation is correct but the public contract is misleading.

### 2. Source Quality Checks

These inspect stateful source behavior without pretending to repair it.

Initial checks:

1. returned observation count versus expected business-date count,
2. weekend row presence,
3. missing-date count,
4. stale or restated concentration,
5. largest positive and negative daily moves,
6. share of return explained by the top N days,
7. repeated unexplained move patterns.

### 3. Economic Plausibility Checks

These should remain profile-aware and mandate-aware.

Initial checks:

1. unexplained double-digit daily moves for a balanced private-banking mandate,
2. monthly return dominated by one unexplained day,
3. benchmark-relative story that does not fit the benchmark path,
4. external flow or fee patterns that do not fit the transaction story.

These checks produce findings; they do not rewrite the return.

### 4. Reconciliation Checks

These are the heaviest and most valuable support checks.

Initial checks:

1. `portfolio_timeseries` market value versus reconstructed latest coherent `position_timeseries`,
2. latest row per security and date versus served aggregate,
3. mixed-epoch snapshot detection,
4. duplicated or conflicting cash-state detection,
5. transaction totals versus derived cash-flow totals,
6. fee transaction totals versus derived fee values.

## What Stays in the Normal TWR Response

The existing TWR endpoint should keep lightweight calculation-native diagnostics such as:

1. reset counts,
2. NIP counts,
3. policy counters,
4. effective period metadata,
5. benchmark metadata,
6. existing audit and calculation metadata.

The normal TWR response should not automatically absorb:

1. cross-source reconciliation tables,
2. ownership findings,
3. heavy anomaly lists,
4. supportability verdicts,
5. mandate-plausibility judgments.

## Artifact Model

Inspection artifacts should be durable and typed.

Expected first-class artifacts:

1. `findings.json`
2. `inspection_summary.json`
3. `reconciliation.csv`
4. `anomalies.json`
5. optional `support_brief.md`

Artifact rules:

1. artifacts must be inspection-scoped,
2. artifacts must not overwrite original calculation lineage artifacts,
3. artifact names and schemas must stay stable enough for platform automation,
4. artifact detail must remain authorization-aware and avoid unnecessary raw source dumping.

## Failure and Degradation Semantics

This RFC requires explicit inspection failure behavior.

Required semantics:

1. if inspection cannot resolve the subject, the result must be `inspection_failed`,
2. if some check families succeed and some fail, the contract must surface partial completion
   truthfully,
3. absence of a finding must not imply a clean bill of health if the relevant checks did not run,
4. unavailable upstream state, authorization failure, or artifact materialization failure must be
   represented explicitly,
5. a failed inspection must never be coerced into `supportable_with_warnings`.

## Relationship to Lineage

For existing calculations:

1. inspection should reference the original calculation lineage identity,
2. inspection should produce its own inspection-scoped artifacts,
3. inspection must not replace the original analytics lineage.

For request-subject inspection with no prior calculation:

1. inspection should still produce a durable artifact set,
2. those artifacts should be clearly typed as inspection outputs rather than normal analytics
   lineage.

## Canonical Validator Direction

The canonical validator for `PB_SG_GLOBAL_BAL_001` should be built on this contract.

The target operating model is:

1. `lotus-performance` owns the inspection contract,
2. `lotus-platform` automation calls that contract for governed validation,
3. canonical evidence and support evidence are derived from the same durable artifacts,
4. ad hoc scripts do not become the long-term source of truth.

## Security and Operational Requirements

1. inspection authorization must remain at least as strict as the underlying analytics and lineage
   surfaces,
2. inspection responses must prefer summarized evidence over raw source payload dumping,
3. heavy profiles must be async and rate-aware,
4. sensitive source detail should be artifact-backed and governed, not sprayed into summary payloads,
5. inspection status must remain truthful across restart and worker failure.

## Delivery Slices

### Slice 1: Contract and Runtime Skeleton

Outcome:

1. inspection request and response models exist,
2. endpoint family exists,
3. durable runtime type exists,
4. polling and artifact plumbing exist,
5. no heavy reconciliation logic is required yet.

Acceptance gate:

1. the public contract is typed and documented,
2. the async lifecycle is durable,
3. artifact retrieval works,
4. request-subject and calculation-subject inspection both work,
5. inspection records remain distinct from normal calculation records.

### Slice 2: Calculation Consistency Checks

Outcome:

1. the service can identify arithmetic and contract-level inconsistencies,
2. findings and verdict rules exist for engine-local failures,
3. ownership can route to `lotus-performance` truthfully.

Acceptance gate:

1. benchmark-relative and bucket-linking checks are tested,
2. verdict rules are deterministic,
3. engine-local defects are not misrouted to `lotus-core`.

### Slice 3: Source Quality and Plausibility Checks

Outcome:

1. the service can flag implausible source behavior without mutating the result,
2. anomaly summaries and evidence artifacts are available,
3. canonical-validation profile gains real operational value.

Acceptance gate:

1. missing-date, weekend, stale-series, and large-move checks are implemented,
2. mandate-aware plausibility rules remain bounded and documented,
3. findings distinguish warnings from non-supportable defects coherently.

Implementation status on 2026-04-15:

1. source-quality inspection now covers weekend observations, missing business dates, bounded stale
   valuation-series detection, and extreme daily moves,
2. the stale-series rule is intentionally narrow: it only triggers when at least three observations
   repeat the same begin or end valuation state with zero cash-flow and fee activity,
3. source-quality evidence summaries now carry stale-run and stale-observation counts so support
   can distinguish single-point oddities from repeated source stagnation,
4. the inspection artifact contract now exposes `source_quality_summary.json` so operators and
   automation can retrieve source-quality evidence directly instead of reconstructing it from the
   top-level inspection summary,
5. source-quality inspection now also emits a high-severity finding when resolved observations have
   a nonpositive daily capital base (`begin_mv + bod_cf <= 0`), because daily-move plausibility
   can no longer be interpreted truthfully for those dates,
6. source-quality inspection now adds a bounded canonical balanced-mandate warning for
   `PB_SG_GLOBAL_BAL_001` when a daily move is at least `2.00%` but still below the active generic
   extreme-move threshold, keeping the mandate-aware rule scoped until broader mandate profiles are
   governed,
7. source-quality inspection now warns when the top three absolute daily moves explain at least
   `80%` of total absolute movement across an inspected window with at least 20 interpretable daily
   moves,
8. source-quality inspection now warns on repeated same-direction daily move patterns when at least
   three consecutive daily moves each have absolute return of at least `1.00%`.

### Slice 4: Reconciliation Checks

Outcome:

1. the inspector can tie portfolio aggregates against coherent position state,
2. mixed-epoch and cash-flow-classification defects become first-class findings,
3. supportability evidence becomes sufficient for upstream escalation.

Acceptance gate:

1. reconciliation logic is integration-tested against realistic stateful fixtures,
2. cash-flow and fee duplication defects can be surfaced clearly,
3. ownership routing to `lotus-core` is backed by explicit evidence artifacts.

Implementation status on 2026-04-15:

1. stateful existing-calculation inspection now performs portfolio-versus-position reconciliation using
   the same `StatefulInputService` seam already trusted by the analytics runtime,
2. mixed-epoch position snapshots, duplicate snapshot rows, and latest-position-versus-portfolio
   end-value gaps are emitted as first-class `lotus-core` findings,
3. rows with unusable snapshot epoch labels and latest selected position rows with unusable ending
   market values are now emitted as explicit `lotus-core` reconciliation evidence instead of being
   dropped silently from selection or tie-out totals,
4. unexplained position begin-value carry-forward breaks are now emitted as explicit `lotus-core`
   reconciliation findings with prior end value, current begin value, position id, valuation dates,
   and gap evidence,
5. owner-summary synthesis now reflects the actual finding owners instead of defaulting every clean
   or dirty inspection to `lotus-performance`.

### Slice 5: Canonical and Platform Integration

Outcome:

1. platform automation can call the inspection contract,
2. canonical TWR validation is based on service-owned inspection outputs,
3. runbooks and docs are aligned to runtime truth.

Acceptance gate:

1. platform validation consumes the inspection contract rather than a bespoke script,
2. repo and platform docs point to the same supported operating model,
3. support evidence is usable by humans and automation without manual reconstruction.

Implementation status on 2026-04-15:

1. `/integration/capabilities` now advertises the TWR inspection surface with machine-readable
   `subject_type` and `inspection_profile` options,
2. the inspection artifact contract now exposes `reconciliation_summary.json` when stateful
   reconciliation runs, so automation can consume structured reconciliation evidence directly,
3. the inspection artifact contract now also exposes `source_economics_summary.json` when raw
   stateful portfolio-source economics checks run,
4. raw source-economics inspection now covers both fee and external cash-flow classification,
   conflicting or malformed explicit fee or bod/eod source totals, fee and external normalization
   mismatches, duplicate source signals, positive fee sign anomalies, explicit fee or external
   source-total mismatches, unsupported beginning-of-day fee timing, mixed external BOD/EOD timing
   on the same valuation date, external timing-bucket contradictions, invalid amount values, invalid
   timing labels, missing `cash_flow_type` labels, non-canonical `cash_flow_type` labels, governed
   aliases such as `management_fee`, and unsupported labels such as `dividend`,
5. stateful portfolio and position valuation normalization now use the same source cash-flow taxonomy so
   canonical fee economics, including operational expenses emitted as `cash_flow_type="fee"` with
   `source_classification="EXPENSE"`, are preserved in `mgmt_fees` rather than in generic cash-flow buckets,
6. the public service reference and support-facing check guide now document the bounded inspection
   controls, active finding inventory, and artifact set,
7. a deeper platform-owned canonical validator can now consume the same contract instead of relying
   on ad hoc parsing or a bespoke parallel script.

## Validation and Evidence Strategy

### Unit Tests

1. subject resolution,
2. verdict rules,
3. ownership assignment,
4. finding synthesis,
5. individual check modules,
6. partial-failure semantics.

### Integration Tests

1. inspection by `subject_calculation_id`,
2. inspection by request payload,
3. durable async submission and polling,
4. artifact retrieval,
5. linkage to original calculation identity,
6. authorization-aware artifact exposure.

### Characterization Tests

1. mathematically coherent but economically implausible stateful inputs,
2. mixed-epoch snapshots,
3. duplicated cash-flow classification,
4. benchmark-consistent but mandate-implausible paths.

### Cross-App Validation

For governed canonical scenarios:

1. the inspector should classify upstream source defects as `lotus-core` ownership when supported by
   evidence,
2. the inspector should not classify correct arithmetic as an engine defect,
3. platform automation should be able to consume the same contract and artifacts.

## Risks and Mitigations

1. Risk: the inspection endpoint becomes a vague "run everything" tool.
   Mitigation: use bounded profiles, explicit stages, and a narrow finding taxonomy.
2. Risk: inspection logic leaks back into the normal TWR request path.
   Mitigation: keep a separate runtime type, endpoint family, and artifact model.
3. Risk: ownership routing becomes opinionated rather than evidence-based.
   Mitigation: require structured evidence and deterministic finding rules.
4. Risk: heavy reconciliation increases operator latency expectations.
   Mitigation: run stateful inspection asynchronously by default.
5. Risk: platform automation forks into a second permanent validator path.
   Mitigation: make the service-owned inspection contract the canonical validation surface.

## Alternatives Considered

### Alternative 1: Harden `POST /performance/twr` Inline

Rejected because it mixes:

1. calculation,
2. supportability inspection,
3. upstream reconciliation,
4. operator evidence generation.

That would increase latency, widen the normal contract, and blur repository boundaries.

### Alternative 2: Keep Inspection as External Scripts Only

Rejected because it creates split-brain truth:

1. the service owns the number,
2. but scripts own the supportability explanation.

That is not durable enough for production support or governed platform validation.

### Alternative 3: Push Supportability Judgment Fully to `lotus-platform`

Rejected because `lotus-performance` owns the analytics contract and is the right place to define
inspection semantics for its own outputs. Platform automation should consume the contract, not invent
it.

## Open Questions

1. Should the first public slice remain internal-only until the finding taxonomy stabilizes?
2. Should explicit mandate profiles beyond canonical balanced portfolios be introduced in slice 1 or
   deferred until slice 3?
3. Should some lightweight source-quality counters eventually be mirrored into normal TWR diagnostics
   once inspection semantics are proven stable?
4. Should the internal subsystem be named generically enough to support MWR and returns-series
   inspection later, while keeping the public contract TWR-specific at first?

## Recommendation

Proceed with a TWR-first inspector subsystem.

Keep TWR calculation and TWR supportability as separate contracts.

Build the canonical validator on top of the inspection contract rather than beside it.

Reuse the existing durable async and artifact backbone.

That is the cleanest path to:

1. truthful production support,
2. canonical validation,
3. reliable ownership routing,
4. durable evidence artifacts,
5. future automation and agent-assisted triage.
