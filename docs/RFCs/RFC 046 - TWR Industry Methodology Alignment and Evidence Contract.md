# RFC 046 - TWR Industry Methodology Alignment, Evidence Contract, and Data Product Hardening

- Status: Approved - In Implementation
- Date: 2026-05-10
- Owners: Performance Analytics Service
- Requires Approval From:
  - lotus-performance maintainers
  - lotus-platform maintainers
  - lotus-core maintainers when upstream source contracts, source products, or seeded evidence need
    changes
  - downstream maintainers when API, gateway, Workbench, report, AI, or product-realization
    contracts change
- Source Material:
  - `C:\Users\Sandeep\Downloads\twr-industry-docs.zip\twr-industry-docs`
- LinkedIn Communication Source:
  - `lotus-platform/thought-leadership/linkedin/content-ledger.md`
  - `lotus-platform/thought-leadership/linkedin/themes.md`
  - `lotus-platform/thought-leadership/linkedin/voice-and-style-guide.md`
- Related:
  - RFC-015
  - RFC-020
  - RFC-025
  - RFC-029
  - RFC-031
  - RFC-034
  - RFC-039
  - RFC-040
  - RFC-041
  - RFC-042
  - RFC-043
  - RFC-045
- Slice Evidence:
  - Slice 0: `docs/RFCs/RFC-046-source-map-and-gap-analysis.md`
  - Slice 1: `docs/RFCs/RFC-046-platform-automation-slice1.md`
  - Slice 2: `docs/RFCs/RFC-046-cleanup-and-structure-slice2.md`
  - Slice 3: `docs/RFCs/RFC-046-data-product-hardening-slice3.md`
  - Slice 4: `docs/RFCs/RFC-046-daily-twr-evidence-slice4.md`
  - Slice 5: `docs/RFCs/RFC-046-denominator-linkability-slice5.md`
  - Slice 6: `docs/RFCs/RFC-046-source-quality-slice6.md`

## 0. Critical Review Of The First Draft

The first RFC-046 draft correctly identified the TWR industry methodology gap and explicitly kept
composite calculation out of scope, but it was not yet strong enough to guide implementation with
minimal ambiguity.

| Area | First-draft gap | Tightening in this version |
| --- | --- | --- |
| Scope | The RFC described TWR evidence improvements, but did not separate product hardening, data product posture, and documentation productization strongly enough. | Added explicit architecture, data product, enterprise-grade, security, CI, documentation, and supported-feature sections. |
| Sequencing | The slices were directionally right, but platform automation, data product hardening, proof, hardening, final closure, and communication were not forceful enough. | Reworked slices so platform automation, cleanup, data product/platform hardening, implementation proof, second-last hardening, final closure, and post-completion communication are mandatory. |
| Acceptance criteria | Several slices accepted broad completion rather than proof-backed outcomes. | Added evidence requirements, validation gates, branch hygiene rules, and stop conditions. |
| Data mesh | Data mesh was present but not central. | Added explicit producer-product requirements, ownership, metadata, discoverability, trust telemetry, lineage, source supportability, SLO, and consumer contract expectations. |
| CI and security | CI/security were implied through governance, not delivery-grade requirements. | Added GitHub async check monitoring, security/dependency hygiene, platform compliance, and production readiness requirements. |
| Documentation | The draft required docs, but did not sufficiently prevent generic methodology output. | Added hard requirement that final docs are detailed, implementation-backed, Lotus-specific, and grounded in actual code/API behavior after implementation. |
| Supported features | The draft warned against unsupported claims, but did not maintain a clear product ledger. | Added a supported-features ledger with promotion evidence and non-promotion rules. |
| Communication | There was no post-completion communication path. | Added a LinkedIn slice that drafts a truthful post only after implementation is complete and evidence-backed. |

This RFC is now approved for slice-by-slice implementation. Implementation must continue under the
strict slice gate defined below: no slice may start until the previous slice is implemented,
validated, reviewed, and documented.

## 1. Executive Summary

`lotus-performance` should align its Time-Weighted Return (TWR) implementation, tests, API
evidence, data product posture, and documentation with the reviewed industry TWR material while
preserving the stronger Lotus capabilities that already exist.

The current implementation is already more production-oriented than the industry documents in
several areas: stateful portfolio sourcing, benchmark-aware TWR, asynchronous execution, lineage
artifacts, inspection checks, supportability metrics, reset diagnostics, and data mesh posture.
The main gaps are not basic TWR computation. The gaps are API-visible calculation evidence,
semantic reason codes, denominator and linkability policy clarity, episode metadata, source data
quality visibility, deterministic edge-case coverage, enterprise data-product discoverability,
security/CI hardening, and Lotus-owned documentation.

This RFC is correctness-first and realization-first. It should not rewrite the TWR engine or widen
the calculation scope without evidence, but it may change existing APIs when that is the right
design. Backward compatibility is not a constraint for this RFC. If contracts change, all required
upstream and downstream repositories must be updated in the same RFC delivery so the business value
is realized end to end.

Composite calculation is explicitly out of scope for this RFC.

No follow-up RFC, second wave, or downstream-only realization track should be required for the
approved RFC-046 business value. Required upstream source work, platform work, downstream consumer
work, documentation, wiki, CI, security, and product realization belong inside this RFC. Only
explicit non-goals, such as composite calculation, may remain outside the RFC.

## 2. Business Outcomes

This RFC should make TWR in `lotus-performance` credible to four audiences:

1. portfolio and performance users who need explainable TWR values,
2. operations and support teams who need source-aware diagnostics and reason codes,
3. downstream product teams that need stable, well-described contracts,
4. banking technology buyers and architects who expect production-grade data products with clear
   ownership, evidence, security, observability, and governance.

The intended outcome is not a larger endpoint. The intended outcome is a better governed
performance data product: clearer calculations, stronger evidence, sharper contracts, better
documentation, better tests, stronger CI/security posture, and implementation-backed product
material.

## 3. Current Implementation Assessment

| Area | Assessment |
| --- | --- |
| Portfolio TWR | Implemented in stateless and stateful modes. |
| Benchmark-aware TWR | Implemented with stronger capability than the supplied industry docs, including stateful/vendor/calculated benchmark context. |
| Async execution and lineage | Implemented through the RFC-041 runtime and lineage artifact path. |
| Inspection and supportability | Implemented through RFC-045 inspection endpoints and artifacts. |
| Reset and NIP diagnostics | Strong foundation from RFC-043, but the API needs clearer semantic TWR reason codes and episode evidence. |
| Daily calculation evidence | Gap. Daily status, calculation method, denominator basis, flow timing, warnings, and reason codes are not first-class response evidence. |
| Zero, negative, and near-zero capital behavior | Gap. Existing behavior must be characterized before any policy change. |
| Linkability for returns less than or equal to `-100%` | Partially handled by reset logic, but not exposed through clear semantic linkability status. |
| Source classification | Partially implemented through inspection and normalization, but not sufficiently visible in calculation responses. |
| FX and currency evidence | Multi-currency support exists, but missing-FX and reporting-currency behavior need stronger tests and documentation. |
| Data product posture | Partially present through data mesh conventions, but must be reviewed end to end for ownership, metadata, discoverability, trust telemetry, SLOs, lineage, supportability, and consumer documentation. |
| CI, security, and platform compliance | Existing governance exists, but this RFC must verify and strengthen the posture needed for a bank-buyable product. |
| Group, composite, and sleeve TWR | Not part of this RFC. Composite calculation remains out of scope. Sleeve/group/composite support claims must not be promoted by this work. |
| Documentation and wiki | Needs detailed Lotus-specific, implementation-backed methodology, QA, API, data mesh, product, demo, and production-support material. |

## 4. Goals

1. Convert the reviewed industry TWR material into Lotus-owned, implementation-backed methodology,
   runbook, QA, and wiki material.
2. Add or strengthen calculation evidence for daily and linked portfolio TWR.
3. Make denominator basis, flow timing, calculation method, status, warning, and reason-code
   behavior explicit.
4. Strengthen deterministic tests for industry edge cases that apply to Lotus portfolio TWR.
5. Preserve existing Lotus capabilities: stateful sourcing, benchmark support, async execution,
   lineage, reset diagnostics, inspection, supportability, and data mesh evidence.
6. Strengthen `lotus-performance` as a true data product with clear ownership, discoverability,
   metadata quality, lineage, trust telemetry, consumer contracts, source supportability, SLOs,
   and production support material.
7. Improve CI, dependency hygiene, security posture, platform compliance, API certification,
   Swagger/OpenAPI quality, observability, structured logging, and enterprise readiness where gaps
   are discovered.
8. Improve `lotus-platform` automation and scaffolding for cross-cutting concerns that should not
   be solved repeatedly inside individual apps.
9. Choose the correct API contract even when it requires breaking changes.
10. Update all required upstream and downstream repositories in the same RFC when source contracts,
    API contracts, product surfaces, gateway orchestration, reporting, or AI evidence consumption
    are affected.
11. Keep README, docs, wiki, OpenAPI, API vocabulary, supported-features, context, and agent
    guidance aligned.
12. Produce a truthful post-completion LinkedIn draft based only on what was implemented and proven.
13. Fully realize the approved RFC-046 business value without requiring a follow-up RFC or second
    implementation wave.

## 5. Non-Goals

1. Do not implement composite calculation as part of this RFC.
2. Do not create a first-class composite, group, or sleeve TWR endpoint in this RFC.
3. Do not promote composite, group, or sleeve TWR as supported in `lotus-performance` because of
   this RFC.
4. Do not rewrite the TWR engine wholesale.
5. Do not silently change denominator or linkability behavior without characterization tests,
   migration notes, and approval.
6. Do not copy generic industry documentation into Lotus docs. Final documentation must use Lotus
   vocabulary and reflect implemented behavior.
7. Do not claim UI or demo readiness unless downstream Gateway/Workbench work is implemented,
   integrated, and proven as part of this RFC when required for business realization.
8. Do not treat platform automation gaps as local-only app work when they belong in
   `lotus-platform` scaffolding.
9. Do not draft public communication with aspirational or unimplemented claims.
10. Do not leave required upstream or downstream work as a follow-up RFC when it is necessary to
    realize the approved RFC-046 business value.

## 6. Architecture Direction

RFC-046 should keep TWR ownership clean:

1. `lotus-performance` owns TWR methodology, calculation evidence, calculation response semantics,
   OpenAPI, tests, inspection alignment, documentation, and supported-feature claims.
2. `lotus-core` owns source portfolio valuation, cashflow, transaction, and source timestamp truth
   consumed by stateful TWR.
3. Benchmark and FX evidence must preserve source authority and clearly indicate whether the value
   is sourced, calculated, missing, stale, degraded, or unsupported.
4. Inspection remains a supportability contract. Calculation responses may summarize source quality,
   but inspection artifacts remain the deeper support diagnostic surface.
5. Gateway and Workbench must be updated in the same RFC when their APIs, typed clients, panels,
   data loading, evidence displays, or product workflows need changes to consume the corrected
   `lotus-performance` contract.
6. Platform-level automation and scaffolding belong in `lotus-platform` when the gap is repeatable
   across apps.
7. `lotus-report`, `lotus-ai`, and other downstream consumers must be updated in the same RFC when
   TWR evidence, methodology, supportability, report input, AI evidence input, or product material
   contracts change.

The design must avoid mixing concerns:

1. calculation values,
2. calculation evidence,
3. source supportability,
4. inspection findings,
5. lineage artifacts,
6. product documentation,
7. public communication.

Each concern can reference the others, but no concern should become a dumping ground.

## 7. Stranded-Truth Baseline

Before this RFC was drafted, the required governance branch check found one unmerged branch:

| Branch | Governance path touched | Classification | Required action before implementation |
| --- | --- | --- | --- |
| `origin/feat/api-contract-hardening` | `docs/standards/api-vocabulary/lotus-performance-api-vocabulary.v1.json` plus TWR request/docs/tests outside the governance-path filter | Superseded for RFC-046 by current mainline | Do not merge. Slice 0 verified the durable public-input contract truth is already present on current mainline, while the branch itself is stale and would delete newer governance, wiki, RFC, inspection, domain-product, trust-telemetry, and runtime truth if merged. Evidence: `docs/RFCs/RFC-046-source-map-and-gap-analysis.md`. |

No implementation slice may close while required TWR, API vocabulary, docs, wiki, context,
supported-feature, OpenAPI, migration, workflow, or platform contract truth exists only on an
unmerged branch.

## 8. Source Authority and Data Mesh Boundary

| Source family | Owner | RFC posture |
| --- | --- | --- |
| Portfolio valuations and cashflow aggregates | `lotus-core` source products, consumed by `lotus-performance` | Preserve source refs, timestamps, supportability, source freshness, and degraded source behavior. |
| TWR calculation and linked return evidence | `lotus-performance` | Service-owned methodology, calculation evidence, tests, OpenAPI, docs, and data product contract. |
| Reset/NIP diagnostics | `lotus-performance`, with upstream source evidence where applicable | Preserve RFC-043 diagnostics and add semantic TWR evidence where needed. |
| Benchmark data | `lotus-performance` integration path and upstream benchmark source where configured | Preserve benchmark context and expose source/method supportability. |
| FX and reporting currency evidence | Upstream FX source plus `lotus-performance` calculation layer | Expose missing/stale FX behavior and reporting-currency assumptions. |
| Inspection findings | `lotus-performance` inspection subsystem | Keep separate from calculation, but align reason-code vocabulary and supportability language. |
| API and product composition | `lotus-gateway`, `lotus-workbench` | Downstream only if this RFC changes response contracts consumed by product surfaces. |
| Reporting and AI evidence consumption | `lotus-report`, `lotus-ai`, and related consumers | Update in the same RFC when TWR evidence, report input, or AI evidence input contracts change. |
| Platform governance and scaffolding | `lotus-platform` | Improve reusable automation/scaffolding where gaps are not app-specific. |

## 9. Data Product Requirements

`lotus-performance` must be treated as a governed data product, not only as a calculation service.
This RFC must assess and strengthen:

1. data product ownership and support boundaries,
2. producer and consumer declarations,
3. API contract clarity and discoverability,
4. field-level metadata and OpenAPI descriptions,
5. lineage and reproducibility,
6. methodology versioning,
7. source freshness and source-quality signaling,
8. trust telemetry and supportability evidence,
9. observability and bounded metrics,
10. structured logs and correlation identifiers,
11. health, liveness, readiness, and dependency diagnostics,
12. data classification and source classification of valuations, flows, FX, benchmark, and
    inspection evidence,
13. SLO or supportability posture where platform standards define it,
14. consumer-facing documentation for developers, operations, product, sales/pre-sales, and demos.

Promotion to supported product material requires implementation-backed evidence. Aspirational data
mesh wording is not enough.

## 10. Proposed Response Evidence Direction

The implementation should choose the clearest and most durable TWR response contract. Additive
fields are acceptable when they keep the contract clean, but breaking response changes are allowed
when they materially improve correctness, supportability, data product clarity, or downstream
realization. The exact field names must be finalized in the implementation slice and pass API
vocabulary review, but the evidence should cover:

1. calculation method,
2. denominator basis,
3. flow timing convention,
4. beginning market value,
5. ending market value,
6. external inflows,
7. external outflows,
8. adjusted capital,
9. performance P&L,
10. daily return,
11. linked return contribution,
12. status,
13. reason codes,
14. warnings,
15. methodology version,
16. episode or reset metadata where applicable,
17. source quality and supportability summary,
18. lineage or source-reference summary where available,
19. benchmark and FX supportability where relevant.

Verbose daily evidence may be gated behind an explicit output/detail option if payload size is a
concern. Summary status, warning, and supportability behavior should remain visible enough for
operators and downstream consumers to explain a result.

## 11. Status and Reason-Code Direction

New reason codes must use upper snake case and align with the existing Lotus vocabulary. Candidate
codes include:

1. `ZERO_CAPITAL`,
2. `NEGATIVE_CAPITAL`,
3. `NEAR_ZERO_CAPITAL`,
4. `INVALID_LINK_FACTOR`,
5. `DAILY_RETURN_LESS_THAN_OR_EQUAL_TO_MINUS_100`,
6. `EPISODE_RESET`,
7. `NO_INVESTED_CAPITAL`,
8. `MISSING_VALUATION`,
9. `MISSING_FX_RATE`,
10. `UNSUPPORTED_CASHFLOW_CLASSIFICATION`,
11. `SOURCE_QUALITY_DEGRADED`,
12. `BENCHMARK_UNAVAILABLE`.

Final codes must be narrowed during implementation and documented in OpenAPI, docs, wiki, and tests.
Existing reset diagnostics must remain available unless a later approved migration removes them.

## 12. Supported-Features Ledger

| Feature or product claim | Current posture | RFC-046 promotion rule |
| --- | --- | --- |
| Stateless portfolio TWR | Supported baseline | Keep supported if existing tests and RFC-046 regression pack pass. |
| Stateful portfolio TWR sourced from Lotus source products | Supported baseline | Keep supported if source-quality, lineage, and supportability evidence remain clear and tested. |
| Benchmark-aware TWR | Supported baseline | Keep supported if benchmark method/source evidence and calendar-gap behavior are tested and documented. |
| Async TWR execution and lineage artifacts | Supported baseline | Keep supported if live proof captures reproducible execution and lineage evidence. |
| TWR inspection and supportability | Supported baseline through RFC-045 | Keep supported and cross-link calculation evidence without merging inspection into calculation. |
| Daily TWR calculation evidence | Proposed | Promote only after API/OpenAPI, tests, docs, examples, and supported-feature updates are complete. |
| Semantic TWR reason codes and warnings | Proposed | Promote only after deterministic tests cover zero/negative/near-zero capital, invalid link factors, missing data, and source-quality degradation. |
| TWR data product documentation | Proposed | Promote only after docs and wiki are implementation-backed, reviewed, and published. |
| Enterprise data product hardening | Proposed | Promote only after data mesh, CI, security, observability, API certification, and platform compliance evidence is captured. |
| Composite TWR calculation | Out of scope | Must not be promoted by this RFC. |
| Group or sleeve TWR calculation | Out of scope | Must not be promoted by this RFC. |
| Public LinkedIn communication | Post-completion draft only | Draft only after implementation is complete and only with implementation-backed, employer-safe claims. |

## 13. Implementation Slices

Implementation must proceed slice by slice. No slice may start until the previous slice is
implemented, validated, reviewed, and documented. If a slice discovers a platform or scaffolding gap
that should benefit future Lotus applications, the gap must be handled at platform level unless
explicitly classified as app-specific.

### Slice 0 - Source Map, Gap Analysis, and Branch Reconciliation

Scope:

1. Reconcile `origin/feat/api-contract-hardening`.
2. Create or update a source map and gap analysis for this RFC.
3. Map each industry requirement to `supported`, `supported-with-gap`, `deferred`, or
   `not-applicable`.
4. Identify source ownership for valuations, cashflows, FX, benchmarks, reset events, inspection
   evidence, data mesh metadata, and downstream consumers.
5. Review the current RFC again after branch reconciliation and tighten it if unique branch truth
   changes the plan.
6. Classify every required upstream and downstream repository change as in-scope, not-required, or
   explicitly out-of-scope because it belongs to an RFC-046 non-goal.

Acceptance:

1. No durable TWR truth required by this RFC remains stranded on an unmerged branch.
2. Composite calculation is recorded as out of scope.
3. The source map is implementation-backed and does not promote unsupported features.
4. Downstream and upstream dependencies are explicitly classified as required, optional, deferred,
   or no-change.
5. No required source, platform, gateway, Workbench, report, AI, or consumer change is left as an
   unspecified follow-up.

### Slice 1 - Platform Automation and Scaffolding Improvement

Scope:

1. Identify gaps in `lotus-platform` automation that should already be handled as part of platform
   scaffolding rather than rediscovered in `lotus-performance`.
2. Improve `lotus-platform` automation when repeatable gaps are found.
3. Identify which cross-cutting concerns should be scaffolded by default for new applications.
4. Improve app scaffolding automation so future apps start with stronger governance from day one.
5. Cover API certification pattern, Swagger quality, observability, health endpoints, structured
   logging, error handling, test scaffolding, CI defaults, documentation scaffolding, governance
   hooks, data mesh onboarding, security baseline, wiki scaffolding, and evidence patterns where
   applicable.
6. During implementation, continue moving newly discovered repeatable concerns into platform
   automation instead of leaving them local to `lotus-performance`.

Acceptance:

1. A platform/scaffolding gap ledger exists.
2. Any implemented platform improvement has tests or validation evidence in `lotus-platform`.
3. Any no-change decision is explicit and justified.
4. The output benefits future Lotus applications, not only RFC-046.

### Slice 2 - Cleanup and Structure

Scope:

1. Remove dead TWR-adjacent code if found.
2. Improve repository structure where needed for TWR evidence, methodology, tests, and docs.
3. Improve documentation structure and reduce sprawl.
4. Move the right long-lived product/operator material to repo-local wiki.
5. Avoid duplicate documentation across repo docs and wiki.
6. Ensure the wiki source is usable and reflects the true post-RFC application state.

Acceptance:

1. Existing tests pass after cleanup.
2. No cosmetic churn is introduced.
3. TWR evidence work has a clean implementation home.
4. Wiki/source-doc layering is explicit: RFC for execution plan, docs for deep methodology and
   engineering detail, wiki for durable product/operator/user-facing material.

### Slice 3 - Data Product and Platform Hardening

Scope:

1. Assess and strengthen `lotus-performance` as a proper data product.
2. Ensure relevant data mesh requirements and standards are met.
3. Improve API posture, metadata quality, discoverability, contract clarity, and documentation
   quality.
4. Review CI, dependency hygiene, security vulnerabilities, platform compliance, production
   readiness, observability, structured logs, bounded metrics, health/readiness/liveness, and
   supportability.
5. Identify and close gaps needed to make `lotus-performance` enterprise-grade, production-ready,
   and bank-buyable.

Acceptance:

1. Data product gaps are closed or formally tracked with owner, severity, and treatment.
2. Security and dependency findings are fixed or documented with governed treatment.
3. CI and platform compliance gaps are closed or tracked with explicit rationale.
4. Data mesh documentation, metadata, lineage, and consumer contract posture are implementation
   backed.

### Slice 4 - Daily TWR Calculation Evidence Contract

Scope:

1. Add internal and API-visible daily calculation evidence for portfolio TWR.
2. Include method, denominator basis, flow timing, beginning value, ending value, external flows,
   adjusted capital, performance P&L, daily return, status, warnings, and reason codes.
3. Decide whether verbose evidence is default or gated by an explicit output/detail option based on
   product usability and downstream realization, not backward compatibility.
4. Ensure evidence is documented as product contract, not a debug-only afterthought.

Acceptance:

1. Unit and integration tests cover no-flow, deposit-neutralized, withdrawal-neutralized, same-day
   deposit/withdrawal, and denominator evidence.
2. OpenAPI examples describe the new evidence.
3. If existing clients break because the corrected contract is materially better, all affected
   downstream consumers are updated in the same RFC.

### Slice 5 - Denominator, Linkability, Reset, and Episode Semantics

Scope:

1. Characterize current behavior for zero capital, negative capital, near-zero capital, `-100%`,
   less than `-100%`, full withdrawal, refunding, and reset periods.
2. Add semantic reason codes and warnings where behavior is currently opaque.
3. Preserve RFC-043 reset diagnostics while adding TWR-specific episode explanation.
4. Do not change denominator policy until tests prove the current behavior is incorrect or
   insufficient.

Acceptance:

1. Every policy edge case has deterministic tests.
2. Linkability failures are visible and explainable.
3. Reset and episode metadata is either exposed or explicitly deferred with rationale.

### Slice 6 - Stateful Source Classification and Data Quality Evidence

Scope:

1. Preserve and expose relevant source classification from stateful portfolio timeseries.
2. Make unsupported cashflow labels, missing valuation points, stale data, source conflicts, and
   quality warnings visible in calculation supportability evidence.
3. Align calculation evidence with RFC-045 inspection findings without merging inspection and
   calculation responsibilities.

Acceptance:

1. Tests cover unsupported cashflow types, missing dates, stale values, source conflicts, and
   degraded source quality.
2. Data mesh lineage and source-owner boundaries remain explicit.

### Slice 7 - FX, Currency, Benchmark, and Calendar Alignment

Scope:

1. Clarify reporting currency, valuation FX, flow FX, transaction FX, benchmark FX, and missing-FX
   behavior.
2. Expose benchmark source/method supportability in TWR evidence.
3. Strengthen calendar-alignment handling for portfolio and benchmark dates.

Acceptance:

1. Tests cover missing FX, multi-currency evidence, benchmark gaps, and benchmark supportability.
2. Documentation explains Lotus currency and benchmark behavior without overstating support.

### Slice 8 - Composite/Group/Sleeve Boundary Documentation

Scope:

1. Document that composite calculation is out of scope for this RFC.
2. Confirm whether any existing docs or supported-feature entries imply composite, group, or sleeve
   TWR support and correct them if needed.
3. Remove or correct any current misleading product, API, or wiki wording that implies composite
   support.

Acceptance:

1. No composite calculation code is added.
2. No composite, group, or sleeve TWR support claim is promoted.
3. Supported-features and docs are truthful.
4. No future-RFC wording is used to defer any required RFC-046 business value.

### Slice 9 - API, OpenAPI, Vocabulary, and Cross-Repo Contract Realization

Scope:

1. Update response models, OpenAPI examples, API vocabulary inventory, no-alias guard coverage, and
   docs contract tests for any additive evidence fields.
2. Redesign existing APIs when the corrected TWR contract requires it.
3. Inspect downstream consumers for strict parsing, typed client assumptions, UI assumptions,
   report input assumptions, AI evidence assumptions, and gateway orchestration assumptions.
4. Patch `lotus-gateway`, `lotus-workbench`, `lotus-report`, `lotus-ai`, or other consumers when
   this RFC changes contracts they consume or when integration is required to realize the business
   value.
5. Patch `lotus-core` or upstream source systems when required source evidence, cashflow
   classification, FX, benchmark, valuation, or lineage behavior is missing and within the RFC-046
   realization boundary.
6. Ensure all APIs touched by this RFC are properly certified.

Acceptance:

1. OpenAPI quality, vocabulary, no-alias, and endpoint certification gates pass.
2. Upstream and downstream impact is implemented or explicitly proven as no-change.
3. Swagger is grouped correctly and includes clear what/when/how guidance, full request/response
   examples, and field-level descriptions, types, and examples.
4. Every downstream consumer uses the correct `lotus-performance` endpoint and contract for the
   feature it realizes.
5. No required contract realization remains outside this RFC.

### Slice 10 - Lotus TWR Documentation and Wiki Productization

Scope:

1. Produce Lotus-owned methodology and product documentation from the industry material.
2. Cover daily TWR calculation, flow timing, denominator policy, reset/episode behavior, source data
   requirements, FX/currency behavior, benchmark behavior, QA cases, production support, API usage,
   data mesh responsibilities, operational behavior, and limitations.
3. Update repo-local wiki for developer, business, operations, sales/pre-sales, and demo audiences.
4. Ensure final documentation is detailed, implementation-backed, and fully aligned to actual
   `lotus-performance` design, behavior, APIs, constraints, and supported capabilities.

Acceptance:

1. Documentation is not generic and does not copy vendor/industry wording.
2. Every product claim maps to implementation evidence, tests, APIs, docs, or explicit limitation.
3. Wiki source passes check-only sync before merge.
4. Supported-feature wording matches proven behavior.

### Slice 11 - Deterministic QA Regression Pack

Scope:

1. Convert applicable industry QA scenarios into high-value tests.
2. Cover arithmetic-sum anti-test, geometric linking, deposits, withdrawals, zero/negative capital,
   near-zero capital, short and leveraged portfolio behavior where portfolio TWR supports it, reset
   episodes, missing FX, benchmark gaps, and source-quality degraded states.
3. Mark composite, group, and sleeve scenarios as out of scope for this RFC.

Acceptance:

1. Tests validate values, statuses, warnings, reason codes, evidence fields, and source-quality
   behavior.
2. Every adopted industry case maps to a Lotus test or documented deferred item.
3. Tests are meaningful and increase confidence rather than only increasing count.

### Slice 12 - Implementation Proof

Scope:

1. Prove the implementation end to end against this RFC.
2. Capture evidence from the live application where live proof is required.
3. Verify the evidence critically, including returned figures, statuses, reason codes, warnings,
   lineage refs, source quality, benchmark/FX behavior, OpenAPI certification, data product
   metadata, logs, metrics, and supportability.
4. Identify gaps, inconsistencies, and loose ends.
5. Iterate until the implementation is genuinely gold standard.
6. Capture proof artifacts under non-git-tracked `output/` and reference them from slice evidence.

Acceptance:

1. Proof artifacts are reproducible.
2. Stateful TWR evidence preserves source ownership and supportability.
3. The proof review records issues found and fixes applied.
4. No material gap is deferred without owner, severity, and rationale.

### Slice 13 - Second-Last Hardening and Review

Scope:

1. Perform a proper code review of the full implementation.
2. Tighten loose ends, duplicate logic, dead code, weak tests, error handling, API descriptions,
   security posture, observability, data mesh posture, and platform compliance.
3. Verify API certification pattern compliance.
4. Ensure all APIs are properly certified.
5. Ensure Swagger is complete and high quality:
   - grouped correctly,
   - clear what/when/how guidance for each endpoint,
   - full request and response examples,
   - every attribute has description, type, and example value.
6. Ensure error handling is complete, correct, and properly tested.
7. Ensure security vulnerabilities are addressed or formally tracked with clear treatment.
8. Make final quality improvements before closure.

Acceptance:

1. Review findings are resolved or explicitly deferred with owner, severity, and rationale.
2. API, OpenAPI, data mesh, security, platform compliance, CI, docs, and wiki posture are clean.
3. Local validation gates pass.
4. The implementation is ready for final closure rather than relying on closure to find quality
   issues.

### Slice 14 - Final Closure

Scope:

1. Update documentation, README where applicable, repo-local wiki, supported-features, endpoint
   certification, RFC status, and repository context.
2. Consciously review whether skills, guidance, documentation, or agent context should be improved
   for future work, faster ramp-up, and stronger agent effectiveness.
3. Add, remove, tighten, or clarify durable guidance where needed. If no changes are needed, record
   that as a deliberate no-change outcome.
4. Rerun stranded-truth reconciliation.
5. Confirm clean git status, CI posture, docs tests, wiki source, supported-features, context,
   downstream status, branch hygiene, and PR merge readiness.
6. Publish wiki after merge using governed wiki synchronization.

Acceptance:

1. Truth is merged to `main`, not only present on a feature branch.
2. Published wiki matches repo-local wiki source.
3. Supported-features list reflects only implementation-backed product material.
4. Agent context, skills, and guidance decisions are recorded and synchronized where applicable.
5. No unclassified governance branches remain.

### Slice 15 - Post-Completion Communication

Scope:

1. Inspect the LinkedIn content ledger, themes, voice guide, and recent drafts/posts before
   drafting.
2. Draft one LinkedIn post after implementation is complete.
3. Base the post only on what was actually implemented and proven.
4. Keep it truthful, grounded, employer-safe, and practitioner-led.
5. Avoid confidential details, active-work clues, employer implications, unsupported Lotus
   capability claims, and direct product marketing.
6. Save the draft under `lotus-platform/thought-leadership/linkedin/drafts/` and update the ledger
   only if the user wants a persisted draft during implementation.

Acceptance:

1. The post reflects implementation-backed outcomes, not aspirational claims.
2. The post follows the Lotus LinkedIn voice guide.
3. The content ledger is updated if a draft file is created.
4. The post is not marked as posted unless the user explicitly confirms publication.

## 14. Testing Requirements

The implementation must include meaningful tests for:

1. no-flow TWR,
2. external deposit neutralization,
3. external withdrawal neutralization,
4. same-day deposit and withdrawal,
5. geometric linking versus arithmetic summing,
6. zero capital,
7. negative capital,
8. near-zero capital,
9. returns less than or equal to `-100%`,
10. full withdrawal and refunding episodes,
11. missing valuation data,
12. unsupported cashflow classification,
13. missing FX data,
14. benchmark calendar gaps,
15. stateful source-quality degraded behavior,
16. OpenAPI examples and response schema,
17. API vocabulary and no-alias governance,
18. documentation contract tests,
19. data product metadata and lineage behavior,
20. security and dependency posture where repository-native checks exist,
21. error handling and degraded-state response behavior,
22. platform automation changes if Slice 1 updates `lotus-platform`.

Composite, group, and sleeve QA scenarios from the industry pack are not implementation tests for
this RFC. They may be retained as out-of-scope notes or future-RFC candidates.

## 15. API Certification and Swagger Standard

Every endpoint touched by RFC-046 must be certified with:

1. route and tag correctness,
2. field-level descriptions,
3. field-level example values,
4. request examples,
5. response examples,
6. error examples,
7. clear what/when/how endpoint guidance,
8. no legacy alias names,
9. vocabulary inventory coverage,
10. explicit degraded, unsupported, and validation behavior where applicable.

Swagger quality is a product requirement. Thin schema-only documentation is not sufficient.

## 16. CI, Security, and GitHub Operating Requirements

Implementation must use GitHub effectively:

1. create or continue a remote feature branch,
2. use small, meaningful, well-scoped commits,
3. open PRs for every affected repository when cross-repo implementation is required,
4. monitor pipelines at regular intervals,
5. fix failures promptly,
6. keep branch hygiene under control,
7. use repository-native validation commands,
8. keep CI health, security posture, dependency hygiene, and PR evidence truthful,
9. coordinate upstream and downstream PR ordering so consumers are not merged against stale
   contracts.

Required lanes:

1. Feature Lane: lint, unit tests, targeted contract/schema/docs checks.
2. PR Merge Gate: integration tests, coverage, OpenAPI, vocabulary, no-alias, security/dependency,
   data mesh, and docs/wiki checks where relevant.
3. Main Releasability: post-merge verification and wiki publication.
4. Platform End-to-End Validation: required only if this RFC affects canonical product surfaces or
   platform runtime assumptions.

## 17. Documentation and Wiki Requirements

Closure must update, as applicable:

1. `docs/methodologies/metrics/metric-twr-base-return.md`,
2. `docs/guides/twr.md`,
3. a TWR industry review findings document,
4. a TWR QA/regression mapping document,
5. a TWR production support runbook,
6. API examples and OpenAPI descriptions,
7. data product and data mesh documentation,
8. `wiki/Supported-Features.md`,
9. TWR wiki material for developers, business users, operations, sales/pre-sales, and client demos,
10. `REPOSITORY-ENGINEERING-CONTEXT.md` only if repository operating truth changes,
11. Lotus skills, central context, or local skill copies only when operating guidance changes.

Final documentation must be detailed, implementation-backed, and fully grounded in the actual
`lotus-performance` implementation. It must describe actual design, behavior, APIs, constraints,
failure modes, source dependencies, supported capabilities, limitations, operational behavior, and
evidence. Docs must not claim composite calculation support under this RFC.

## 18. Risks and Controls

| Risk | Control |
| --- | --- |
| API evidence fields create integration impact | Choose the correct contract, inspect downstream consumers, and update every affected consumer in the same RFC delivery window. |
| TWR methodology docs become generic | Require every claim to map to actual implementation, tests, OpenAPI, or explicit limitation. |
| Data mesh posture remains decorative | Add data product hardening slice with metadata, lineage, supportability, trust telemetry, discoverability, and consumer-contract acceptance criteria. |
| Platform gaps are solved locally and repeated later | Mandatory platform automation/scaffolding slice with reusable improvements or deliberate no-change evidence. |
| Security or dependency findings are ignored | Security/dependency checks must be run where repository-native support exists; findings must be fixed or formally tracked. |
| Swagger remains technically valid but weak | API certification requires what/when/how guidance, examples, and field-level descriptions/types/examples. |
| Composite support is accidentally implied | Composite calculation is a non-goal, QA exclusion, supported-feature non-promotion rule, and final docs constraint. |
| CI drifts while implementation continues | GitHub checks must be monitored asynchronously and fixed promptly. |
| Public communication overclaims | LinkedIn draft happens only after completion and must use implementation-backed, employer-safe language. |

## 19. Rollout and Compatibility

1. Prefer the correct product and data contract over backward compatibility.
2. Breaking changes are allowed when they materially improve correctness, clarity, supportability,
   or product realization.
3. Every breaking change must include migration notes, OpenAPI/vocabulary updates, test coverage,
   and same-RFC updates to all affected upstream and downstream repositories.
3. Keep existing reset diagnostics available while adding semantic TWR reason codes.
4. Preserve existing stateless, stateful, benchmark, async, lineage, and inspection behavior.
5. Do not promote new supported-feature claims until proof and wiki publication are complete.
6. Keep composite calculation out of scope.
7. No required RFC-046 realization work may be deferred to a follow-up RFC or second wave.

## 20. Definition of Done

This RFC is complete only when:

1. all approved slices are implemented and validated,
2. composite calculation remains out of scope and unimplemented,
3. tests cover adopted industry edge cases,
4. OpenAPI, vocabulary, no-alias, data mesh, docs, wiki, CI, security, and platform compliance
   checks pass or governed deviations are formally tracked,
5. upstream and downstream repositories are updated or proven unaffected,
6. README/docs/wiki/supported-features/context truth is aligned,
7. skills, guidance, documentation, and agent context have been consciously reviewed and updated or
   explicitly left unchanged with rationale,
8. PR CI is green,
9. required truth is merged to `main`,
10. wiki is published after merge,
11. branch hygiene confirms no unclassified governance truth remains,
12. a truthful post-completion LinkedIn draft is prepared if requested for persistence, based only
    on implemented and proven outcomes,
13. every downstream consumer that should realize RFC-046 business value uses the right
    `lotus-performance` endpoint and contract,
14. no required business-value, integration, platform, source, or consumer work is left to a
    follow-up RFC or second wave.
