# RFC 048 - Attribution Industry Methodology Alignment and Evidence Contract

Status: Approved - implementation in progress

Owner repository: `lotus-performance`

Primary domain: performance analytics

Source package: `C:\Users\Sandeep\Downloads\attribution-industry-docs.zip\attribution-industry-docs`

Created: 2026-05-11

Implementation posture: approved for slice-by-slice implementation by the operator on 2026-05-11.
No implementation slice may start until the previous slice is fully implemented, validated,
reviewed, documented, committed, and in a solid state. Slice 0 baseline evidence is captured in
`docs/RFCs/RFC-048-source-map-and-baseline-slice0.md`.

## 0. Critical Review Before Implementation

The supplied attribution documentation is materially useful, but it is generic industry material.
It must not be copied into Lotus as generic methodology text. The implementation plan must convert
the useful ideas into Lotus-owned, implementation-backed behavior and documentation using Lotus
private-banking vocabulary, current `lotus-performance` contracts, and the Lotus data-product
governance model.

Current `lotus-performance` attribution is already beyond a simple Brinson prototype:

1. `POST /performance/attribution` supports stateless and stateful attribution modes.
2. Stateful attribution sources portfolio, position, benchmark, and FX inputs through governed
   `lotus-core` integration paths.
3. The engine supports Brinson-Fachler and Brinson-Hood-Beebower formulas.
4. Multi-level grouping is supported through ordered `group_by` dimensions.
5. Currency-aware attribution is supported through local/base/FX return fields when
   `currency_mode="BOTH"`.
6. Async execution, lineage artifacts, execution lifecycle tracking, supportability metadata, and
   bounded supportability metrics already exist.
7. Downstream realization through `lotus-gateway` and `lotus-workbench` already exists for
   performance workspace attribution panels.

The current implementation is not yet bank-buyable as a fully governed attribution data product.
The source documentation highlights gaps that matter for production support, auditability, and
client-facing explanation:

1. attribution status and warning semantics are not first-class enough;
2. daily raw attribution rows are retained in lineage but not exposed through a support-safe API
   contract;
3. off-benchmark, benchmark-only, unclassified, missing benchmark, missing benchmark return,
   currency mismatch, and material residual conditions need explicit controlled reason codes;
4. interaction treatment is always emitted as a separate effect, with no explicit display policy for
   folding interaction into selection where a client report requires it;
5. residual policy exists numerically through reconciliation but lacks materiality thresholds,
   status classification, and operator-ready residual diagnostics;
6. stateful attribution has strong source integration, but benchmark/classification/calendar
   alignment controls need to be promoted into documented API evidence;
7. attribution is not yet promoted as a full governed domain data product with attribution-specific
   trust telemetry, SLO/access/evidence posture, and platform mesh proof;
8. methodology docs are useful but should be upgraded to the stricter implementation-backed
   methodology standard with formulas, deterministic steps, validation behavior, examples, and
   known non-goals;
9. Swagger/OpenAPI quality must be certified after any response or error-contract changes;
10. live proof must cover the front-office canonical stack, not just unit and integration tests.

This RFC is written as an execution guide, not a loose proposal. Once approved, work must proceed
strictly slice by slice. A slice is complete only when implemented, validated, reviewed, documented,
committed, and proven with appropriate evidence. If API contracts change, downstream consumers must
be updated in the same RFC. If upstream source fields are required, upstream changes may be made in
the same RFC after proving they belong to source-data authority rather than local attribution logic.

## 1. Executive Summary

This RFC proposes a gold-standard attribution upgrade for `lotus-performance` based on the supplied
industry attribution documentation. The target outcome is a private-banking attribution capability
that explains portfolio active return versus benchmark in a way that is mathematically correct,
source-backed, auditable, supportable, observable, and safe for banker, operations, and client-demo
use.

The goal is not to build every advanced attribution model mentioned in the supplied documents.
The goal is to adopt what genuinely improves Lotus now:

1. stronger Brinson attribution evidence;
2. explicit active return, allocation, selection, interaction, residual, and linking semantics;
3. controlled statuses and reason codes for support teams and downstream panels;
4. richer daily and period evidence where safe and useful;
5. stronger classification, benchmark alignment, off-benchmark, benchmark-only, and unclassified
   handling;
6. data-product certification for attribution as a governed Lotus performance product;
7. implementation-backed docs, wiki, API reference, and support runbook material;
8. cross-repo downstream realization through `lotus-gateway` and `lotus-workbench` when contracts
   change;
9. live front-office proof on the canonical stack.

Advanced fixed-income factor attribution, derivative exposure attribution, composite attribution,
and GIPS composite workflows are not automatically in scope just because they appear in the source
docs. They must be included only if current Lotus source data, ownership, and business value justify
same-RFC delivery. Otherwise this RFC must explicitly document the current supported boundary and
avoid claiming unsupported capability.

## 2. Business Outcome

Private bankers, portfolio managers, investment counsellors, CIO-office users, operations teams,
and client-service teams need attribution analytics that answer:

1. did the portfolio outperform or underperform its benchmark;
2. which allocation decisions helped or hurt;
3. which security or segment selection decisions helped or hurt;
4. whether interaction is material and how it is presented;
5. whether cash, currency, off-benchmark exposure, unclassified exposure, or benchmark-only
   avoidance drove the story;
6. whether the result reconciles to active return;
7. whether residuals are immaterial rounding noise or evidence of source/methodology issues;
8. whether the attribution result is safe for a client meeting, requires operations review, or is
   unavailable because source data is not reliable.

The product outcome is an attribution data product that a bank could confidently buy:

1. formulas are correct and tested against deterministic examples;
2. APIs are clear, documented, certified, and downstream-safe;
3. output semantics are private-banking appropriate;
4. data lineage, supportability, and residual evidence are explainable;
5. operational telemetry is bounded and safe;
6. documentation is useful to developers, business users, operations, sales, pre-sales, and demo
   preparation;
7. unsupported advanced methods are clearly named as unsupported rather than implied.

## 3. Source Documentation Review

| Source file | Adopt into Lotus? | RFC treatment |
| --- | --- | --- |
| `01-attribution-methodology.md` | Yes | Convert into Lotus methodology material for contribution versus attribution, active return, allocation, selection, interaction, residuals, gross/net posture, and when attribution is not appropriate. |
| `02-brinson-calculation.md` | Yes | Use for Brinson-Fachler/BHB formulas, active contribution, residual calculations, interaction display policy, and deterministic formula tests. |
| `03-daily-attribution-inputs.md` | Yes | Use for daily input validation, daily portfolio/benchmark alignment, contribution reconciliation, benchmark calendar handling, daily row evidence, and source-quality reason codes. |
| `04-multi-period-attribution-linking.md` | Yes | Use for raw versus linked effect semantics, active-return target, smoothing/linking evidence, and support explanation of multi-period differences. |
| `05-benchmark-and-classification-alignment.md` | Yes | Use for taxonomy alignment, portfolio-only/benchmark-only segments, benchmark version, classification mapping, model/SAA benchmark boundary, and benchmark calendar policy. |
| `06-group-hierarchy-and-sleeve-attribution.md` | Partially | Adopt hierarchy and sleeve vocabulary where current source data supports it. Composite or firm-level aggregation remains explicitly gated unless source ownership and implementation evidence are added in this RFC. |
| `07-currency-fixed-income-and-derivative-attribution.md` | Partially | Adopt currency explanation and Brinson boundary warnings. Do not claim fixed-income factor or derivative exposure attribution unless implemented and proven. |
| `08-edge-cases-and-controls.md` | Yes | Use for zero capital, negative weights, shorts, off-benchmark exposure, missing benchmark data, unclassified assets, stale prices, FX mismatch, and residual controls. |
| `09-implementation-design.md` | Yes | Use for pipeline boundaries, controlled statuses, reason-code model, auditability, caching/restatement posture, and observability. |
| `10-qa-regression-pack.md` | Yes | Convert into Lotus deterministic unit, integration, contract, downstream, and live proof matrix. |
| `11-production-support-agent-playbook.md` | Yes | Convert into Lotus support runbook and safe explanation material grounded in actual API fields and lineage artifacts. |
| `attribution-industry-playbook-all-in-one.md` | Reference only | Use only as consolidated review source. Do not commit generic all-in-one wording into Lotus docs. |

## 4. Current Implementation Assessment

### 4.1 Current Strengths

| Area | Current Lotus evidence | Assessment |
| --- | --- | --- |
| Attribution engine | `engine/attribution.py` | Strong baseline for Brinson-Fachler, BHB, top-down scaling, hierarchy aggregation, and currency effects. Needs stronger explicit policy/status output. |
| API request models | `app/models/attribution_requests.py`, `app/models/attribution_analytics_requests.py` | Good schema baseline with stateless/stateful input modes, grouping, model, frequency, linking, and currency controls. Needs stronger policy controls and examples if contract changes. |
| API response models | `app/models/attribution_responses.py` | Good response baseline with group context, level totals, reconciliation, currency attribution, benchmark context, and supportability. Needs statuses, reason codes, material residual classification, and possibly safe daily evidence. |
| Stateful source integration | `app/services/attribution_mode_service.py`, `app/services/stateful_attribution_input_service.py` | Strong upstream integration with `lotus-core`. Needs explicit proof of benchmark/classification/calendar alignment and source-quality failure behavior. |
| Runtime lifecycle | `app/services/attribution_service.py`, execution registry, async result store | Good async and lineage posture. Needs attribution-specific support evidence surfaces and status/reason-code persistence if added. |
| Tests | `tests/unit/engine/test_attribution.py`, `tests/integration/test_attribution_api.py`, `tests/unit/models/test_attribution_models.py` | Meaningful existing coverage. Needs source-doc QA cases, edge cases, residual thresholds, reason-code assertions, and live canonical stack evidence. |
| Docs | `docs/guides/attribution.md`, `docs/technical/attribution-endpoint-certification.md`, metric docs | Good current docs. Needs implementation-backed methodology v3 detail, support playbook, data-product material, and wiki updates. |
| Downstream consumers | `lotus-gateway`, `lotus-workbench` | Current consumers exist for performance workspace attribution. Any new contract fields must be preserved or displayed downstream through gateway-first integration. |
| Observability | `calculation_supportability`, bounded Prometheus labels | Good general posture. Needs attribution-specific counts for status/reason families if implemented, without high-cardinality or sensitive labels. |

### 4.2 Current Gaps

| Gap | Severity | Evidence | Required direction |
| --- | --- | --- | --- |
| Status and reason-code contract is too light | P0 | `AttributionResponse` has reconciliation and supportability but no controlled attribution status/reason list | Add status and reason-code model covering valid, warning, partial, unavailable, invalid, missing benchmark, missing benchmark return, unclassified, off-benchmark, benchmark-only, material residual, currency mismatch, and linking issues. |
| Residual policy is not production-grade | P0 | `Reconciliation.residual` exists but no materiality thresholds or classification | Add configurable residual thresholds, materiality classification, test cases, and docs. |
| Daily attribution evidence is not support-safe enough | P1 | `single_period_effects.csv` lineage exists but support users have no controlled daily evidence contract | Add either response-gated daily evidence or a support-safe evidence endpoint/artifact contract with redaction and bounded field semantics. |
| Interaction treatment is not configurable | P1 | Engine always emits separate interaction | Add or explicitly reject interaction folding. If added, update API, downstream, docs, and tests. |
| Off-benchmark and benchmark-only handling lacks explicit reason codes | P1 | Outer alignment preserves missing side as zero but does not expose semantic status | Preserve reconciliation while surfacing controlled reason codes and affected segment evidence. |
| Classification alignment is implicit | P1 | Missing group labels become `unknown`; no status indicates unclassified/missing mapping | Promote unclassified/missing classification behavior into explicit Lotus vocabulary, reason codes, and docs. |
| Benchmark/calendar/currency alignment is not strongly certified | P1 | Stateful path resolves benchmark inputs, but docs/tests need richer proof | Add alignment checks, degraded/error behavior, and live canonical proof. |
| Attribution data product is incomplete | P1 | Domain-product declarations and trust telemetry do not yet promote attribution as its own product to the same standard as other analytics products | Add attribution producer declaration, telemetry, SLO/access/evidence posture, and platform mesh validation if approved. |
| OpenAPI examples need post-RFC field quality | P1 | Existing fields have descriptions, but new status/evidence fields will need full examples and error contracts | Certify Swagger quality after model changes. |
| Docs are not yet complete methodology v3 for attribution | P1 | Existing guides are useful but not full variable dictionary/algorithm/status/example/runbook suite | Upgrade docs and wiki after implementation is final. |
| Advanced fixed-income, derivative, and composite attribution are not implemented | P2 | No fixed-income factor, derivative exposure, or composite engine exists | Keep unsupported boundaries explicit unless same-RFC source data and tests prove implementation. |

## 5. Architecture Direction

Target architecture:

```text
lotus-core source observations and benchmark inputs
  -> stateful attribution input resolver
  -> normalized daily portfolio/benchmark segment state
  -> classification, calendar, currency, and benchmark alignment controls
  -> Brinson daily effect engine
  -> residual/status/reason-code validator
  -> multi-period linking/smoothing evidence builder
  -> attribution API response, lineage, and support-safe evidence
  -> lotus-gateway performance workspace contract
  -> lotus-workbench attribution panels, degraded states, and demo evidence
```

Architecture rules:

1. `lotus-performance` remains the attribution methodology and calculation authority.
2. `lotus-core` remains source-data authority for portfolio state, positions, transactions,
   classifications, benchmark assignment, benchmark components, and FX source inputs.
3. `lotus-gateway` must not calculate attribution; it should preserve source-authored fields and
   expose a front-office contract.
4. `lotus-workbench` must not reconstruct allocation, selection, interaction, totals, residual,
   status, or reason codes from raw rows.
5. If API changes are required, downstream consumers must be updated in the same RFC. Backward
   compatibility is not a goal when a cleaner contract is materially better, but every known
   consumer must move with the change.
6. If platform automation gaps are discovered, fix repeatable concerns in `lotus-platform`, not as
   one-off `lotus-performance` workarounds.
7. The final implementation must clearly separate supported attribution capability from advanced
   future/non-goal models.

## 5.1 Cross-Repository Scope

| Repository | Role | Same-RFC obligation |
| --- | --- | --- |
| `lotus-performance` | Attribution calculation authority and product owner | Engine, API, evidence, docs, domain-product declarations, telemetry, tests, endpoint certification, and wiki source. |
| `lotus-core` | Source-data authority | Change only if attribution cannot be truthful from current source contracts; add source fields/tests/docs if required. |
| `lotus-gateway` | Experience API and Workbench contract boundary | Preserve or expose any changed attribution fields, statuses, reason codes, and degraded states; update tests and OpenAPI if required. |
| `lotus-workbench` | Front-office attribution surface | Render the correct attribution story, warnings, residual status, and degraded states through gateway/BFF only. |
| `lotus-platform` | Governance, CI, data mesh, automation, wiki publication, and standards | Add or improve scaffolding/validators when gaps are repeatable across Lotus apps. |
| `lotus-report` | Potential report consumer | Update only if report templates or report data contracts consume attribution directly. Record no-change evidence otherwise. |
| `lotus-risk`, `lotus-advise`, `lotus-manage`, `lotus-ai` | Potential adjacent consumers | Search and update only if direct contract dependencies exist. Avoid wrong-layer ownership. |

Consumer search is mandatory before any API change. Required searches include endpoint paths,
response field names, attribution model names, gateway services, Workbench panels, report templates,
OpenAPI snapshots, and supported-features material.

## 5.2 Enterprise-Grade Delivery Standard

The implementation must leave `lotus-performance` closer to a product a bank could buy:

1. deterministic formula tests prove Brinson, linking, residual, and edge behavior;
2. API contracts are explicit, source-owned, and complete;
3. OpenAPI/Swagger includes high-quality summaries, descriptions, request examples, response
   examples, and error examples for every changed endpoint;
4. response fields are bounded, explainable, and safe;
5. error handling is intentional and tested;
6. logs, metrics, supportability, lineage, and diagnostics help operations without leaking client,
   tenant, portfolio, account, benchmark, trace, correlation, request, response, or security data
   into unsafe labels;
7. attribution is governed as a data product where promoted;
8. CI, dependency, security, and platform governance checks stay green;
9. docs/wiki/README/supported-features are implementation-backed and not aspirational.

The implementation standard is deliberately stricter than "feature complete":

1. no known security vulnerability may be ignored; every finding must be fixed or formally tracked
   with severity, owner, and treatment;
2. every changed API must satisfy the Lotus API certification pattern and Swagger quality bar;
3. every downstream product surface must consume `lotus-performance` or `lotus-gateway` source
   truth, not local reconstruction;
4. every data-product claim must be backed by declarations, telemetry, SLO/access/evidence posture,
   and mesh certification evidence where required;
5. every demo, wiki, README, and supported-feature claim must be implementation-backed after the
   RFC is complete;
6. final closure requires mainline truth: merged to `main`, validated, wiki-published where needed,
   and free of unclassified unmerged governance branches.

## 5.3 No-Second-Wave Rule

This RFC must fully realize the approved attribution business value. There must be no follow-up RFC
or second wave for essential realization work discovered during implementation.

Same-RFC obligations:

1. if source contracts are insufficient, update the relevant upstream repository in the same RFC;
2. if API contracts change, update every downstream consumer in the same RFC;
3. if platform automation or scaffolding is missing a repeatable concern, improve
   `lotus-platform` in the same RFC;
4. if documentation, wiki, supported-features, or context truth changes, update the durable truth in
   the same RFC;
5. if a claimed capability cannot be implemented to the required standard, mark it unsupported or
   explicitly bounded before closure instead of leaving it as implied future work.

Backward compatibility is not required when a cleaner API is materially better for private banking,
enterprise readiness, and long-term maintainability. The cost of that choice is mandatory same-RFC
consumer migration and proof.

## 6. Supported-Features Ledger

This ledger controls what may be promoted into README/wiki/sales/demo material.

| Feature | Current state | Target state after RFC | Promotion rule |
| --- | --- | --- | --- |
| Stateless attribution | Supported | Supported with stronger status, residual, reason-code, and evidence contract if approved | Promote after deterministic unit and integration proof. |
| Stateful attribution from `lotus-core` | Supported | Supported with explicit source alignment and degraded-state evidence | Promote after live canonical proof and upstream/downstream validation. |
| Brinson-Fachler attribution | Supported | Certified with deterministic formulas and residual policy | Promote after source-doc QA cases pass. |
| Brinson-Hood-Beebower attribution | Supported | Certified or explicitly bounded | Promote after tests prove formula and docs explain boundary. |
| Allocation/selection/interaction | Supported | Supported with optional display policy if implemented | Promote after API/downstream/docs align. |
| Multi-period linking | Supported through top-down scaling | Supported with explicit linking status and support-safe evidence | Promote after multi-period tests and docs explain raw-versus-linked effects. |
| Currency-aware attribution | Supported under `currency_mode="BOTH"` | Supported with clearer currency status, mismatch behavior, and docs | Promote after multi-currency tests and live evidence. |
| Hierarchical group attribution | Supported | Supported with explicit cross-level reconciliation and status evidence | Promote after hierarchy tests and Workbench proof. |
| Off-benchmark and benchmark-only segment handling | Implicit through outer alignment | Supported with reason codes and support evidence | Promote after deterministic tests prove no segment is dropped and residual remains governed. |
| Unclassified bucket handling | Partially supported as `unknown` | Supported with Lotus vocabulary, reason code, and docs | Promote after source and response semantics are explicit. |
| Material residual classification | Not first-class | Supported with thresholds and reason codes | Promote after tests cover warning and material paths. |
| Attribution data product | Not fully promoted | Governed `AttributionAnalytics:v1` data product if approved | Promote after declaration, telemetry, SLO/access/evidence, and mesh gates pass. |
| Fixed-income factor attribution | Not supported | Explicitly unsupported unless same-RFC implementation is approved and delivered | Do not promote without source fields, engine, tests, docs, and live evidence. |
| Derivative exposure attribution | Not supported beyond standard Brinson/currency buckets | Explicitly unsupported or bounded warning behavior | Promote only warning/boundary language unless implemented and proven. |
| Composite attribution | Not supported as a portfolio-composite engine | Explicitly out of RFC-048 unless source ownership and RFC scope are approved | Do not promote as implemented. |
| Implementation-backed documentation/wiki | Partial | Detailed, audience-aware, actual-code-grounded docs | Promote after final implementation proof and wiki publication. |
| Post-completion LinkedIn draft | Not started | Drafted only after implementation, based only on actual outcomes | Keep truthful and non-aspirational. |

Every feature delivered through this RFC must appear in this ledger, relevant supported-features
material, and final closure evidence. Future-state ideas must remain clearly marked as unsupported
until implemented and proven.

## 7. Slice Plan

Slice execution rule: do not move to the next slice until the current slice is implemented,
validated, reviewed, committed, and in a solid state. For this draft, implementation must not begin
until the RFC is approved.

Every implementation slice must:

1. start from current `main` or a branch explicitly reconciled with current `main`;
2. run stranded-truth reconciliation before implementation start, before final closure, and before
   moving to another RFC;
3. use small, meaningful commits and keep PR evidence truthful;
4. monitor GitHub Feature Lane and PR Merge Gate checks while continuing useful non-conflicting
   work;
5. fix CI failures promptly and avoid allowing branch quality to drift;
6. leave touched code, tests, docs, and contracts cleaner than they were at slice start.

### Slice 0 - Source Map, Baseline, and Stranded-Truth Reconciliation

Purpose: establish an implementation-safe baseline.

Scope:

1. rerun stranded-truth reconciliation for `lotus-performance`;
2. classify unmerged governance branches as `must-merge`, `cherry-pick`, `superseded`, `delete`, or
   `active`;
3. preserve source-doc review mapping in this RFC or a source-map companion if needed;
4. verify current attribution code/tests/docs/OpenAPI/downstream evidence from `main`;
5. record current behavior as implemented, gap, or explicit non-goal;
6. create non-committed `output/` evidence directories for analysis artifacts.

Acceptance criteria:

1. no unclassified unmerged governance branch exists;
2. source documents are reviewed and mapped to implementation decisions;
3. current attribution implementation and downstream consumer surfaces are inventoried;
4. no implementation changes are made before approval.

Validation:

1. `git fetch origin --prune`
2. `git branch -r --no-merged origin/main`
3. targeted code/doc searches for attribution paths and consumers.

### Slice 1 - Platform Automation and Scaffolding Improvement

Purpose: fix repeatable platform gaps at platform level.

Implementation evidence: `docs/RFCs/RFC-048-platform-automation-slice1.md`. Slice 1 strengthened
`lotus-platform` analytics data-product onboarding through `sgajbi/lotus-platform#323`, merged as
`df085a5194235cae15968a54471f51e4400e49cc`.

Scope:

1. assess whether platform automation already scaffolds API certification, Swagger quality,
   observability, health/readiness, structured logging, error handling, test scaffolding, CI
   defaults, documentation scaffolding, governance hooks, data-product onboarding, and live-evidence
   patterns for analytics APIs;
2. improve `lotus-platform` automation if a gap is repeatable and should not be solved locally in
   every app;
3. ensure any new data-product declaration, trust telemetry, SLO/access/evidence, or OpenAPI quality
   requirement is validator-backed where practical;
4. identify which cross-cutting concerns should be scaffolded by default for future FastAPI
   analytics services, including API certification, Swagger examples, health/liveness/readiness,
   correlation and trace propagation, structured errors, bounded metrics, secure defaults,
   docs/wiki seed material, governance hooks, and test scaffolds;
5. improve app scaffolding automation so future Lotus apps start with stronger enterprise and
   data-product governance from day one;
6. during later slices, continue moving newly discovered repeatable concerns into platform
   automation instead of leaving them as local one-off fixes;
7. record a deliberate no-platform-change decision if current automation already covers the need.

Acceptance criteria:

1. platform gaps are fixed in `lotus-platform` or explicitly ruled out with evidence;
2. future Lotus apps benefit from any scaffolding improvement;
3. platform tests/validators pass for any platform change;
4. the RFC records whether scaffolding was improved, why, and which future-app concerns it now
   covers.

Validation:

1. relevant `lotus-platform` unit/automation tests;
2. platform domain-product and mesh validators when touched;
3. GitHub Feature Lane and PR Merge Gate for platform changes.

### Slice 2 - Cleanup and Structure

Purpose: simplify before expanding attribution.

Implementation evidence: `docs/RFCs/RFC-048-cleanup-and-structure-slice2.md`. Slice 2 added an
attribution documentation map, implementation-backed wiki page, wiki navigation links, supported
feature boundary wording, and corrected stale downstream Gateway issue status.

Scope:

1. remove dead, duplicate, or misleading attribution docs/code/tests discovered in Slice 0;
2. clarify module boundaries if attribution status/residual/evidence logic would otherwise bloat
   `engine/attribution.py`;
3. reduce documentation sprawl by moving long-lived operator/product material to wiki source and
   keeping RFC methodology depth in repo docs;
4. keep README concise and command-accurate;
5. avoid duplicate documentation across repo docs and wiki;
6. identify repo-local source material that should remain RFC/methodology detail versus wiki
   product/operator material;
7. record explicit no-wiki-change if wiki source is not changed.

Acceptance criteria:

1. attribution code remains easier to read after cleanup;
2. docs are layered: RFC for plan, methodology docs for formulas, guide for API use, wiki for
   audience-facing product/operations material;
3. public docs contract tests are updated only for truthful current-state material;
4. wiki source is usable, non-duplicative, and ready for publication when post-RFC truth changes.

Validation:

1. `ruff check` and `ruff format --check` for touched Python files;
2. docs contract tests if docs/wiki/README change;
3. no unrelated cosmetic churn.

### Slice 3 - Attribution Methodology and Engine Contract

Purpose: implement the core methodology changes approved by this RFC.

Implementation evidence: `docs/RFCs/RFC-048-attribution-methodology-engine-contract-slice3.md`.
Slice 3 added controlled attribution period status, reason codes, residual materiality,
support-safe alignment evidence, and lineage evidence while preserving existing Brinson,
hierarchy, currency, and linking formulas.

Scope:

1. add controlled attribution status and reason-code model;
2. implement residual materiality thresholds and classification;
3. expose off-benchmark, benchmark-only, unclassified, missing benchmark, missing benchmark return,
   currency mismatch, linking issue, and material residual semantics;
4. decide and implement or explicitly reject interaction folding;
5. add support-safe daily attribution evidence if approved;
6. preserve raw, linked, and reconciled effect semantics without forcing downstream recomputation;
7. maintain exact existing supported formulas unless a source-doc review proves a correction is
   required.

Acceptance criteria:

1. deterministic formula tests pass for Brinson-Fachler and BHB;
2. edge tests cover portfolio-only, benchmark-only, missing classification, negative weights,
   zero capital, missing benchmark return, residual threshold, and currency mismatch;
3. response fields are bounded, described, and safe;
4. lineage captures enough evidence for operations without exposing unsafe payloads in metrics or
   logs.

Validation:

1. `python -m pytest tests/unit/engine/test_attribution.py tests/unit/models/test_attribution_models.py -q`
2. focused service and endpoint tests for changed behavior;
3. lineage artifact assertions where evidence changes.

### Slice 4 - Stateful Source Alignment and Upstream Contract Review

Purpose: ensure attribution is source-backed, not locally guessed.

Scope:

1. test current `lotus-core` sourced portfolio, position, benchmark, classification, and FX inputs
   against the attribution source-doc requirements;
2. identify whether source contracts need additional fields for benchmark version, classification
   version, calendar, off-benchmark policy, derivative/short flags, fee/tax/income handling, or FX
   conversion evidence;
3. change `lotus-core` only when source truth cannot be represented correctly in current contracts;
4. update `lotus-performance` stateful normalization only after source ownership is clear;
5. preserve `lotus-core` as source-data authority and `lotus-performance` as methodology authority.

Acceptance criteria:

1. source requirements are either satisfied by current contracts or implemented upstream;
2. no attribution conclusion is moved into `lotus-core`;
3. stateful attribution tests prove source alignment and degraded/error behavior.

Validation:

1. focused `lotus-core` tests if upstream contracts change;
2. `lotus-performance` stateful attribution unit/integration tests;
3. source-contract docs and API snapshots if touched.

### Slice 5 - API Contract, OpenAPI, and Error Handling Certification

Purpose: make the attribution API integration-grade.

Scope:

1. update request/response models for approved status/evidence fields;
2. define all error paths intentionally, including invalid request, missing source, invalid
   benchmark, missing FX, unsupported dimension, unavailable evidence, async failure, and internal
   calculation failure;
3. certify Swagger/OpenAPI summaries, descriptions, tags, request examples, response examples, and
   error examples;
4. keep field names aligned to Lotus private-banking vocabulary and platform no-alias governance;
5. update API vocabulary inventory.

Acceptance criteria:

1. every new or changed field has a description, type, and example;
2. every changed endpoint has clear what/when/how guidance;
3. examples show realistic private-banking attribution use;
4. errors are tested and documented;
5. OpenAPI and vocabulary gates pass.

Validation:

1. `python scripts/openapi_quality_gate.py`
2. `python scripts/api_vocabulary_inventory.py --validate-only`
3. focused integration tests for success and failure contracts.

### Slice 6 - Data Product and Platform Hardening

Purpose: strengthen attribution as a true Lotus data product.

Scope:

1. assess whether attribution should be promoted, updated, or explicitly bounded as a governed
   Lotus performance data product;
2. add or update `contracts/domain-data-products/lotus-performance-products.v1.json`;
3. add or update attribution trust telemetry under `contracts/trust-telemetry/`;
4. add SLO/access/evidence posture where platform governance requires it;
5. update platform contract mirrors or generated catalog evidence when required;
6. improve API posture, metadata quality, discoverability, contract clarity, and documentation
   quality;
7. review dependency hygiene, security posture, CI coverage, Docker posture, and migration posture;
8. close gaps needed to make `lotus-performance` enterprise-grade, production-ready, and
   bank-buyable.

Acceptance criteria:

1. data-product declaration is truthful and validator-backed;
2. trust telemetry does not overclaim unsupported runtime maturity;
3. mesh certification passes where applicable;
4. security and dependency checks are green or formally tracked with treatment;
5. attribution ownership, upstream dependencies, downstream consumers, freshness, lineage,
   evidence, SLO, access, and escalation posture are clear enough for platform catalog and
   operating review.

Validation:

1. `make domain-product-validate`
2. relevant trust telemetry and platform mesh validators;
3. `make check` or narrower repo-native checks as risk requires;
4. GitHub Feature Lane and PR Merge Gate.

### Slice 7 - Downstream Contract Realization

Purpose: ensure changed attribution value is actually available to consumers.

Scope:

1. search `lotus-gateway`, `lotus-workbench`, `lotus-report`, and adjacent repos for attribution
   dependencies;
2. update `lotus-gateway` contracts/services/tests for new fields, statuses, reason codes, row
   coverage, degraded states, and supportability;
3. update `lotus-workbench` panels to display or preserve source-owned attribution status,
   residual, warnings, and evidence without local recomputation;
4. update reports only if report data contracts or templates consume attribution directly;
5. prove gateway-first consumption and no direct Workbench-to-service coupling.

Acceptance criteria:

1. every downstream consumer compiles/tests against the changed contract;
2. Workbench uses gateway/BFF only;
3. UI feature claims are backed by implemented backend fields;
4. no downstream consumer reconstructs attribution totals, residual, or statuses locally.

Validation:

1. focused gateway tests;
2. focused Workbench tests and browser validation if UI changes;
3. platform front-office canonical runtime proof when product surfaces change.

### Slice 8 - QA Regression Pack

Purpose: convert the supplied QA pack into meaningful Lotus tests.

Scope:

1. add deterministic Brinson-Fachler reconciliation tests using source-doc examples adapted to
   Lotus naming;
2. add interaction treatment tests if implemented;
3. add active contribution and reconciliation tests where response supports it;
4. add portfolio-only, benchmark-only, unclassified, short/negative-weight, zero-capital, missing
   benchmark return, calendar mismatch, currency mismatch, material residual, and multi-period
   linking cases;
5. add stateful source-input tests for canonical private-banking portfolios;
6. add downstream contract tests where API shape changes.

Acceptance criteria:

1. tests validate real behavior and risks, not shallow field presence;
2. numeric tests use appropriate precision and avoid rounded display values for engine validation;
3. tests cover warnings/reason codes/statuses as first-class outputs;
4. failures are actionable.

Validation:

1. targeted unit, integration, and model tests;
2. docs contract tests for examples if examples change;
3. repo-native `make check` before PR-ready handoff.

### Slice 9 - Documentation Productization

Purpose: make attribution documentation implementation-backed and useful.

Scope:

1. upgrade attribution methodology docs to the Lotus methodology v3 standard;
2. update `docs/guides/attribution.md` with actual request/response/error behavior;
3. update `docs/technical/attribution-endpoint-certification.md` with current certification
   evidence and caveats;
4. update API reference, README, and supported-features material only with implementation-backed
   claims;
5. add or update wiki pages for business users, developers, operations, sales/pre-sales, and demo
   preparation;
6. include diagrams where they improve understanding of source flow, benchmark alignment,
   attribution calculation, downstream consumption, and support triage.

Acceptance criteria:

1. docs are not generic imports from the source pack;
2. every described field/feature exists in code and tests;
3. unsupported advanced methods are explicitly marked as unsupported/bounded;
4. wiki source is published after merge when changed.

Validation:

1. docs contract tests;
2. `Sync-RepoWikis.ps1 -CheckOnly -Repository lotus-performance`;
3. post-merge wiki publication when approved implementation is merged.

### Slice 10 - Implementation Proof

Purpose: prove the implementation end to end against this RFC.

Scope:

1. run live API tests on the front-office canonical stack;
2. capture request/response evidence under non-committed `output/`;
3. verify every returned figure, status, reason code, residual, supportability state, lineage
   artifact, and downstream panel state critically;
4. include stateful attribution for `PB_SG_GLOBAL_BAL_001` unless a more appropriate governed
   attribution fixture is approved;
5. include gateway and Workbench proof when downstream surfaces change;
6. record issues found and fix them before moving forward.

Acceptance criteria:

1. live evidence demonstrates the actual implemented behavior;
2. proof is reviewed for correctness, not only captured;
3. known gaps are either fixed or formally scoped as unsupported with approval;
4. the live stack is left in the agreed state after testing;
5. the RFC records what was proven, what failed during proof, what was fixed, and why the remaining
   result is gold-standard rather than merely passing.

Validation:

1. repo-native service tests;
2. canonical front-office runtime validation if UI/gateway surfaces change;
3. saved evidence manifest in RFC closure notes.

### Slice 11 - Second-Last Hardening and Review

Purpose: run the final engineering quality pass before closure.

Scope:

1. perform a proper code review of all changed repositories;
2. remove dead code, duplicated logic, misleading docs, brittle tests, and unnecessary abstractions;
3. verify API certification pattern compliance;
4. verify platform governance and data mesh standards;
5. ensure all APIs touched by the RFC are properly certified;
6. ensure Swagger is complete and high quality:
   - endpoints are grouped correctly;
   - every endpoint has clear what/when/how guidance;
   - full request and response examples are present;
   - every attribute has description, type, and example value;
   - error responses are documented with realistic examples;
7. ensure all errors are complete, correct, and tested;
8. review logs, metrics, lineage, diagnostics, and security posture;
9. ensure security vulnerabilities are fixed or formally tracked with treatment;
10. make final quality improvements before closure.

Acceptance criteria:

1. no known avoidable production-readiness issue remains;
2. all required checks are green;
3. residual risks are documented with owner and treatment;
4. implementation is simpler and clearer than before.

Validation:

1. `make check`
2. `make ci` where risk and time justify PR-grade local proof;
3. GitHub PR checks;
4. targeted security/dependency checks.

### Slice 12 - Final Closure

Purpose: close the RFC as mainline truth.

Scope:

1. update RFC status and gold-pass assessment;
2. update README, wiki source, docs, supported-features, API references, and endpoint
   certification;
3. update `REPOSITORY-ENGINEERING-CONTEXT.md` if attribution responsibilities or commands changed;
4. consciously review whether AGENTS/context/skills/local skill copies need improvement;
5. run stranded-truth reconciliation before closure;
6. confirm branch hygiene, PR merge, CI green, and local `main == origin/main`;
7. publish wiki after merge if wiki source changed;
8. run context/skill/wiki synchronization commands when applicable;
9. record a deliberate no-change decision when skills, guidance, documentation, or agent context do
   not need updates.

Acceptance criteria:

1. implementation and durable truth are merged to `main`;
2. wiki truth is published if changed;
3. no required truth remains stranded on unmerged branches;
4. local repo is clean and aligned with remote main;
5. final status is truthful and evidence-backed;
6. supported-features material reflects every delivered feature as implementation-backed product
   truth;
7. closure includes an explicit review of what should be added, removed, tightened, or clarified in
   AGENTS, context, skills, local skill copies, docs, wiki, and supported features.

Validation:

1. `git fetch origin --prune`
2. `git branch -r --no-merged origin/main`
3. relevant docs/context tests;
4. wiki check and publish commands where applicable;
5. `powershell -ExecutionPolicy Bypass -File ..\lotus-platform\automation\Sync-AgentOperatingContract.ps1 -AllRepoRoots -IncludeDeployedTarget` when operating contract truth changed;
6. `python ..\lotus-platform\automation\validate_engineering_context_system.py` when context changed;
7. `python ..\lotus-platform\automation\validate_lotus_skill_alignment.py` when skills or routing changed;
8. `powershell -ExecutionPolicy Bypass -File ..\lotus-platform\automation\Sync-RepoWikis.ps1 -CheckOnly -Repository lotus-performance`;
9. post-merge `powershell -ExecutionPolicy Bypass -File ..\lotus-platform\automation\Sync-RepoWikis.ps1 -Publish -Repository lotus-performance` when wiki changed.

### Slice 13 - Post-Completion Communication

Purpose: draft truthful public-facing communication after implementation is complete.

Scope:

1. review existing Lotus LinkedIn draft style and the local LinkedIn thought-leadership skill;
2. inspect recent drafts such as `LI-2026-05-10-013-contribution-needs-method-evidence.md`,
   `LI-2026-05-10-012-evidence-travels-with-workflow.md`, and
   `LI-2026-05-10-001-performance-evidence-product-contract.md` for voice and repetition;
3. draft a LinkedIn post only after implementation is complete;
4. base the post only on what was actually implemented and proven;
5. avoid aspirational claims, client-sensitive details, employer-specific inferences, and
   unsupported banking/product promises;
6. keep the post separate from formal product docs and record it in the thought-leadership ledger
   if a draft file is created.

Acceptance criteria:

1. post draft is truthful, grounded, and implementation-backed;
2. no unsupported advanced attribution claims are made;
3. the post references engineering/product outcomes without exposing sensitive implementation or
   client data;
4. the draft follows the Lotus LinkedIn voice guide and remains personal-brand content, not direct
   Lotus marketing.

## 8. Data Mesh Requirements

Attribution must be treated as a data product candidate throughout this RFC. Promotion to
`supported` data-product status is allowed only when implementation evidence satisfies the required
mesh standards. If promotion is not justified, the RFC must record the explicit boundary and avoid
data-product marketing claims.

The implementation must satisfy or explicitly classify:

1. explicit producer declaration with stable product id, owner, description, schema posture,
   upstream dependencies, consumer expectations, and lifecycle state;
2. governed vocabulary references for time period, source freshness, trust metadata, lineage, and
   evidence class;
3. trust telemetry snapshot or runtime telemetry collection path that does not overclaim maturity;
4. SLO posture for freshness, completeness, reconciliation, data quality, lineage, and escalation;
5. access posture for allowed consumers, use cases, denial behavior, audit owner, and gateway-only
   publication where required;
6. evidence posture for customer-safe, operator-only, and internal artifacts;
7. platform mesh certification gates passing after source and platform mirrors are updated;
8. consumer dependency graph clarity across `lotus-gateway`, `lotus-workbench`, `lotus-report`, and
   adjacent services;
9. API discoverability and metadata quality suitable for self-serve data-product discovery;
10. safe public/customer evidence-pack posture that excludes restricted telemetry, raw holdings,
   entitlement details, trace identifiers, and unsafe source artifacts.

## 9. API and Compatibility Posture

Backward compatibility is not a hard requirement for this RFC if a cleaner private-banking
attribution contract is materially better. However:

1. every known downstream consumer must be updated in the same RFC;
2. old fields or endpoints must not be left as undocumented aliases unless explicitly governed;
3. API vocabulary inventory must be updated;
4. OpenAPI snapshots/examples must reflect the final contract;
5. Workbench and Gateway must use source-owned attribution fields rather than recomputing or
   inferring them.

## 10. Risks and Controls

| Risk | Impact | Control |
| --- | --- | --- |
| Generic source docs lead to over-scoped implementation | Bloated or misleading product claims | Supported-features ledger, explicit non-goals, slice approval discipline. |
| API changes break Gateway or Workbench | Front-office regression | Same-RFC downstream update and canonical runtime proof. |
| Residual/status fields become noisy | Poor operations trust | Controlled thresholds, reason-code taxonomy, deterministic tests, docs. |
| Metrics leak high-cardinality or sensitive values | Observability/security defect | Bounded labels only; tests against forbidden label categories. |
| Fixed-income/derivative/composite language is overclaimed | Misleading client/demo material | Explicit unsupported boundaries unless implemented and proven. |
| Source alignment requires upstream fields | Delay or wrong-layer workaround | Slice 4 source-authority review and upstream changes only when justified. |
| Docs drift from implementation | Bad client/support material | Docs contract tests, wiki source governance, implementation-backed closure. |

## 11. Evidence Expectations

Final implementation evidence must include:

1. source-doc-to-implementation mapping;
2. deterministic unit tests for formulas and edge cases;
3. integration tests for sync and async attribution APIs;
4. stateful source-integration proof;
5. OpenAPI and vocabulary validation;
6. data-product and mesh validation if promoted;
7. gateway and Workbench tests if contracts change;
8. live front-office canonical proof where product surfaces change;
9. docs/wiki validation and publication evidence;
10. CI check links and final branch hygiene proof;
11. security/dependency posture evidence or formal risk treatment;
12. API certification and Swagger quality evidence;
13. data-product certification, telemetry, SLO/access/evidence posture, and mesh-gate proof where
    promoted;
14. a final gold-pass assessment section in this RFC stating:
    - what was truly completed;
    - what quality improvements were made;
    - what debt was removed;
    - what was proven through testing and evidence;
    - whether the implementation genuinely reached the expected standard.

## 12. Approval Gate

Implementation may start only after the RFC is approved.

Approval should confirm:

1. the scope is correct;
2. supported and unsupported attribution capabilities are clearly bounded;
3. API compatibility posture is acceptable;
4. upstream/downstream same-RFC obligations are acceptable;
5. data-product promotion scope is acceptable;
6. documentation and wiki expectations are acceptable;
7. slice sequencing is acceptable.

Until then, this RFC remains planning material only.
