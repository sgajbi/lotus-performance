# RFC-046 Source Map and Gap Analysis

| Field | Value |
| --- | --- |
| RFC | RFC-046 - TWR Industry Methodology Alignment, Evidence Contract, and Data Product Hardening |
| Slice | 0 - Source Map, Gap Analysis, and Branch Reconciliation |
| Status | Complete for Slice 0 implementation start |
| Date | 2026-05-10 |
| Branch | `feat/rfc-046-twr-industry-evidence` |

## Purpose

This document is the Slice 0 control artifact for RFC-046. It prevents TWR methodology,
API-contract, data-product, documentation, wiki, platform, or downstream realization truth from
being implemented from stale assumptions or stranded side branches.

Slice 0 does not implement the TWR evidence contract. It defines the source map, dependency
boundary, current supported/gap posture, stranded-branch decision, and execution order for the
remaining slices.

## Stranded-Truth Reconciliation

Required command:

```powershell
git fetch origin --prune
git branch -r --no-merged origin/main
```

Result:

| Branch | Classification | Evidence | Decision |
| --- | --- | --- | --- |
| `origin/feat/api-contract-hardening` | `superseded` for RFC-046 | `git cherry -v origin/main origin/feat/api-contract-hardening` still lists `480553f Harden public analytics input contract`, but the durable contract outcomes are already present on the current mainline baseline: `DailyInputData` forbids extra fields, public valuation examples no longer send client-authored `day`, benchmark public input uses `perf_date`, and tests assert client-supplied `day` is rejected. A direct `origin/main..origin/feat/api-contract-hardening` diff shows the branch is stale and would delete newer governance, wiki, RFC-043/RFC-044/RFC-045, inspection, domain-product, trust-telemetry, and runtime truth if merged. | Do not merge the stale branch. Do not cherry-pick the commit because conflict resolution produced no useful delta beyond blank-line noise. Treat the branch's durable RFC-046-relevant contract truth as already superseded by current mainline. |

Validated current-mainline evidence:

1. `app/models/requests.py` - `DailyInputData` uses `model_config = ConfigDict(extra="forbid")`
   and has no caller-authored `day` field.
2. `app/models/benchmark_analytics_requests.py` - benchmark observation, price point, and return
   point public inputs use `perf_date`.
3. `tests/unit/models/test_twr_requests.py` - regression coverage rejects client-supplied `day`.
4. `docs/examples/twr_request.json`, `docs/examples/twr_request_with_benchmark.json`,
   `docs/examples/benchmark_request.json`, `docs/guides/twr.md`, and `docs/guides/benchmark.md`
   use canonical `perf_date` examples for public analytics input.

No unique durable RFC-046 truth remains stranded on `origin/feat/api-contract-hardening`.

## Industry Source Requirement Map

| Industry requirement family | RFC-046 posture | Current implementation evidence | Slice action |
| --- | --- | --- | --- |
| Daily TWR calculation independent of external flow timing | Supported baseline with evidence gap | `engine/ror.py`, `engine/compute.py`, `app/services/twr_service.py`, `docs/guides/twr.md` | Slice 4 adds explicit daily calculation evidence and tests. |
| Flow timing and denominator basis should be explainable | Supported with API evidence gap | `DailyInputData` has BOD/EOD cashflow fields; responses do not expose method/denominator evidence as first-class contract | Slice 4 and Slice 5 add evidence contract and edge-case semantics. |
| Geometric linking and linkability handling | Supported baseline with semantic gap | `engine/compute.py` and RFC-043 reset diagnostics; `docs/technical/performance-reset-scenarios.md` | Slice 5 adds semantic linkability reason codes and episode evidence. |
| Zero, negative, near-zero capital behavior | Supported with characterization gap | Existing reset/diagnostic behavior exists; policy is not fully API-visible | Slice 5 characterizes and hardens behavior before any policy change. |
| Stateful source quality and data classification | Partially supported | `app/services/valuation_points_service.py`, stateful input services, RFC-045 inspection service | Slice 6 exposes relevant source classification and degraded quality evidence. |
| FX, reporting currency, benchmark, and calendar alignment | Partially supported | `engine/ror.py`, `engine/benchmarks.py`, `app/services/twr_mode_service.py`, benchmark request models | Slice 7 strengthens evidence, tests, and docs. |
| Group, composite, and sleeve TWR | Out of scope | No first-class composite/sleeve TWR endpoint is promoted by RFC-046 | Slice 8 corrects docs or supported-feature wording if needed. Composite calculation remains out of scope. |
| Production support and operator explanation | Partially supported | RFC-045 inspection artifacts, `calculation_supportability`, bounded metrics, lineage artifacts | Slices 3, 10, 12, and 13 strengthen enterprise readiness and documentation. |
| QA regression pack | Gap | Existing unit/integration coverage is broad but not mapped to the industry QA pack | Slice 11 maps adopted cases to tests or explicit exclusions. |
| Documentation as product | Gap | Existing TWR guide and methodology docs exist, but final RFC-046 docs must be Lotus-specific and implementation-backed | Slice 10 produces final docs/wiki material after implementation truth exists. |

## Source Authority And Dependency Map

| Capability or dependency | Owner | RFC-046 requirement | Required action |
| --- | --- | --- | --- |
| Portfolio valuations, cashflow aggregates, transaction/source facts | `lotus-core` | Required for stateful TWR source truth | Change upstream only if Slice 6 proves missing source evidence, classification, FX, benchmark, or lineage behavior blocks RFC-046 realization. |
| TWR calculation, response semantics, reason codes, evidence contract | `lotus-performance` | Required | Implement in RFC-046 slices. |
| TWR inspection supportability | `lotus-performance` | Required as supportability companion, not calculation replacement | Preserve RFC-045 and align terminology. |
| Data product metadata, repo-native declarations, trust telemetry | `lotus-performance` plus `lotus-platform` standards | Required | Slice 3 validates and strengthens data product posture. |
| Platform automation and new-app scaffolding | `lotus-platform` | Required when repeatable gaps are found | Slice 1 moves repeatable automation/scaffold gaps to platform level. |
| Gateway product contract | `lotus-gateway` | Required if TWR contract changes affect product composition | Slice 9 updates or proves no-change. |
| Workbench product surface | `lotus-workbench` | Required if TWR contract changes affect UI realization | Slice 9 updates or proves no-change; product proof is required before UI/demo claims. |
| Report and AI evidence consumers | `lotus-report`, `lotus-ai` | Required if TWR evidence/report/AI contracts change | Slice 9 updates or proves no-change. |
| Public communication | `lotus-platform/thought-leadership/linkedin` | Post-completion only | Slice 15 drafts only implementation-backed, employer-safe content. |

## First-Wave Implementation Boundary

RFC-046 must fully realize approved portfolio TWR business value. The following are in scope when
needed:

1. `lotus-performance` API, model, engine, service, OpenAPI, docs, wiki, tests, data product, and
   CI/security hardening changes.
2. `lotus-platform` automation/scaffolding changes for repeatable cross-app gaps.
3. `lotus-core` source-contract changes required for stateful TWR correctness or evidence.
4. `lotus-gateway`, `lotus-workbench`, `lotus-report`, and `lotus-ai` changes required by contract
   or product realization.

The following remain out of scope:

1. composite TWR calculation,
2. group TWR calculation,
3. sleeve TWR calculation,
4. public communication before implementation proof.

## Slice 0 Decisions

1. `origin/feat/api-contract-hardening` is classified as `superseded` for RFC-046; do not merge it.
2. Current mainline already contains the durable public API input-hardening truth relevant to
   RFC-046.
3. RFC-046 proceeds with a correctness-first, cross-repo realization-first posture.
4. Composite calculation remains out of scope.
5. Slice 1 may start after targeted validation passes and this source map is committed.

## Slice 0 Validation

Targeted validation completed on 2026-05-10:

1. `python -m pytest tests/unit/docs -q` - `48 passed`
2. `python scripts/no_alias_contract_guard.py` - passed
3. `python -m pytest tests/unit/models/test_twr_requests.py -q` - `22 passed`
4. `python -m pytest tests/integration/test_performance_api.py -q` - `37 passed`, with one existing
   `HTTP_422_UNPROCESSABLE_ENTITY` deprecation warning in
   `app/services/stateful_benchmark_input_service.py`

Full PR-grade validation remains part of later slices and GitHub PR Merge Gate.
