# RFC 049 Slice 0 - Composite Source Map and Baseline

Status: completed

Branch: `draft/rfc-049-composite-performance-alignment`

PR: `sgajbi/lotus-performance#162`

Started: 2026-05-12

## Purpose

Slice 0 anchors RFC 049 implementation against current repository truth before any platform,
calculation, persistence, API, downstream, wiki, or supported-feature implementation begins. It
records:

1. operator approval to start implementation;
2. stranded-truth reconciliation before implementation;
3. source documentation mapping;
4. current `lotus-performance` implementation evidence;
5. current gaps and target slices;
6. downstream and upstream baseline;
7. CI baseline at implementation start.

## Implementation Start Decision

The operator approved implementation on 2026-05-12 after RFC 049 was drafted, reviewed, and
tightened into an implementation-ready plan. Implementation must proceed strictly slice by slice.
No later slice may start until the active slice is implemented, validated, reviewed, documented,
committed, and in a solid state.

Slice 0 is documentation and governance only. It does not implement composite calculation,
persistence, API behavior, platform automation, or downstream integration.

## Stranded-Truth Reconciliation

Commands run:

```powershell
git fetch origin --prune
git branch -r --no-merged origin/main
```

Result:

1. `origin/main` was fetched and pruned successfully.
2. `git branch -r --no-merged origin/main` returned no additional unmerged `lotus-performance`
   remote branches.
3. Current branch `draft/rfc-049-composite-performance-alignment` remains the active RFC 049
   delivery branch and is represented by draft PR `sgajbi/lotus-performance#162`.
4. No durable RFC, docs, wiki, context, contract, migration, OpenAPI, workflow, or
   supported-features truth was found stranded on another unmerged `lotus-performance` remote
   branch before implementation started.

Classification:

| Branch | Classification | Rationale |
| --- | --- | --- |
| `draft/rfc-049-composite-performance-alignment` | active | Active implementation branch for RFC 049. Draft PR #162 exists and is the governed branch for the RFC. |

## CI Baseline At Implementation Start

PR #162 check state observed before Slice 0 edits:

1. Feature Lane / Workflow Lint: passed.
2. Feature Lane / Lint Typecheck Security: passed.
3. Feature Lane / Tests (unit): passed.
4. PR Merge Gate / Workflow Lint: passed.
5. PR Merge Gate / Lint Typecheck Security: passed.
6. PR Merge Gate / Tests (unit): passed.
7. PR Merge Gate / Tests (integration): passed.
8. PR Merge Gate / Tests (e2e): passed.
9. PR Merge Gate / Coverage Gate (Combined): passed.
10. PR Merge Gate / Validate Docker Build: passed.

Queue Auto Merge was skipped because PR #162 is still draft and implementation is not ready for
merge.

## Source Package Map

Source package reviewed:
`C:\Users\Sandeep\Downloads\composite-performance-docs.zip\composite-performance-docs`

| Source file | Lotus decision | Implementation implication |
| --- | --- | --- |
| `01-composite-methodology.md` | Adopt | Convert into Lotus methodology language for composite definition, strategy versus client group, effective-dated membership, no-member periods, survivorship-bias prevention, and methodology declarations. |
| `02-composite-return-calculation.md` | Adopt | Use for persisted member return facts, asset-weighted period returns, geometric linking, annualization controls, invalid member handling, zero/negative asset controls, and numerical tolerances. |
| `03-membership-eligibility-and-governance.md` | Adopt | Use for eligibility, grace periods, minimum asset thresholds, discretion/restriction status, significant cash-flow policy, terminated portfolio handling, manual override governance, and membership audit output. |
| `04-assets-fees-dispersion-and-benchmarks.md` | Adopt | Use for composite assets, gross/net separation, fee-view boundaries, dispersion policy, benchmark alignment, blended benchmark/versioning requirements, and active return. |
| `05-carveouts-models-wraps-and-special-structures.md` | Partially adopt | Keep boundaries and vocabulary. Do not promote carve-outs, sleeves, model portfolios, wraps, pooled funds, private-market composites, portability, tax-aware composites, or long/short special handling unless same-RFC source authority and proof justify them. |
| `06-group-composite-contribution-and-attribution.md` | Partially adopt | Adopt group-versus-composite distinction and reconciliation requirements. Composite contribution and attribution remain gated until composite return/member evidence exists and same-RFC proof supports them. |
| `07-data-classification-and-inputs.md` | Adopt | Use for required data categories, composite definition input, membership input, return input, asset input, flow/fee/benchmark/discretion/classification input, data quality statuses, lineage, snapshotting, and validation checks. |
| `08-implementation-design.md` | Adopt | Use for domain objects, calculation pipeline, status/reason-code model, auditability, caching/restatement posture, observability, operational APIs, and support evidence design. |
| `09-edge-cases-and-controls.md` | Adopt | Convert no-member, single-member, missing return, invalid return, zero/negative assets, large flows, transition portfolios, terminated portfolios, inactive gaps, duplicate membership, missing FX, mixed currencies, mixed return views, benchmark missing, restatement, outlier, calendar, and rounding controls into tests and docs. |
| `10-qa-regression-pack.md` | Adopt | Convert into deterministic unit, property, persistence, integration, API, downstream, live stack, and docs regression tests. |
| `11-production-support-agent-playbook.md` | Adopt | Convert into Lotus support runbook/wiki material grounded only in actual implemented fields, reason codes, lineage, inspector artifacts, exports, and failure behavior. |
| `composite-performance-playbook-all-in-one.md` | Reference only | Consolidated source only; generic all-in-one wording must not be copied into Lotus product docs. |
| `README.md` | Reference only | Use for package orientation only. |

## Current Lotus Implementation Evidence

| Area | Evidence | Current assessment |
| --- | --- | --- |
| Portfolio TWR | `app/api/endpoints/performance.py`, `app/services/twr_service.py`, `engine/compute.py`, `engine/ror.py` | Strong member-return authority candidate, with daily calculation evidence and supportability. Composite production must consume persisted facts rather than request-time fan-out recalculation. |
| Stateful source integration | `app/services/stateful_performance_input_service.py`, `app/services/core_integration_service.py` | Good upstream source pattern. Composite definitions, memberships, eligibility, and policy ownership still need explicit source-authority decisions. |
| Returns series | `app/api/endpoints/returns_series.py`, `app/services/returns_series_service.py` | Existing integration product for return-series consumers. It is not a composite member-return fact store or composite result store. |
| Contribution and attribution | `engine/contribution.py`, `engine/attribution.py` | Strong portfolio-level analytics. Composite contribution/attribution are gated until composite return, member evidence, benchmark alignment, and reconciliation can be proven. |
| Runtime/execution | execution registry, async result store, workers, runtime status, recovery and retention surfaces | Good foundation for long-running jobs, but RFC 049 must reassess workload isolation, queue health, retries, idempotency, stuck-run handling, and composite worker/container posture. |
| Lineage and artifacts | `app/services/lineage_service.py`, lineage endpoint tests | Good baseline for calculation lineage. Composite lineage must add definition, membership, member return fact, calculation run, result version, publication, and restatement layers. |
| Inspection | `app/api/endpoints/inspections.py`, `app/services/inspection/*` | Strong portfolio TWR inspection pattern. Composite inspector must be a separate check family and must not become a calculator. |
| OpenAPI and vocabulary | `app/openapi_enrichment.py`, `docs/standards/api-vocabulary/lotus-performance-api-vocabulary.v1.json`, OpenAPI tests | Good certification baseline. Composite product, operator, inspector, export, and runtime APIs must meet the same bar. |
| Data products and trust telemetry | `contracts/domain-data-products/lotus-performance-products.v1.json`, `contracts/trust-telemetry/` | TWR, MWR, Contribution, Attribution, ReturnsSeries, and BenchmarkExposureContext are declared. `CompositePerformanceAnalytics:v1` is not yet declared. |
| Docs and wiki | README, `docs/guides/*`, `docs/methodologies/*`, `wiki/*`, docs contract tests | Strong implementation-backed documentation pattern. Composite documentation must remain unsupported until implementation proof exists. |

## Baseline Gaps

| Gap | Severity | Evidence | Target slice |
| --- | --- | --- | --- |
| No persisted member return fact store | P0 | No `member_return_fact` model/store/contract exists. | Slice 4 |
| No composite batch/recalculation workflow | P0 | No composite calculation run, result version, publication, or restatement store exists. | Slice 4 |
| No composite runtime API | P0 | No `/performance/composites*` product, operator, inspector, export, or runtime endpoints exist. | Slice 5 |
| No composite source-authority contract | P0 | No current contract declares composite definition/membership ownership. | Slice 3 |
| No composite data product | P0 | Domain product and trust telemetry contracts do not include `CompositePerformanceAnalytics:v1`. | Slice 6 |
| No composite inspector/export model | P1 | Existing inspection is TWR-oriented and there are no composite CSV/XLSX/Markdown artifacts. | Slice 7A |
| No downstream realization | P1 | Gateway and Workbench do not expose composite performance. | Slice 9 |
| No composite QA pack | P1 | No tests for member weighting, membership, no-member periods, dispersion, restatement, batch idempotency, or export access. | Slice 10 |
| RFC-022 is outdated | P1 | RFC-022 proposes broad wrapper endpoints without current data mesh, source authority, persisted fact, worker, inspector, and enterprise-hardening requirements. | Slice 2 |
| Enterprise posture must be reassessed under composite workload | P1 | Current runtime is strong for existing analytics but not yet assessed for composite fact storage, batch workload isolation, artifact exports, and restatement lifecycle. | Slice 2A and Slice 6 |
| Carve-outs/sleeves, composite contribution, composite attribution, and composite MWR are not supported | P2 | No current engine/API/source contract implements them. | Slice 8 gated decision |

## Upstream and Downstream Baseline

| Repository | Evidence | Current classification |
| --- | --- | --- |
| `lotus-core` | Source authority for portfolio state, positions, transactions, benchmark assignment/components, classifications, FX, and valuation facts. | Candidate upstream source for data needed to generate member return facts. Change only if source truth cannot be represented today. |
| `lotus-manage` | Management/governance domain for portfolio operations and business workflow. | Candidate source for strategy/mandate/composite policy lifecycle if composite definitions belong to governance rather than source accounting. |
| `lotus-gateway` | Experience API boundary for Workbench and other consumers. | Direct downstream if composite product surfaces are added. Must preserve source-owned fields and avoid calculation. |
| `lotus-workbench` | Front-office product surface. | Direct downstream if composite panels or demo surfaces are added. Must consume through Gateway/BFF only. |
| `lotus-report` | Reporting and proof-pack candidate consumer. | Update only if composite outputs feed reports, archives, proof packs, or client presentation material in this RFC. |
| `lotus-platform` | Platform automation, data mesh, wiki publication, and governance authority. | Must receive reusable scaffolding, validators, or context updates when Slice 1 or later slices identify repeatable gaps. |
| `lotus-risk`, `lotus-advise`, `lotus-ai` | Adjacent analytics/advisory consumers. | Search and update only for direct contract dependency. Record no-change evidence otherwise. |

## Slice 0 Validation Plan

Required validation for this slice:

```powershell
git diff --check
python -m pytest tests\unit\docs\test_public_docs_contract.py -q
```

Slice 0 is complete only after this baseline artifact, RFC status, and RFC index updates pass the
validation commands and are committed/pushed to PR #162.
