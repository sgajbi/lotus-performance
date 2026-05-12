# RFC 049 - Composite Performance Industry Methodology Alignment and Evidence Contract

Status: Draft - approval required before implementation

Owner repository: `lotus-performance`

Primary domain: performance analytics

Source package: `C:\Users\Sandeep\Downloads\composite-performance-docs.zip\composite-performance-docs`

Created: 2026-05-12

Implementation posture: planning only. No implementation slice may start until this RFC is
approved by the operator. After approval, work must proceed strictly slice by slice. A slice is
complete only when it is implemented, validated, reviewed, documented, committed, and in a solid
state.

Related RFCs:

1. RFC-022 - historical composite and sleeve proposal, now outdated and superseded for execution
   planning by this RFC.
2. RFC-046 - portfolio-level TWR industry alignment, which explicitly kept composite, group, and
   sleeve TWR out of scope.
3. RFC-047 - contribution Carino methodology alignment.
4. RFC-048 - attribution methodology alignment and evidence contract.

## 0. Critical Review Before Implementation

The supplied composite performance documentation is materially useful, but it is generic industry
material. It must not be copied into Lotus as generic methodology text. The implementation plan must
convert the useful ideas into Lotus-owned, implementation-backed behavior and documentation using
Lotus private-banking vocabulary, current `lotus-performance` contracts, and the Lotus data-product
governance model.

The current `lotus-performance` implementation is strong at single-portfolio analytics:

1. `POST /performance/twr` supports stateless and stateful portfolio-level TWR with benchmark
   evidence, daily calculation evidence, linkability status, source-quality evidence, lineage, and
   async result retrieval.
2. `POST /performance/mwr` supports portfolio-level MWR methods with solver diagnostics,
   cash-flow schedule evidence, and current single reporting-currency boundaries.
3. `POST /performance/contribution` supports portfolio-level contribution with Carino smoothing,
   source-economics evidence, stateful input, supportability, and downstream realization.
4. `POST /performance/attribution` supports portfolio-level Brinson attribution with source
   alignment evidence, residual materiality, controlled statuses, downstream realization, and data
   product promotion.
5. `POST /integration/returns/series` serves portfolio/benchmark return-series bundles for
   downstream consumers.
6. Inspection, lineage, runtime, observability, OpenAPI enrichment, API vocabulary, and domain data
   product contracts already exist.

The current implementation is not yet a composite performance product:

1. there is no `/performance/composites/*` or `/composites/*` runtime API;
2. there is no `engine/composite.py` or equivalent domain engine;
3. there is no composite definition, membership, eligibility, inclusion, exclusion, dispersion, or
   restatement model;
4. current supported-features material intentionally says composite, group, and sleeve TWR are not
   supported;
5. `CompositePerformanceAnalytics:v1` is not a declared domain data product;
6. no Gateway or Workbench consumer contract exists for composite performance;
7. the historical RFC-022 document is too broad, too stateless, and not sufficiently aligned with
   current Lotus governance, data mesh, source authority, API certification, live proof, or
   documentation-as-product standards.

This RFC therefore does not assume RFC-022 is implementation-ready. It replaces RFC-022 as the
execution guide for composite performance. RFC-022 remains useful historical context, but this RFC
is the approval artifact for any new composite implementation.

### 0.1 Stranded Truth Baseline

Pre-draft reconciliation was run from clean `lotus-performance` `main` on 2026-05-12:

```powershell
git fetch origin --prune
git branch -r --no-merged origin/main
```

Result: no unmerged remote `lotus-performance` branches were listed. No durable RFC, docs, wiki,
contract, context, OpenAPI, supported-features, or workflow truth was stranded before drafting this
RFC.

## 1. Executive Summary

This RFC proposes a gold-standard composite performance capability for `lotus-performance` based on
the supplied composite performance documentation. The target outcome is a private-banking composite
performance product that can answer:

1. how a strategy performed across all eligible portfolios;
2. which portfolios were included or excluded in each period;
3. why each member was included or excluded;
4. which member return, asset, return view, currency, and weighting basis was used;
5. whether the result is valid, provisional, not available, blocked, restated, or unsupported;
6. whether benchmark, dispersion, assets, fees, contribution, and attribution evidence are available;
7. whether the result is safe for advisor use, client review, operations review, or not available.

The implementation must focus first on governed composite TWR, because the source documentation and
industry practice make clear that composite performance starts with effective-dated member
portfolio TWRs, objective eligibility, and asset-weighted linking. Composite MWR, composite
contribution, composite attribution, carve-outs, model portfolios, wrap programs, private-market
composites, and portability metadata must be treated as explicitly gated scopes. They can be
implemented in this RFC only when source ownership, implementation value, tests, downstream
realization, and live evidence are all satisfied within the same RFC. There must be no follow-up
RFC required for the approved business value.

The RFC must make Lotus stronger, not merely larger:

1. `lotus-performance` should become a true composite performance data product where promoted;
2. source authority must be clear across `lotus-core`, `lotus-performance`, `lotus-gateway`, and
   `lotus-workbench`;
3. API contracts must be bank-grade, fully documented, certified, and downstream-realized;
4. implementation-backed docs and wiki material must be useful to developers, business users,
   operations, sales, pre-sales, and demo preparation;
5. CI, security, observability, data mesh, and platform compliance must improve as part of the work;
6. supported-features material must remain truthful and never promote unimplemented composite
   capability.

## 2. Business Outcome

Private bankers, portfolio managers, CIO-office users, investment operations, performance
operations, sales, pre-sales, and client-service teams need strategy-level performance analytics
that are not vulnerable to cherry-picking, survivorship bias, current-membership bias, or
unsupported methodology claims.

This RFC should allow Lotus to support a bank-buyable composite performance story:

1. define a strategy composite objectively;
2. resolve eligible member portfolios using effective-dated membership and policy;
3. calculate composite return from validated member portfolio returns and assets;
4. preserve every included and excluded member with reason codes;
5. separate gross, net actual, model-fee net, and unsupported return views;
6. prevent silent dropping of eligible members with missing or invalid data;
7. treat no-member periods as no performance, not zero return;
8. expose composite assets, member counts, benchmark return, active return, and dispersion where
   source data and policy support them;
9. support restatement and reproducibility evidence;
10. publish implementation-backed documentation suitable for client demos and operations support.

The target language is private banking and investment governance language, not generic aggregation
language. Use terms such as composite definition, investment mandate, eligible member,
effective-dated membership, discretion status, restriction status, minimum asset threshold,
significant cash-flow policy, return view, composite currency, weighting assets, dispersion,
restatement, source authority, and supportability evidence.

## 3. Source Documentation Review

| Source file | Adopt into Lotus? | RFC treatment |
| --- | --- | --- |
| `01-composite-methodology.md` | Yes | Adopt composite definition, strategy versus client group versus model portfolio boundaries, effective-dated membership, no-member period handling, survivorship-bias prevention, and methodology declarations. |
| `02-composite-return-calculation.md` | Yes | Adopt asset-weighted member-return calculation, geometric linking, annualization controls, invalid member-return handling, zero/negative weighting asset controls, numerical tolerance, and output fields. |
| `03-membership-eligibility-and-governance.md` | Yes | Adopt eligibility dimensions, inclusion/exclusion timing, grace periods, minimum asset thresholds, discretion/restriction status, significant cash-flow policy, manual override governance, and membership audit output. |
| `04-assets-fees-dispersion-and-benchmarks.md` | Yes | Adopt composite assets, gross/net separation, actual/model-fee boundaries, fee-drag posture, tax boundary, dispersion policy, benchmark alignment, blended benchmark requirements, benchmark change control, and active return. |
| `05-carveouts-models-wraps-and-special-structures.md` | Partially | Adopt boundaries and vocabulary. Do not promote carve-outs, model portfolios, wrap-fee programs, pooled funds, private-market composites, portability, tax-aware composites, or long/short special handling unless same-RFC source authority and evidence prove them. |
| `06-group-composite-contribution-and-attribution.md` | Partially | Adopt group-versus-composite distinction and the requirement that contribution/attribution reconcile to composite return when implemented. Composite contribution and composite attribution are gated unless implemented and proven within this RFC. |
| `07-data-classification-and-inputs.md` | Yes | Adopt required data categories, composite definition input, membership input, return input, asset input, flow/fee/benchmark/discretion/classification input, data quality statuses, lineage, snapshotting, and validation checks. |
| `08-implementation-design.md` | Yes | Adopt domain objects, calculation pipeline, status model, reason-code model, auditability, caching/restatement posture, and observability metrics, translated into Lotus API and engine architecture. |
| `09-edge-cases-and-controls.md` | Yes | Adopt no-member, single-member, missing return, invalid return, zero/negative/near-zero assets, large flows, transition portfolios, terminated portfolios, inactive gaps, duplicate membership, multiple-composite membership, missing FX, mixed currencies, mixed return views, benchmark missing, restatement, outlier, calendar, and rounding controls. |
| `10-qa-regression-pack.md` | Yes | Convert into deterministic unit, property, integration, API, downstream, live stack, and docs regression tests. |
| `11-production-support-agent-playbook.md` | Yes | Convert into Lotus operations/support playbook grounded in actual API fields, reason codes, lineage, evidence packs, and safe support-agent behavior. |
| `composite-performance-playbook-all-in-one.md` | Reference only | Use as consolidated review material only. Do not commit generic all-in-one wording as Lotus product documentation. |

## 4. Current Implementation Assessment

### 4.1 Current Strengths

| Area | Current Lotus evidence | Assessment |
| --- | --- | --- |
| Portfolio TWR | `app/api/endpoints/performance.py`, `app/services/twr_service.py`, `engine/compute.py`, `engine/ror.py` | Strong member-return authority candidate. Composite engine should consume validated member portfolio returns rather than reimplementing raw return math unnecessarily. |
| Stateful source integration | `app/services/stateful_performance_input_service.py`, `app/services/core_integration_service.py` | Good upstream source pattern. Composite membership and policy data will still require source-authority decisions. |
| Contribution and attribution engines | `engine/contribution.py`, `engine/attribution.py` | Strong portfolio-level engines. Composite contribution/attribution must not be bolted on until composite return and membership governance are stable. |
| Runtime and lineage | execution registry, async result store, lineage services | Good foundation for long-running composite jobs and reproducible evidence. |
| Inspection and supportability | `app/api/endpoints/inspections.py`, `app/services/inspection/*` | Strong pattern for support-safe diagnostics. Composite inspection may need a new check family instead of overloading TWR inspection. |
| Data product governance | `contracts/domain-data-products/lotus-performance-products.v1.json`, trust telemetry contracts | Good mesh baseline. Composite performance needs its own product declaration and telemetry if promoted. |
| OpenAPI and vocabulary governance | `app/openapi_enrichment.py`, `docs/standards/api-vocabulary/lotus-performance-api-vocabulary.v1.json` | Good certification baseline. New composite APIs must satisfy the same quality bar. |
| Documentation productization | `wiki/Supported-Features.md`, `wiki/Time-Weighted-Return.md`, `wiki/Contribution-Analytics.md`, `wiki/Attribution-Analytics.md` | Strong implementation-backed pattern. Composite docs must remain unsupported until implemented and proven. |

### 4.2 Current Gaps

| Gap | Severity | Evidence | Required direction |
| --- | --- | --- | --- |
| No composite runtime API | P0 | No composite endpoint or router exists | Add a governed composite API only after source and domain model are approved. |
| No composite domain model | P0 | No composite definition, member, eligibility, or result model exists | Add explicit Lotus models for composite definition, effective-dated membership, policy, member evidence, result status, and restatement. |
| No composite engine | P0 | No `engine/composite.py` or equivalent exists | Add a small, testable domain engine that composes existing portfolio analytics where appropriate. |
| No membership source authority | P0 | Current source contracts do not declare composite membership authority | Decide whether `lotus-core`, `lotus-manage`, or another source owns composite definitions and memberships; update upstream contracts if needed. |
| No composite data product | P0 | Domain product contract does not include `CompositePerformanceAnalytics:v1` | Add producer declaration, trust telemetry, SLO/access/evidence posture, and mesh certification when implemented. |
| RFC-022 is outdated | P1 | RFC-022 proposes broad `/composites/*` wrappers without modern governance | Supersede with this RFC; preserve useful concepts but remove unsafe implementation assumptions. |
| Composite docs intentionally say unsupported | P1 | `wiki/Supported-Features.md` and TWR docs say composite/group/sleeve TWR are unsupported | Update only after implementation proof; until then keep unsupported boundary truthful. |
| No downstream consumer contract | P1 | Gateway and Workbench do not expose composite performance | Same-RFC downstream updates are required if composite APIs are added. |
| No composite QA pack | P1 | No tests for member weighting, eligibility, no-member periods, dispersion, restatement, or edge controls | Add deterministic and live proof before promotion. |
| Carve-outs/sleeves are not source-backed | P2 | No sleeve cash allocation or parent-account exclusion model exists | Keep out of supported scope unless same-RFC source data and tests justify implementation. |
| Composite contribution/attribution are not implemented | P2 | Current contribution/attribution are portfolio-level | Gate until composite return/member evidence exists and reconciliation can be proven. |

## 5. Architecture Direction

Target architecture:

```text
lotus-core / approved source authority
  -> composite definition and effective-dated membership source contract
  -> member portfolio TWR source contract from lotus-performance
  -> composite eligibility and policy resolver
  -> composite member evidence builder
  -> asset-weighted period return engine
  -> linking, benchmark, asset, dispersion, and status engine
  -> composite response, lineage, trust telemetry, and support evidence
  -> lotus-gateway composite performance contract
  -> lotus-workbench composite product surface and demo evidence
```

Architecture rules:

1. `lotus-performance` is the composite performance calculation authority once the product is
   approved.
2. `lotus-performance` should reuse validated portfolio TWR and return-series contracts where
   possible instead of duplicating portfolio return formulas.
3. Source authority for composite definitions, effective-dated membership, discretion status,
   restriction status, minimum asset thresholds, fee status, benchmark assignment, benchmark
   version, classification, and restatement approval must be explicit before implementation.
4. `lotus-gateway` must not calculate composite returns; it must preserve source-owned fields,
   statuses, warnings, and reason codes.
5. `lotus-workbench` must not reconstruct composite math from member rows; it must display
   `lotus-performance` authored outputs through gateway-first integration.
6. No backward compatibility is required if a cleaner contract is materially better, but every known
   downstream consumer must be updated in the same RFC.
7. Composite TWR is the first-class implementation target. Composite MWR, contribution,
   attribution, carve-outs, sleeves, model portfolios, wraps, private markets, and portability are
   approved only if this RFC's implementation slices prove source readiness and business value.
8. The final product must avoid claims of GIPS compliance or verification. Lotus may implement
   GIPS-aware evidence and methodology controls, but formal compliance claims require separate
   business/legal approval.

## 5.1 Proposed API Direction

The final API shape must be decided during implementation after source-authority review, but the
preferred Lotus posture is:

1. publish composite performance under `lotus-performance` API ownership, for example
   `POST /performance/composites/twr` and `GET /performance/composites/twr/results/{calculation_id}`;
2. keep portfolio TWR at `POST /performance/twr` unchanged unless composite implementation exposes a
   shared internal model;
3. avoid the older broad RFC-022 `/composites/*` family unless endpoint certification proves that
   route shape is the right current Lotus contract;
4. include `composite_id`, `composite_name`, `composite_currency`, `strategy_code`, `return_view`,
   `calculation_frequency`, `as_of_date`, `periods`, `membership_policy`, `benchmark_policy`,
   `source_authority`, and `lineage` metadata;
5. include member audit evidence for included, excluded, blocked, provisional, and invalid members;
6. expose `status`, `reason_codes`, `warnings`, `supportability`, and `data_quality_status` as
   controlled enums with OpenAPI examples;
7. separate customer-consumable evidence from operator-only evidence.

## 5.2 Cross-Repository Scope

| Repository | Role | Same-RFC obligation |
| --- | --- | --- |
| `lotus-performance` | Composite performance calculation authority | Engine, API, models, evidence, docs, OpenAPI, API vocabulary, tests, trust telemetry, data-product declaration, supported-features, and wiki source. |
| `lotus-core` | Candidate source authority for portfolio state, portfolio returns, classifications, benchmark assignment, discretion/restriction fields, and possibly composite membership | Change only if source truth cannot be represented today. Do not fake missing source authority inside `lotus-performance`. |
| `lotus-manage` | Candidate source authority for strategy/mandate governance, approval workflow, and composite policy lifecycle | Change only if composite definitions belong to management governance rather than source accounting. |
| `lotus-gateway` | Experience API boundary | Preserve or expose composite APIs, statuses, reason codes, evidence, degraded states, OpenAPI, and tests. |
| `lotus-workbench` | Front-office product surface | Render composite performance, member audit, benchmark, dispersion, warnings, degraded states, and demo evidence through Gateway/BFF only. |
| `lotus-platform` | Governance, data mesh, automation, scaffolding, wiki publication, and standards | Add reusable scaffolding/validators when gaps are repeatable across Lotus apps. |
| `lotus-report` | Potential report and proof-pack consumer | Update if composite outputs feed client reports, presentations, or archive packs. Record no-change evidence otherwise. |
| `lotus-risk`, `lotus-advise`, `lotus-ai` | Adjacent consumers | Search and update only when direct contract dependencies exist. Avoid wrong-layer ownership. |

Consumer search is mandatory before any API change. Required searches include endpoint paths,
response field names, data-product ids, supported-feature entries, Gateway clients, Workbench
panels, report templates, OpenAPI snapshots, API vocabulary inventories, and wiki material.

## 5.3 Data Product Direction

Composite performance should be promoted as a data product only after implementation proof supports
the claim.

Candidate product:

```text
CompositePerformanceAnalytics:v1
```

Candidate scope:

1. scope level: composite;
2. product family: analytics output;
3. temporal basis: `as_of_date` plus effective-dated membership periods;
4. source dependencies: portfolio returns, member assets, composite membership, benchmark
   assignment, FX source, fee policy, discretion/restriction state, and restatement metadata;
5. supported routes: final composite performance routes only after implementation;
6. trust metadata: product name/version, generated time, as-of date, correlation id, request
   fingerprint, source services, upstream request fingerprints, composite definition version,
   membership snapshot id, data-quality status, coverage status, reconciliation status, and
   restatement status;
7. evidence classes: customer-consumable summary, customer lineage summary, restricted member
   audit, operator diagnostics, internal-only source artifacts.

Promotion rule:

1. before implementation proof, `CompositePerformanceAnalytics:v1` is proposed only;
2. after API, tests, live proof, data-product contract, trust telemetry, Gateway/Workbench
   realization, docs, supported-features, and wiki publication are complete, it may be promoted to
   supported;
3. unsupported advanced scopes must remain explicit.

## 6. Supported-Features Ledger

| Feature | Proposed status | Promotion rule | Current claim before implementation |
| --- | --- | --- | --- |
| Composite TWR from validated member portfolio returns | Proposed | Promote only after engine/API/tests/live proof and downstream realization are complete. | Not supported. |
| Effective-dated composite membership and eligibility evidence | Proposed | Promote only after source authority, API response, reason-code tests, and docs are complete. | Not supported. |
| Included/excluded member audit with reason codes | Proposed | Promote only after every reason family is tested and documented. | Not supported. |
| Composite assets and member counts | Proposed | Promote only after weighting assets and currency conversion policies are tested. | Not supported. |
| Benchmark return and active return for composites | Proposed | Promote only after benchmark source/version policy, missing benchmark behavior, and tests are complete. | Not supported. |
| Dispersion | Proposed | Promote only after minimum-member policy, calculation method, one-member behavior, and OpenAPI docs are complete. | Not supported. |
| Restatement and reproducibility evidence | Proposed | Promote only after snapshot, lineage, result id, and restatement behavior are implemented and tested. | Not supported. |
| Composite contribution | Gated | Promote only if implemented in this RFC with reconciliation to composite return and downstream proof. | Not supported. |
| Composite attribution | Gated | Promote only if implemented in this RFC with benchmark alignment, residual proof, and downstream proof. | Not supported. |
| Composite MWR | Gated | Promote only if implemented with separate investor-capital-timing disclosure and controls. | Not supported. |
| Carve-outs and sleeves | Gated | Promote only if sleeve cash allocation, parent exclusion, source authority, and tests are implemented. | Not supported. |
| Model, wrap, pooled fund, private-market, portability, tax-aware, leveraged, and long/short special structures | Gated or unsupported | Promote only with explicit source authority, business approval, and implementation proof. | Not supported. |

Supported-features material must not be updated from unsupported to supported until the promotion
rule is satisfied. Target-state wording belongs in this RFC until implementation-backed proof exists.

## 7. Slice Plan

### Slice 0 - Source Map, Baseline Assessment, and RFC Approval Readiness

Purpose: turn the generic source pack into an implementation-ready Lotus plan without coding.

Scope:

1. map every source document to Lotus adoption, partial adoption, or rejection;
2. confirm current `lotus-performance` implementation reality from code, tests, contracts,
   OpenAPI, wiki, and README;
3. reconcile RFC-022 against the new source pack and current Lotus standards;
4. identify upstream and downstream repositories that may be impacted;
5. record stranded-truth reconciliation;
6. keep all composite capability claims unsupported until implementation proof exists;
7. submit this RFC for approval.

Acceptance criteria:

1. this RFC is detailed enough for a strong implementer to execute with minimal ambiguity;
2. source-doc ideas are translated into Lotus vocabulary and product outcomes;
3. current implementation gaps are explicit;
4. no code implementation starts before approval.

Validation:

1. docs/RFC review;
2. `git fetch origin --prune`;
3. `git branch -r --no-merged origin/main`;
4. targeted docs tests if index/status files change.

### Slice 1 - Platform Automation and Scaffolding Improvement

Purpose: improve repeatable platform scaffolding rather than solving cross-cutting concerns only in
`lotus-performance`.

Scope:

1. identify platform automation gaps that should scaffold composite-quality API surfaces by
   default;
2. improve `lotus-platform` automation where repeatable gaps are found;
3. evaluate scaffolding for API certification, Swagger quality, OpenAPI examples, vocabulary
   inventory, health/readiness, structured logging, error handling, supportability metrics, trust
   telemetry, data-product onboarding, docs/wiki scaffolding, test templates, CI defaults, and
   governance hooks;
4. add or update platform templates only when they benefit future Lotus applications;
5. record a deliberate no-change decision if current platform automation is sufficient.

Acceptance criteria:

1. repeatable platform gaps are fixed at platform level, not locally duplicated;
2. future apps start with a stronger baseline for composite-quality analytics APIs;
3. platform changes are tested and merged before dependent local closure claims.

Validation:

1. platform automation tests relevant to changed scripts/templates;
2. `python ..\lotus-platform\automation\validate_engineering_context_system.py` if context changes;
3. `python ..\lotus-platform\automation\validate_lotus_skill_alignment.py` if skill guidance changes.

### Slice 2 - Cleanup, Structure, and Historical RFC Reconciliation

Purpose: remove misleading composite sprawl before adding new implementation.

Scope:

1. reconcile RFC-022 with RFC-049:
   - mark RFC-022 as superseded for execution planning;
   - preserve useful historical rationale;
   - stop using RFC-022 as implementation-ready guidance;
2. remove or rewrite stale docs that imply composite support where none exists;
3. keep current unsupported claims in README/wiki/supported-features until implementation is real;
4. improve repository structure only where it materially helps composite implementation;
5. identify and remove dead code if encountered;
6. avoid duplicate documentation across RFC, docs, README, and wiki.

Acceptance criteria:

1. no public or wiki material implies implemented composite support before implementation;
2. RFC-022 and RFC-049 have a clear relationship;
3. future documentation layers are planned without sprawl.

Validation:

1. docs contract tests;
2. grep/search proof for misleading composite support claims;
3. `Sync-RepoWikis.ps1 -CheckOnly -Repository lotus-performance` when wiki source changes.

### Slice 3 - Composite Domain Model, Source Authority, and Membership Governance

Purpose: establish the core business object model before calculation.

Scope:

1. define Lotus composite domain vocabulary:
   - composite definition;
   - composite version;
   - strategy code;
   - effective-dated membership;
   - member eligibility;
   - inclusion and exclusion decision;
   - discretion status;
   - restriction status;
   - minimum asset threshold;
   - significant cash-flow policy;
   - grace period;
   - return view;
   - composite currency;
   - restatement status;
2. decide and implement source authority for composite definition and membership:
   - `lotus-core` if it owns source/reference truth;
   - `lotus-manage` if it owns mandate/governance workflow truth;
   - `lotus-performance` only for calculation-local request-scoped definitions when explicitly
     approved;
3. implement source contracts and validation if upstream change is required;
4. add `lotus-performance` request/response models for composite definitions and member audit;
5. add controlled status and reason-code taxonomy.

Acceptance criteria:

1. membership is effective-dated and reproducible;
2. current membership is never used to rewrite historical composite results;
3. terminated members remain in historical periods when eligible;
4. manual overrides require reason and approval evidence;
5. no eligible member with missing required data is silently excluded;
6. source ownership is explicit and tested.

Validation:

1. model tests;
2. source contract tests in impacted upstream repo;
3. API schema tests;
4. source-authority documentation review.

### Slice 4 - Core Composite TWR Calculation Engine

Purpose: implement the minimum bank-grade composite calculation capability.

Scope:

1. add a composite engine module with small, testable functions;
2. calculate period composite return by asset-weighting validated member portfolio returns;
3. link period returns geometrically;
4. support daily and monthly calculation only where source member returns exist;
5. preserve member weights, member returns, assets, return view, currency, and statuses;
6. implement no-member, one-member, zero-asset, negative-asset, missing-return, invalid-return,
   mixed-currency, mixed-return-view, calendar-mismatch, inactive-gap, duplicate-membership, and
   restatement controls;
7. expose valid, warning, provisional, blocked, not-available, invalid, and unsupported status
   semantics.

Acceptance criteria:

1. no-member periods return no performance, not zero return;
2. eligible members with missing or invalid required data block or degrade according to policy and
   never disappear silently;
3. weights are reproducible and sum to one when result status is valid;
4. linked returns are mathematically correct and do not link through inactive gaps unless policy
   explicitly permits it;
5. deterministic examples from the source QA pack are converted into Lotus tests.

Validation:

1. unit tests for engine formulas and edge cases;
2. property tests for weight and no-member invariants;
3. integration tests through API service layer once API is available;
4. numerical tolerance documentation.

### Slice 5 - Composite API Contract, OpenAPI, Error Handling, and Async Runtime

Purpose: publish the composite capability through a certified API contract.

Scope:

1. add final composite endpoint routes after approval of route shape;
2. support sync and async execution using existing execution registry patterns;
3. implement result retrieval paths;
4. include full request, response, and error models;
5. document every attribute with type, description, example value, and controlled enums;
6. include realistic examples for valid, no-member, blocked missing member return, missing
   benchmark, mixed return view, and restated result;
7. add 400/404/409/422/500 behavior where appropriate;
8. update API vocabulary inventory and no-alias governance.

Acceptance criteria:

1. Swagger is high quality and grouped correctly;
2. every endpoint has clear what/when/how guidance;
3. all error behavior is intentional and tested;
4. no stale or duplicate composite endpoint exists;
5. async accepted responses include execution, polling, and result paths.

Validation:

1. OpenAPI contract tests;
2. endpoint integration tests;
3. `python scripts/api_vocabulary_inventory.py`;
4. no-alias/vocabulary checks;
5. `make check`.

### Slice 6 - Data Product and Platform Hardening

Purpose: promote composite performance only when it satisfies data mesh and platform standards.

Scope:

1. add or update `CompositePerformanceAnalytics:v1` domain product declaration;
2. add trust telemetry contract and runtime/static telemetry evidence as appropriate;
3. define SLO, access, evidence, lifecycle, and data-quality posture;
4. update platform catalog/source manifest where required;
5. certify gateway-only publication where customer/product surfaces are involved;
6. add bounded metrics for composite calculation status and reason-code families without sensitive
   labels;
7. review dependency, CI, security, observability, logging, health, readiness, and runtime posture;
8. formally track or fix security vulnerabilities.

Acceptance criteria:

1. data product declaration is truthful and implementation-backed;
2. mesh certification passes or records an approved limited posture;
3. metrics and logs are bounded, useful, and non-sensitive;
4. no product claim exceeds implementation proof.

Validation:

1. data-product contract tests;
2. trust telemetry validation;
3. mesh certification gate where applicable;
4. security/dependency checks;
5. observability tests.

### Slice 7 - Benchmark, Assets, Fees, Dispersion, and Restatement Evidence

Purpose: move beyond a single return number into a supportable composite product.

Scope:

1. implement composite assets and member counts;
2. implement benchmark return and active return where benchmark source/version is available;
3. implement dispersion with explicit minimum-member policy;
4. implement fee-view separation:
   - gross;
   - net actual;
   - model-fee net only when policy/source data supports it;
5. document unsupported fee/tax treatment clearly;
6. implement restatement metadata and snapshot evidence;
7. preserve reproducibility through lineage and source fingerprints.

Acceptance criteria:

1. gross and net results are never mixed in one result;
2. composite assets are computed in composite currency with source evidence;
3. dispersion is not emitted as meaningful for one-member or below-threshold periods;
4. benchmark missing does not invalidate composite return but blocks active return and attribution;
5. restatements never silently overwrite published results.

Validation:

1. deterministic unit tests;
2. integration tests;
3. lineage/reproducibility tests;
4. OpenAPI examples for each status family.

### Slice 8 - Gated Advanced Composite Analytics Decision

Purpose: consciously decide which advanced scopes are implemented in this RFC and which remain
unsupported.

Scope:

1. evaluate composite contribution;
2. evaluate composite attribution;
3. evaluate composite MWR;
4. evaluate carve-outs/sleeves;
5. evaluate model portfolios, wrap programs, pooled funds, private-market composites, portability,
   tax-aware composites, multi-currency special handling, leveraged, and long/short composites;
6. implement only the advanced scopes that are required for approved business value and can be
   completed, tested, documented, downstream-realized, and proven within this RFC;
7. explicitly keep all other advanced scopes unsupported in docs/wiki/supported-features.

Acceptance criteria:

1. no advanced scope is implemented superficially;
2. no advanced scope is promoted without source authority and proof;
3. contribution/attribution, if implemented, reconcile to composite return and benchmark active
   return;
4. unsupported boundaries are explicit and demo-safe.

Validation:

1. source-authority review;
2. tests for each implemented advanced scope;
3. docs/search proof that unsupported scopes are not overclaimed.

### Slice 9 - Downstream and Upstream Integration Realization

Purpose: make every required cross-repo change in the same RFC.

Scope:

1. update upstream systems if source authority fields are required;
2. update `lotus-gateway` to expose composite performance through the correct experience API;
3. update `lotus-workbench` to consume composite outputs through Gateway/BFF only;
4. update `lotus-report` if composite outputs become report or proof-pack inputs;
5. update `lotus-risk`, `lotus-advise`, `lotus-manage`, or `lotus-ai` only when direct contract
   dependencies exist;
6. update OpenAPI, tests, docs, and supported-features in each impacted repo;
7. do not preserve backward compatibility when a cleaner contract is materially better, but migrate
   every known consumer.

Acceptance criteria:

1. all known consumers compile/test against the final contract;
2. Gateway and Workbench do not recompute composite figures;
3. Workbench degraded states use source-authored statuses and reason codes;
4. no downstream repo relies on stale endpoints or fields.

Validation:

1. targeted tests in every impacted repo;
2. Gateway integration tests;
3. Workbench unit and live validation tests;
4. search proof for old endpoint/field usage;
5. PR/CI evidence for each impacted repo.

### Slice 10 - QA Regression Pack

Purpose: convert the source pack into durable Lotus tests.

Scope:

1. basic asset-weighted return;
2. member contribution to composite return;
3. monthly linking;
4. no eligible portfolios;
5. one eligible portfolio;
6. terminated portfolio remains historically;
7. survivorship-bias prevention;
8. grace period;
9. minimum asset threshold;
10. eligible member missing return;
11. invalid member assets;
12. negative assets;
13. mixed return view;
14. missing FX;
15. benchmark active return;
16. benchmark missing;
17. dispersion;
18. one-member dispersion;
19. inactive gap;
20. duplicate membership;
21. restated member return;
22. restated member assets;
23. property tests for no-member, missing eligible member, and weight invariants;
24. API tests for status/reason/error behavior.

Acceptance criteria:

1. tests validate math and governance;
2. tests are not shallow count inflation;
3. every adopted edge case is mapped to a test or explicit unsupported decision;
4. regression pack is documented and maintainable.

Validation:

1. targeted unit/integration/e2e tests;
2. `make check`;
3. coverage remains at the governed repository threshold.

### Slice 11 - Documentation Productization and Wiki

Purpose: make composite documentation implementation-backed and useful across audiences.

Scope:

1. add Lotus methodology v3 composite docs with formulas, variables, deterministic steps,
   validation/failure behavior, and worked examples;
2. add API guide material only after endpoint implementation;
3. add endpoint certification docs;
4. update README only with concise current capability and command truth;
5. update repo-local wiki with:
   - feature coverage;
   - upstream and downstream integrations;
   - business flows;
   - non-functional capabilities;
   - architecture and operational behavior;
   - diagrams where useful;
   - supported and unsupported boundaries;
6. avoid duplicating detailed RFC mechanics in wiki;
7. update supported-features only with implementation-backed claims;
8. publish wiki after merge if changed.

Acceptance criteria:

1. docs are not generic imports from the source pack;
2. every described feature exists in code and tests;
3. docs support developers, business users, operations, sales, pre-sales, and demos;
4. diagrams explain source flow, calculation flow, downstream flow, and support triage where useful;
5. unsupported advanced scopes remain explicit.

Validation:

1. docs contract tests;
2. `Sync-RepoWikis.ps1 -CheckOnly -Repository lotus-performance`;
3. post-merge `Sync-RepoWikis.ps1 -Publish -Repository lotus-performance` when wiki changed.

### Slice 12 - Implementation Proof

Purpose: prove the implementation end to end against this RFC.

Scope:

1. run live API tests on the front-office canonical stack;
2. capture request/response evidence under non-committed `output/`;
3. verify every returned figure, status, reason code, member inclusion/exclusion, weight, return,
   asset value, benchmark value, dispersion value, supportability state, lineage artifact, and
   downstream panel state critically;
4. include canonical portfolio/composite fixtures approved by the operator;
5. include Gateway and Workbench proof if downstream surfaces change;
6. identify issues, fix them, and rerun proof until the result is genuinely production-grade;
7. leave the live stack in the agreed state after testing.

Acceptance criteria:

1. live evidence demonstrates actual implemented behavior;
2. proof is reviewed for correctness, not only captured;
3. every issue found during proof is fixed or explicitly classified with owner, severity, and
   treatment;
4. evidence can support client demo preparation without exposing sensitive data.

Validation:

1. repo-native service tests;
2. canonical front-office runtime validation when UI/gateway surfaces change;
3. saved evidence manifest in closure notes;
4. API, Gateway, and Workbench direct probes as applicable.

### Slice 13 - Second-Last Hardening and Review

Purpose: run the final engineering quality pass before closure.

Scope:

1. perform a proper code review of all changed repositories;
2. remove dead code, duplicated logic, misleading docs, brittle tests, and unnecessary abstractions;
3. verify API certification pattern compliance;
4. verify platform governance and enterprise data mesh standards;
5. ensure all APIs touched by the RFC are certified;
6. ensure Swagger is complete and high quality:
   - grouped correctly;
   - clear what/when/how guidance for each endpoint;
   - full request and response examples;
   - every attribute has description, type, and example value;
   - every error response has realistic examples;
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

1. `make check`;
2. `make ci` where risk and time justify PR-grade local proof;
3. GitHub PR checks;
4. targeted security/dependency checks;
5. docs/wiki/context validation.

### Slice 14 - Final Closure

Purpose: close the RFC as mainline truth.

Scope:

1. update RFC status and gold-pass assessment;
2. update README, wiki source, docs, supported-features, API references, and endpoint
   certification;
3. update `REPOSITORY-ENGINEERING-CONTEXT.md` if repository responsibilities or commands changed;
4. consciously review whether AGENTS, context, skills, local skill copies, docs, wiki, or supported
   features should be improved to support future work;
5. run stranded-truth reconciliation before closure;
6. confirm branch hygiene, PR merge, CI green, and local `main == origin/main`;
7. publish wiki after merge if wiki source changed;
8. run context/skill/wiki synchronization commands when applicable;
9. record a deliberate no-change decision when no guidance/context/skill change is needed.

Acceptance criteria:

1. implementation and durable truth are merged to `main`;
2. wiki truth is published if changed;
3. no required truth remains stranded on unmerged branches;
4. local repos are clean and aligned with remote main;
5. final status is truthful and evidence-backed;
6. supported-features material reflects every delivered feature as implementation-backed product
   truth.

Validation:

1. `git fetch origin --prune`;
2. `git branch -r --no-merged origin/main`;
3. relevant docs/context tests;
4. wiki check and publish commands where applicable;
5. `powershell -ExecutionPolicy Bypass -File ..\lotus-platform\automation\Sync-AgentOperatingContract.ps1 -AllRepoRoots -IncludeDeployedTarget` when operating contract truth changed;
6. `python ..\lotus-platform\automation\validate_engineering_context_system.py` when context changed;
7. `python ..\lotus-platform\automation\validate_lotus_skill_alignment.py` when skills or routing changed.

### Slice 15 - Post-Completion Communication

Purpose: draft truthful public-facing communication after implementation is complete.

Scope:

1. review the local `lotus-linkedin-thought-leadership` skill;
2. inspect recent drafts such as:
   - `LI-2026-05-10-001-performance-evidence-product-contract.md`;
   - `LI-2026-05-10-012-evidence-travels-with-workflow.md`;
   - recent contribution and attribution completion drafts;
3. draft a LinkedIn post only after implementation is complete;
4. base the post only on what was actually implemented and proven;
5. avoid aspirational claims, client-sensitive details, employer-specific inferences, unsupported
   GIPS/compliance claims, and unimplemented product promises;
6. keep the post separate from formal product docs and record it in the thought-leadership ledger if
   a draft file is created.

Acceptance criteria:

1. post draft is truthful, grounded, and implementation-backed;
2. no unsupported composite, GIPS, attribution, sleeve, or model-portfolio claims are made;
3. the draft follows the Lotus LinkedIn voice guide and remains personal-brand content, not direct
   Lotus marketing.

## 8. Data Mesh Requirements

Composite performance must be treated as a data product candidate throughout this RFC. Promotion to
supported data-product status is allowed only when implementation evidence satisfies the required
mesh standards.

The implementation must satisfy or explicitly classify:

1. explicit producer declaration with stable product id, owner, description, schema posture,
   upstream dependencies, consumer expectations, and lifecycle state;
2. governed vocabulary references for composite, member, strategy, mandate, period, source
   freshness, trust metadata, lineage, and evidence class;
3. trust telemetry snapshot or runtime telemetry collection path that does not overclaim maturity;
4. SLO posture for freshness, completeness, reconciliation, data quality, lineage, restatement, and
   escalation;
5. access posture for allowed consumers, use cases, denial behavior, audit owner, and gateway-only
   publication where required;
6. evidence posture for customer-safe, restricted customer, operator-only, and internal artifacts;
7. platform mesh certification gates passing after source and platform mirrors are updated;
8. consumer dependency graph clarity across `lotus-gateway`, `lotus-workbench`, `lotus-report`, and
   adjacent services;
9. API discoverability and metadata quality suitable for self-serve data-product discovery;
10. safe public/customer evidence-pack posture that excludes restricted telemetry, raw holdings,
   entitlement details, trace identifiers, and unsafe source artifacts.

## 9. API and Compatibility Posture

Backward compatibility is not a hard requirement for this RFC if a cleaner private-banking
composite contract is materially better. However:

1. every known downstream consumer must be updated in the same RFC;
2. old fields or endpoints must not be left as undocumented aliases unless explicitly governed;
3. API vocabulary inventory must be updated;
4. OpenAPI snapshots/examples must reflect the final contract;
5. Workbench and Gateway must use source-owned composite fields rather than recomputing or
   inferring them;
6. unsupported old RFC-022 routes must not be advertised unless implemented and certified.

## 10. Risks and Controls

| Risk | Impact | Control |
| --- | --- | --- |
| Composite capability is over-scoped | Bloated implementation or shallow product | Core composite TWR first; advanced scopes gated with explicit acceptance criteria. |
| Composite support is claimed before implementation | Misleading demo/client material | Supported-features ledger and docs tests keep unsupported boundary until proof. |
| Membership source authority is unclear | Wrong-layer governance and unreliable history | Slice 3 source-authority decision before calculation. |
| Current membership is used for historical periods | Survivorship/current-membership bias | Effective-dated membership and regression tests. |
| Eligible members with missing data are silently excluded | Performance manipulation risk | Missing eligible member blocks/degrades with reason codes. |
| Gross/net/currency views are mixed | Incorrect performance claims | Return-view and currency consistency validation. |
| No-member periods return zero | False strategy performance | No-member status returns not available, never zero. |
| API changes break Gateway or Workbench | Front-office regression | Same-RFC downstream updates and live canonical proof. |
| Metrics leak sensitive/high-cardinality labels | Security/observability defect | Bounded label tests and no-sensitive-content review. |
| GIPS wording is overclaimed | Legal/compliance risk | Use GIPS-aware controls only; no compliance/verification claim without separate approval. |
| Docs drift from implementation | Bad client/support material | Docs contract tests, wiki governance, and implementation-backed closure. |

## 11. Evidence Expectations

Final implementation evidence must include:

1. source-doc-to-implementation mapping;
2. current implementation baseline and RFC-022 supersession rationale;
3. deterministic unit tests for composite formulas and edge cases;
4. property tests for weight, no-member, missing member, and linking invariants;
5. API and integration tests for sync/async composite routes;
6. source-authority proof and upstream tests when upstream changes are required;
7. OpenAPI and vocabulary validation;
8. data-product and mesh validation if promoted;
9. Gateway and Workbench tests if contracts change;
10. live front-office canonical proof where product surfaces change;
11. docs/wiki validation and publication evidence;
12. CI check links and final branch hygiene proof;
13. security/dependency posture evidence or formal risk treatment;
14. API certification and Swagger quality evidence;
15. data-product certification, telemetry, SLO/access/evidence posture, and mesh-gate proof where
    promoted;
16. a final gold-pass assessment section in this RFC stating:
    - what was truly completed;
    - what quality improvements were made;
    - what debt was removed;
    - what was proven through testing and evidence;
    - whether the implementation genuinely reached the expected standard.

## 12. Approval Gate

Implementation may start only after the operator approves this RFC.

Approval should confirm:

1. composite TWR-first scope is correct;
2. source-authority decision process is acceptable;
3. advanced composite analytics gates are acceptable;
4. API compatibility posture is acceptable;
5. upstream/downstream same-RFC obligations are acceptable;
6. data-product promotion scope is acceptable;
7. documentation, wiki, supported-features, and LinkedIn expectations are acceptable;
8. slice sequencing is acceptable.

Until approval, this RFC remains planning material only.

## 13. Gold-Pass Assessment

Status: not started.

This section must be completed during Slice 14 after implementation, live proof, hardening review,
docs/wiki publication, supported-features promotion, CI closure, branch hygiene, and stranded-truth
reconciliation are complete.

Required closure statements:

1. what was truly completed;
2. what quality improvements were made;
3. what debt was removed;
4. what was proven through testing and evidence;
5. whether the implementation genuinely reached the expected standard;
6. which features are supported, gated, or unsupported after closure;
7. whether skills, guidance, documentation, local skill copies, agent context, or platform
   automation were improved or deliberately left unchanged.
