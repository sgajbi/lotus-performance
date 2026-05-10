# RFC 047 - Contribution Carino Methodology Alignment and Evidence Contract

Status: Draft - For Approval

Owner repository: `lotus-performance`

Primary domain: performance analytics

Source package: `C:\Users\Sandeep\Downloads\contribution-carino-docs.zip\contribution-carino-docs`

Created: 2026-05-10

Implementation posture: not started. This RFC is the approval artifact for the next implementation cycle.

## 1. Executive Summary

This RFC proposes a gold-standard contribution and Carino smoothing upgrade for `lotus-performance`.
The source documentation package explains industry-practice absolute contribution, single-period
contribution, multi-period linking, Carino smoothing, data classification, edge cases, QA
regressions, and production support behavior. The goal is not to copy the generic documents into
Lotus. The goal is to convert the useful parts into implementation-backed Lotus capability,
documentation, wiki material, API evidence, and data-product governance.

`lotus-performance` already has a sophisticated contribution baseline:

1. stateless and stateful contribution input modes;
2. lotus-core sourced portfolio and position timeseries;
3. hierarchy output with `Other` and `Unclassified` handling;
4. Carino smoothing with invalid-domain guardrails;
5. reset/NIP awareness and reset-aware average-weight shadow diagnostics;
6. residual-adjusted position, daily, and hierarchy series;
7. async execution, lineage capture, supportability metadata, and bounded observability labels;
8. downstream realization through `lotus-gateway` and `lotus-workbench`.

The review also found material gaps that should be addressed before contribution can be considered
bank-buyable as a fully auditable contribution data product:

1. current Carino implementation appears to use `K / k_t` instead of the industry-standard
   `k_t / K` factor described in the supplied documentation;
2. the response does not expose enough raw-vs-smoothed evidence for support teams to explain a
   contribution number without recomputing internals;
3. invalid Carino paths are currently surfaced through audit counts and diagnostics, but not as a
   first-class per-period smoothing status and reason-code contract;
4. contribution data-product declarations and trust telemetry do not yet promote contribution as a
   first-class governed mesh product in the same way as TWR, MWR, and returns-series capability;
5. methodology documentation is useful but not yet at the full v3 standard for Carino factors,
   residual policy, component P&L, source lineage, and deterministic worked examples;
6. upstream source economics from `lotus-core` may need richer normalized contribution-economics
   fields for income, fees, taxes, FX, corporate actions, derivatives, cash, and component flows;
7. downstream Gateway and Workbench should consume any new evidence/status fields instead of
   inferring contribution quality locally.

No implementation should start until this RFC is approved.

## 2. Business Outcome

Private bankers, portfolio managers, investment counsellors, operations teams, and client-service
teams need contribution analytics that can answer:

1. what drove the portfolio return;
2. whether the answer is raw daily contribution or linked-period smoothed contribution;
3. whether the result is gross, net, local-currency, base-currency, or FX-aware;
4. whether the result covers the full portfolio or a partial/hierarchical view;
5. whether residuals are rounding noise, data-quality gaps, or intentional methodology buckets;
6. whether the contribution explanation is safe for a client meeting or requires operations review.

The expected product outcome is a contribution capability that a bank can confidently buy:

1. mathematically correct;
2. source-backed;
3. explainable;
4. API-certified;
5. governed as a data product;
6. operationally observable;
7. documented for engineers, business users, operations, sales, pre-sales, and client demos.

## 3. Source Documentation Review

The supplied package contains:

| Source file | Adopt into Lotus? | RFC treatment |
| --- | --- | --- |
| `01-contribution-methodology.md` | Yes | Convert into Lotus business and methodology docs explaining contribution vs component return, absolute contribution vs relative attribution, gross/net, income, fees, FX, hierarchy, residuals, and private-banking interpretation. |
| `02-single-period-contribution-calculation.md` | Yes | Use for P&L-over-denominator requirements, buy/sell flow classification, external-flow exclusion, income/fee treatment, and single-period reconciliation tests. |
| `03-multi-period-contribution-and-linking.md` | Yes | Use for raw vs linked contribution behavior, multi-period output naming, and support guidance. |
| `04-carino-smoothing-methodology.md` | Yes, high priority | Use as the source for Carino factor correction, zero-return tolerance, invalid-return handling, smoothing residual evidence, and deterministic examples. |
| `05-data-classification-and-inputs.md` | Yes | Use for upstream/core source-economics requirements and contribution data-quality reason codes. |
| `06-implementation-design.md` | Yes | Use for pipeline boundaries, smoothing service separation, audit evidence, configuration versioning, caching/restatement expectations, and access control. |
| `07-edge-cases-and-controls.md` | Yes | Use for zero/near-zero denominator, negative NAV, -100% return, missing classification, partial views, multi-parent classification, fees/taxes, FX, derivatives, and residual controls. |
| `08-qa-regression-pack.md` | Yes | Convert into Lotus test matrix and canonical proof pack. |
| `09-production-support-agent-playbook.md` | Yes | Convert into Lotus support runbook and safe support-agent behavior. |
| `contribution-carino-playbook-all-in-one.md` | Reference only | Use only as a consolidated review source; do not commit generic wording into Lotus docs. |

## 4. Current Implementation Assessment

### 4.1 Current strengths

| Area | Current Lotus evidence | Assessment |
| --- | --- | --- |
| Contribution endpoint | `app/api/endpoints/contribution.py`, `app/models/contribution_requests.py`, `app/models/contribution_responses.py` | Strong baseline. Supports stateful/stateless execution, hierarchy, emit controls, async result polling, and strict models. |
| Engine implementation | `engine/contribution.py`, `app/services/contribution_service.py` | Strong baseline. Computes position-level daily weights, raw contribution, smoothed contribution, reset/NIP zeroing, hierarchy aggregation, residual allocation, and reset-aware average-weight shadow diagnostics. |
| Stateful source integration | `app/services/stateful_contribution_input_service.py` | Good baseline. Resolves source input from `lotus-core`; must be assessed for richer contribution-economics needs. |
| Supportability | `calculation_supportability`, bounded metric labels | Good baseline. Already aligned to front-office degraded-state handling. |
| Documentation | `docs/guides/contribution.md`, `docs/methodologies/metrics/metric-contribution-total.md`, `docs/technical/contribution-endpoint-certification.md` | Good but not yet complete for full Carino/source-economics/data-product evidence. |
| Downstream consumers | `lotus-gateway` Workbench performance workspace; `lotus-workbench` performance panels | Good baseline. Gateway issue #107 is closed and tests preserve full contribution row coverage. |
| Tests | `tests/unit/engine/test_contribution.py`, `tests/integration/test_contribution_api.py`, endpoint certification docs | Strong baseline for existing behavior; must be expanded for Carino correction and industry QA cases. |

### 4.2 Current gaps

| Gap | Severity | Evidence | Required direction |
| --- | --- | --- | --- |
| Carino factor direction appears inverted | P0 | Source docs define `F_t = k_t / K`; current code applies adjustment equivalent to `K / k_t` in `engine/contribution.py` | Correct implementation after approval, prove against deterministic examples, and update all affected tests/docs/downstream expectations. |
| Carino smoothing is not separated from raw contribution calculation | P1 | Current smoothing lives in `_calculate_daily_instrument_contributions` | Extract a focused Carino/linking module or service boundary if it reduces complexity and improves auditability. |
| Per-period smoothing status is not first-class | P1 | Invalid-domain days are audit counts/diagnostic notes, not a structured per-period smoothing result | Add explicit status/reason-code evidence such as `OK`, `RAW_ONLY`, `CARINO_INVALID_PERIOD_RETURN`, `CARINO_INVALID_TOTAL_RETURN`, `SINGLE_PERIOD_RECONCILIATION_FAILED`. |
| Raw and smoothed contribution evidence is not fully exposed | P1 | Response primarily exposes final contribution totals and optional series | Add support-safe evidence fields for raw contribution, smoothed contribution, smoothing factor, linked return, residual, and method status where useful. |
| Component P&L/source economics are not first-class | P1 | Current engine uses weight x position return; source docs prefer normalized P&L-over-denominator for complex cases | Assess and, where necessary, add upstream/source fields for income, fees, taxes, FX, component flows, and residual buckets. |
| Contribution is not declared as a first-class data product | P1 | `contracts/domain-data-products/lotus-performance-products.v1.json` includes TWR, MWR, returns series, and benchmark exposure context, but not contribution analytics | Add `ContributionAnalytics` producer declaration, trust telemetry, SLO/access/evidence posture, and platform catalog validation. |
| Methodology docs are not full v3 for Carino | P1 | `metric-contribution-total.md` has formulas but lacks complete Carino worked table, factor evidence, status behavior, and support examples | Upgrade methodology docs to v3 and align docs/wiki with actual implementation after code changes. |
| OpenAPI examples need richer contribution evidence | P1 | Current models have descriptions/examples but not full post-RFC evidence payload examples | Certify Swagger with complete request/response examples and field-level descriptions for new fields. |
| Live proof pack should include contribution support scenarios | P1 | Existing live evidence is endpoint-certification oriented | Add canonical live evidence covering raw vs smoothed, hierarchy, source-quality, and downstream display. |

## 5. Architecture Direction

The target architecture is:

```text
lotus-core source observations
  -> stateful contribution input resolver
  -> normalized contribution economics
  -> raw single-period contribution engine
  -> single-period reconciliation validator
  -> Carino/linking service
  -> residual/status/evidence builder
  -> contribution API response and lineage artifacts
  -> lotus-gateway performance workspace contract
  -> lotus-workbench performance drivers UI and advisor context
```

Key decisions:

1. `lotus-performance` remains the contribution methodology authority.
2. `lotus-core` supplies source observations and, if needed, richer source-economics inputs; it does
   not own contribution conclusions.
3. `lotus-gateway` remains the experience API; it must preserve source-authored contribution
   totals, evidence status, and row coverage.
4. `lotus-workbench` must render contribution truth from Gateway and must not invent smoothing,
   residual, or supportability state.
5. If API changes are the right design, backward compatibility is not required for this RFC, but
   every downstream consumer must be updated in the same implementation cycle.

## 6. Supported-Features Ledger

This ledger controls what may be promoted into README/wiki/sales/demo material.

| Feature | Current state | Target state after RFC | Promotion rule |
| --- | --- | --- | --- |
| Stateful contribution from lotus-core | Supported | Supported with stronger source-economics evidence | Promote only after source input and live canonical proof pass. |
| Stateless contribution | Supported | Supported with corrected Carino evidence and stronger examples | Promote after deterministic unit/integration proof. |
| Carino-smoothed absolute contribution | Supported but under review | Supported only after factor correction/proof | Promote only when deterministic examples prove `sum(smoothed)=linked_return` without relying on hidden residual distortion. |
| Raw contribution | Supported internally | Supported and explainable where emitted | Promote after raw-vs-smoothed response evidence is available and documented. |
| Hierarchy contribution | Supported | Supported with explicit full/partial view status, `Other`, `Unclassified`, and residual evidence | Promote after hierarchy tests and Workbench proof. |
| Local/base/FX contribution | Supported where source fields allow | Supported with explicit FX policy/status evidence | Promote after multi-currency tests and docs. |
| Gross/net contribution | Supported via basis | Supported with methodology metadata and fee/tax policy evidence | Promote after NET/GROSS QA cases and docs. |
| Contribution data product | Not fully declared | Governed `ContributionAnalytics:v1` data product | Promote after domain-product, telemetry, SLO/access/evidence, and mesh certification gates pass. |
| Contribution support runbook | Partial | Implementation-backed wiki/runbook | Promote after live proof and support examples reference actual fields. |

## 7. Slice Plan

### Slice 0 - Source Map, Branch Hygiene, and Baseline Assessment

Purpose: establish an implementation-safe baseline before code changes.

Scope:

1. rerun stranded-truth reconciliation for `lotus-performance` and any downstream repos touched;
2. preserve source-doc review mapping in the RFC/source-map;
3. identify current code/tests/docs/OpenAPI/downstream evidence;
4. classify existing behavior as implemented, gap, or explicit non-goal;
5. create a local evidence directory under `output/` for non-committed review artifacts.

Acceptance criteria:

1. no unclassified unmerged governance branches;
2. source documents are mapped to Lotus decisions;
3. current implementation strengths/gaps are recorded;
4. implementation branch is current with `origin/main`.

### Slice 1 - Platform Automation and Scaffolding Improvement

Purpose: move repeatable platform gaps into `lotus-platform` rather than local one-off fixes.

Assess and improve platform automation for:

1. contribution/analytics API certification patterns;
2. Swagger field-description and example quality;
3. methodology-doc v3 validation for formulas, variable dictionaries, validation behavior, and worked examples;
4. domain-data-product onboarding for analytics outputs beyond returns series;
5. trust telemetry scaffolding for analytics products;
6. source-data API profile and ingestion-pipeline checklists;
7. live proof pack structure for endpoint, gateway, and Workbench evidence.

Acceptance criteria:

1. platform gaps are either fixed in `lotus-platform` or deliberately classified as no-change;
2. any platform change has tests and is merged/validated before relying on it;
3. future Lotus apps benefit from the scaffolding improvement.

### Slice 2 - Cleanup and Contribution Module Structure

Purpose: make contribution easier to reason about before adding more scope.

Scope:

1. review `engine/contribution.py` and `app/services/contribution_service.py` for overly large or mixed-responsibility blocks;
2. extract focused helpers only where they materially improve correctness or testability;
3. remove dead or misleading contribution docs/tests;
4. reduce duplicate docs across README, docs, and wiki;
5. keep implementation behavior stable except where a verified bug fix is explicitly part of this RFC.

Acceptance criteria:

1. raw contribution, smoothing, residual/evidence, and response-shaping responsibilities are clearer;
2. no unrelated cosmetic churn;
3. existing tests remain green before moving to the methodology slices.

### Slice 3 - Carino Methodology Correction and Deterministic Engine Proof

Purpose: align Carino smoothing with the supplied industry methodology and prove the math.

Scope:

1. verify the factor direction against source-doc examples and current Lotus behavior;
2. correct the formula if the current implementation is confirmed to use `K / k_t` instead of `k_t / K`;
3. use `log1p` and zero-return tolerance instead of exact zero comparison;
4. distinguish daily invalid-domain and total invalid-domain status;
5. prevent residual allocation from masking a smoothing-formula defect;
6. add deterministic tests for:
   - two-day `+10%/-10%` Carino example;
   - zero daily return;
   - zero linked return;
   - invalid `-100%` period return;
   - near-zero return tolerance;
   - raw contribution mismatch before smoothing.

Acceptance criteria:

1. deterministic examples match expected values within strict tolerance;
2. smoothed contribution reconciles to linked return for valid inputs;
3. invalid Carino paths do not publish precise-looking smoothed values without status;
4. all affected docs and OpenAPI examples use the corrected formula.

### Slice 4 - Raw Contribution, Residual, and Smoothing Evidence Contract

Purpose: make every contribution number explainable without hidden recomputation.

Scope:

1. add response evidence for raw contribution, smoothed contribution, smoothing method, smoothing factor, linked return, raw residual, smoothing residual, and status where appropriate;
2. add reason codes for contribution and smoothing outcomes;
3. distinguish display rounding residual from source/data/methodology residual;
4. make full/partial hierarchy scope explicit;
5. ensure `Other` and `Unclassified` buckets are visible and documented;
6. preserve safe field access for support and client-facing contexts.

Acceptance criteria:

1. every returned period has a structured smoothing/evidence posture;
2. support teams can answer raw vs smoothed, linked return, residual, and invalid-domain questions from the response/lineage;
3. Gateway and Workbench preserve the evidence fields that matter for user-facing status.

### Slice 5 - Source Economics and Upstream Contract Realization

Purpose: strengthen contribution as a source-backed analytics product.

Scope:

1. assess whether current `lotus-core` stateful timeseries provides enough fields for:
   - component P&L;
   - external flows vs internal trades;
   - income;
   - fees;
   - taxes;
   - FX rates and FX P&L;
   - corporate actions;
   - derivative/loan/cash/liability treatment;
   - classification snapshots and effective dates;
2. if upstream fields are missing and required, update `lotus-core` contracts and tests in the same RFC;
3. preserve `lotus-performance` as methodology authority;
4. add lineage/audit identifiers for valuation, transaction, classification, FX, and configuration source snapshots where available;
5. explicitly classify unavailable upstream economics as unsupported/degraded rather than guessed.

Acceptance criteria:

1. contribution source-economics assumptions are explicit;
2. upstream contract changes, if any, are implemented and validated;
3. lotus-performance tests prove both source-rich and source-limited behavior;
4. no follow-up RFC is required for essential upstream realization.

### Slice 6 - Data Product and Data Mesh Hardening

Purpose: promote contribution into the governed Lotus data mesh.

Scope:

1. add or update `ContributionAnalytics:v1` in repo-local domain-data-product declarations;
2. add trust telemetry for contribution analytics;
3. add SLO/access/evidence policy participation where required by platform standards;
4. update platform catalog/certification references if needed;
5. document approved consumers, freshness, completeness, lineage, restatement, access, and evidence classes;
6. prove mesh certification locally and in CI.

Acceptance criteria:

1. domain-product declaration validates;
2. trust telemetry validates;
3. mesh certification recognizes contribution as a governed product;
4. Gateway and Workbench consume contribution through governed APIs only.

### Slice 7 - API Contract, OpenAPI, and Downstream Consumer Alignment

Purpose: make API changes deliberate and fully consumed.

Scope:

1. revise `POST /performance/contribution` request/response models if needed;
2. certify OpenAPI summaries, descriptions, tags, examples, error responses, and field descriptions;
3. update `lotus-gateway` client/parser/contracts to preserve new evidence and totals;
4. update `lotus-workbench` models and UI surfaces to render safe contribution status;
5. update advisor-brief context if it consumes contribution evidence;
6. remove stale aliases or misleading compatibility paths if they conflict with the target contract.

Acceptance criteria:

1. all downstream consumers compile and pass tests;
2. Gateway does not synthesize source-owned totals;
3. Workbench does not invent contribution quality state;
4. API docs show complete request/response examples and error behavior.

### Slice 8 - QA Regression Pack and Test Pyramid Upgrade

Purpose: convert the source QA pack into Lotus tests.

Required tests:

1. basic single-period contribution;
2. internal buy trade is not portfolio external flow;
3. external deposit is not performance;
4. income assigned to generating asset or explicit income bucket;
5. fee bucket in net contribution;
6. short position sign behavior;
7. raw multi-period mismatch;
8. Carino smoothing deterministic example;
9. zero period return;
10. zero total linked return;
11. invalid period return;
12. missing classification -> `Unclassified`;
13. partial hierarchy -> explicit partial/Other/residual posture;
14. FX/local/base contribution behavior;
15. async execution and lineage evidence;
16. downstream Gateway/Workbench preservation.

Acceptance criteria:

1. tests validate real behavior, not just schema count;
2. tests include unit, integration, contract/OpenAPI, e2e/live proof where relevant;
3. no shallow coverage-only tests;
4. coverage and CI gates remain green.

### Slice 9 - Documentation and Wiki Productization

Purpose: turn generic industry docs into Lotus implementation-backed product material.

Scope:

1. update methodology docs to v3 standard;
2. update contribution guide;
3. update endpoint certification;
4. update README only if navigation or supported feature truth changes;
5. update repo-local wiki with audience-aware material:
   - business explanation;
   - contribution vs component return;
   - raw vs smoothed;
   - Carino method;
   - source economics;
   - support workflow;
   - upstream/downstream architecture;
   - diagrams where useful;
6. avoid duplicate long-form docs between repo and wiki.

Acceptance criteria:

1. docs are detailed, Lotus-specific, and implementation-backed;
2. docs are useful to developers, business users, operations, sales, pre-sales, and demos;
3. docs tests pass;
4. repo-local wiki source validates and is ready for publication after merge.

### Slice 10 - Live Front-Office Proof

Purpose: prove the implementation in the canonical front-office stack.

Scope:

1. validate `lotus-performance` APIs directly;
2. validate Gateway routes;
3. validate Workbench performance drivers;
4. capture machine-readable request/response evidence under `output/`;
5. use canonical portfolio `PB_SG_GLOBAL_BAL_001` unless a slice requires a specialized fixture;
6. include contribution, raw/smoothed, hierarchy, residual, source-quality, and downstream display checks;
7. leave live stack state as requested by the operator.

Acceptance criteria:

1. live evidence proves endpoints and product surfaces;
2. evidence is critically reviewed for mismatches, not merely captured;
3. discovered gaps are fixed before closure;
4. demo-safe claims are backed by live evidence.

### Slice 11 - Second-Last Hardening and Review

Purpose: perform a critical production-readiness review before closure.

Scope:

1. code review for correctness, modularity, duplication, dead code, and hidden coupling;
2. API certification review;
3. Swagger quality review;
4. error-handling review;
5. security/dependency review;
6. data-mesh certification review;
7. observability/metrics/logging review;
8. downstream consumer review;
9. documentation truth review.

Acceptance criteria:

1. no known correctness defects remain;
2. security issues are fixed or formally tracked with treatment;
3. all API fields have descriptions/examples where exposed;
4. all contribution claims are implementation-backed.

### Slice 12 - Final Closure

Purpose: close the RFC to Lotus definition-of-done.

Scope:

1. update RFC status and implementation evidence;
2. update `RFC-INDEX.md` and supported-feature material;
3. update repository context if repository truth changed;
4. update AGENTS/context/skills only if operating guidance changed;
5. sync wiki source and publish after merge;
6. rerun stranded-truth reconciliation;
7. confirm all touched repos are clean, merged to main, and CI green;
8. classify any remaining unmerged governance branches.

Acceptance criteria:

1. implementation is merged to `main`;
2. CI is green;
3. wiki is published when wiki truth changed;
4. local repos are clean and aligned with remote main;
5. no durable truth is stranded on unmerged branches.

## 8. API and Compatibility Posture

Backward compatibility is not guaranteed for this RFC. If the right design requires response shape
changes, the implementation will update all known consumers in the same RFC:

1. `lotus-gateway`;
2. `lotus-workbench`;
3. advisor brief context through Gateway;
4. any reporting or AI consumer discovered during implementation.

Old fields may be removed or replaced if they are misleading, duplicate, or prevent correct
source-backed contribution behavior. Any removal must be backed by consumer search and migration
tests.

## 9. Data Mesh Requirements

The implementation must satisfy:

1. repo-native producer declaration for `ContributionAnalytics:v1`;
2. trust telemetry snapshot and validation;
3. freshness, completeness, lineage, source service, and restatement semantics;
4. approved consumers and access policy;
5. evidence policy for customer, restricted customer, operator, and internal fields;
6. platform mesh certification;
7. Gateway/Workbench discovery compatibility if catalog publication changes.

## 10. Observability, Security, and Operations

The implementation must provide:

1. bounded Prometheus labels only;
2. structured logs with correlation and trace context;
3. safe operator diagnostics without raw payload leakage;
4. clear error responses for invalid source economics, invalid Carino, and no usable periods;
5. support runbook examples for raw vs smoothed, residuals, partial views, and missing source data;
6. no sensitive holdings/P&L leakage beyond authorized surfaces;
7. dependency and security gates green.

## 11. Documentation Standard

The final documentation must be:

1. implementation-backed;
2. Lotus-specific;
3. aligned with private banking vocabulary;
4. detailed enough for business users, engineers, operations, sales, pre-sales, and demos;
5. careful about raw vs smoothed contribution;
6. explicit about unsupported or degraded states;
7. free of generic imported source wording.

## 12. Risks and Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Carino correction changes existing numbers | High | Treat as intentional methodology correction, update downstream expectations, provide evidence and migration notes. |
| Upstream source economics are incomplete | High | Implement required `lotus-core` contract changes in the same RFC or explicitly mark unsupported/degraded fields. |
| Response evidence becomes too large | Medium | Use configurable evidence depth and safe summaries; keep raw artifacts in lineage where needed. |
| Docs over-claim product readiness | High | Tie every supported-feature claim to tests/live proof. |
| Downstream UI displays method status poorly | Medium | Update Gateway/Workbench contracts and tests in the same RFC. |
| Data-product catalog drift | Medium | Run mesh certification and platform validation before closure. |

## 13. Evidence Expectations

Required proof before final closure:

1. unit tests for Carino formulas and edge cases;
2. integration tests for contribution endpoint response evidence and errors;
3. OpenAPI quality and vocabulary gates;
4. domain-product and trust-telemetry validation;
5. Gateway consumer tests;
6. Workbench unit/e2e or live proof where UI behavior changes;
7. canonical front-office live evidence for `PB_SG_GLOBAL_BAL_001`;
8. docs/wiki validation;
9. CI green on all touched repos;
10. branch cleanup and stranded-truth reconciliation.

## 14. Approval Gate

Implementation may start only after this RFC is approved.

Approval decision needed:

1. approve the Carino correction and evidence-contract direction;
2. approve cross-repo changes where required;
3. approve no backward-compatibility constraint for misleading contribution APIs;
4. approve data-product promotion of `ContributionAnalytics:v1`;
5. approve documentation/wiki productization scope.
