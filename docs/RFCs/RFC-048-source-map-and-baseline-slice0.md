# RFC 048 Slice 0 - Attribution Source Map and Baseline

Status: completed

Branch: `feat/rfc-048-attribution-industry-alignment`

PR: `sgajbi/lotus-performance#160`

Completed: 2026-05-11

## Purpose

Slice 0 anchors RFC 048 implementation against durable evidence before any calculation, API,
downstream, platform, wiki, or supported-feature changes are made. It records:

1. source documentation that will be adopted, partially adopted, or explicitly bounded;
2. current `lotus-performance` attribution implementation evidence;
3. current downstream consumer evidence;
4. data-product and platform-governance baseline gaps;
5. stranded-truth reconciliation before implementation starts.

## Stranded-Truth Reconciliation

Commands run:

```powershell
git fetch origin --prune
git branch -r --no-merged origin/main
```

Result:

1. `origin/main` was fetched and pruned successfully.
2. `git branch -r --no-merged origin/main` returned no additional unmerged remote branches.
3. Current branch `feat/rfc-048-attribution-industry-alignment` remains the active RFC 048 delivery
   branch and is represented by draft PR `sgajbi/lotus-performance#160`.
4. No durable RFC, docs, wiki, context, contract, migration, OpenAPI, workflow, or
   supported-features truth was found stranded on another unmerged remote branch before
   implementation started.

Classification:

| Branch | Classification | Rationale |
| --- | --- | --- |
| `feat/rfc-048-attribution-industry-alignment` | active | Active implementation branch for RFC 048. Draft PR #160 exists and was clean/green at baseline. |

Baseline PR check:

1. PR #160 is open and draft.
2. Head SHA at baseline: `6066dd1a212577ec3b81bcae71a91bf8e7e99fba`.
3. Merge state: `CLEAN`.
4. Feature Lane and PR Merge Gate checks were green at baseline.

## Source Package Map

Source package reviewed:
`C:\Users\Sandeep\Downloads\attribution-industry-docs.zip\attribution-industry-docs`

| Source file | Lotus decision | Implementation implication |
| --- | --- | --- |
| `01-attribution-methodology.md` | Adopt | Convert into Lotus methodology language for active return, allocation, selection, interaction, residual, attribution versus contribution, client-safe explanation, and unsupported boundaries. |
| `02-brinson-calculation.md` | Adopt | Use to harden Brinson-Fachler and Brinson-Hood-Beebower deterministic examples, active contribution, interaction, and residual tie-out tests. |
| `03-daily-attribution-inputs.md` | Adopt | Add support-safe daily attribution evidence, input completeness, daily alignment, source-quality reason codes, and lineage/test proof where the current API does not expose enough evidence. |
| `04-multi-period-attribution-linking.md` | Adopt | Strengthen raw versus linked effect semantics, linking evidence, active-return target disclosure, and residual explanation for multi-period attribution. |
| `05-benchmark-and-classification-alignment.md` | Adopt | Make classification, benchmark calendar, portfolio-only, benchmark-only, off-benchmark, and unclassified semantics first-class in response/status evidence. |
| `06-group-hierarchy-and-sleeve-attribution.md` | Partially adopt | Current Lotus supports ordered grouping and hierarchy-style output. Sleeve, group-of-portfolios, and composite attribution remain unsupported unless same-RFC source ownership and implementation evidence prove them. |
| `07-currency-fixed-income-and-derivative-attribution.md` | Partially adopt | Keep current base/local/FX attribution support and add clear warnings/boundaries. Do not claim fixed-income factor or derivative attribution unless implemented and proven. |
| `08-edge-cases-and-controls.md` | Adopt | Add controlled reason codes and tests for missing benchmark, missing returns, unclassified exposure, off-benchmark exposure, benchmark-only exposure, residual materiality, negative/zero capital posture, and currency mismatch where supported by current inputs. |
| `09-implementation-design.md` | Adopt | Use for status model, reason-code contract, observability, audit, supportability, cache/restatement posture, and API evidence design. |
| `10-qa-regression-pack.md` | Adopt | Convert into deterministic unit, integration, OpenAPI, downstream, live canonical stack, and documentation validation matrix. |
| `11-production-support-agent-playbook.md` | Adopt | Convert into Lotus support runbook/wiki material grounded only in actual implemented fields, evidence, and failure behavior. |
| `attribution-industry-playbook-all-in-one.md` | Reference only | Consolidated source only; generic all-in-one wording must not be copied into Lotus product docs. |
| `README.md` | Reference only | Use for package orientation only. |

## Current Lotus Implementation Evidence

| Area | Evidence | Current assessment |
| --- | --- | --- |
| Engine formulas | `engine/attribution.py` | Implements Brinson-Fachler and Brinson-Hood-Beebower allocation, selection, and interaction effects, top-down linking scale, group context metrics, and currency attribution effects. |
| Alignment behavior | `engine/attribution.py` | Uses outer portfolio/benchmark alignment and fills missing values with zero, which keeps portfolio-only and benchmark-only rows in calculations but does not expose semantic reason codes yet. |
| Hierarchy/grouping | `engine/attribution.py`, `app/models/attribution_responses.py` | Ordered `group_by` output supports multi-level attribution views with authoritative totals. |
| Currency attribution | `engine/attribution.py`, `app/models/attribution_responses.py` | Emits Karnosky-Singer-style local allocation, local selection, currency allocation, and currency selection when `currency_mode="BOTH"` and currency data exists. |
| API request model | `app/models/attribution_requests.py`, `app/models/attribution_analytics_requests.py` | Supports stateless and stateful attribution, grouping, model, frequency, linking, input mode, benchmark sourcing, and currency controls. |
| API response model | `app/models/attribution_responses.py` | Emits levels, rows, totals, reconciliation, currency attribution, benchmark context, supportability, meta, diagnostics, and audit envelopes. It lacks first-class attribution status/reason-code and residual materiality policy. |
| Stateful source integration | `app/services/attribution_mode_service.py`, `app/services/stateful_attribution_input_service.py` | Resolves stateful source-normalized attribution inputs through `lotus-core` and benchmark source paths. |
| Runtime/execution | `app/services/attribution_service.py`, `app/workers/compute_executor_worker.py` | Supports sync/async attribution, execution polling, result retrieval, lineage capture, and supportability. |
| Tests | `tests/unit/engine/test_attribution.py`, `tests/integration/test_attribution_api.py`, `tests/unit/models/test_attribution_models.py` | Good baseline tests exist for formulas, API response, lineage, hierarchy, stateful input, supportability, async flow, and currency path. Source-doc edge coverage needs expansion. |
| Documentation | `docs/guides/attribution.md`, `docs/technical/attribution-endpoint-certification.md`, `wiki/Supported-Features.md`, `wiki/Integrations.md` | Current docs are useful but not yet complete methodology v3, data-product, status/reason-code, residual-materiality, or client-demo grade. |

## Baseline Gaps

| Gap | Severity | Evidence | Target slice |
| --- | --- | --- | --- |
| Attribution response lacks controlled status/reason-code contract | P0 | `AttributionResponse` has `calculation_supportability`, reconciliation, diagnostics, and audit but no attribution-specific status/reason collection. | Calculation/API implementation slices |
| Residual policy is numerical only | P0 | `Reconciliation` exposes `residual` but not threshold, materiality classification, or operator treatment. | Calculation/API implementation slices |
| Portfolio-only, benchmark-only, off-benchmark, and unclassified rows are not explicit enough | P1 | Engine outer-aligns and fills missing values with zero; missing group labels become `unknown`. | Edge-control implementation slice |
| Daily attribution evidence is lineage-only | P1 | `aligned_panel.csv` and `single_period_effects.csv` exist as lineage artifacts, but there is no support-safe daily evidence API/contract. | Evidence contract slice |
| Multi-period linking evidence is under-explained | P1 | Engine scales effects for non-`none` linking, but the response does not expose enough raw versus linked evidence for support review. | Linking/evidence slice |
| Attribution is not yet a governed mesh data product | P1 | `contracts/domain-data-products/lotus-performance-products.v1.json` declares TWR, MWR, Contribution, ReturnsSeries, and BenchmarkExposureContext, but not AttributionAnalytics. `contracts/trust-telemetry/` has no attribution telemetry snapshot. | Data-product hardening slice |
| OpenAPI quality must be recertified after contract changes | P1 | Current models have useful descriptions/examples, but new fields must satisfy API certification and Swagger quality requirements. | Hardening/review slice |
| Downstream consumers must preserve any new source-authored fields | P1 | Gateway and Workbench currently consume attribution summaries/trends and supportability; they do not yet consume attribution-specific status/reason/material residual fields because they do not exist. | Downstream contract slice |
| Advanced fixed-income factor, derivative, sleeve, and composite attribution are not supported | P2 | No current engine/API/source contract implements those models. | Documentation boundary unless same-RFC proof justifies implementation |

## Downstream Consumer Baseline

| Repository | Evidence | Current classification |
| --- | --- | --- |
| `lotus-gateway` | `src/app/clients/lotus_analytics_client.py` calls `/performance/attribution`; `src/app/services/performance_workspace_service.py` maps attribution payloads into `AttributionSummaryView`, `AttributionLevelView`, `AttributionRowView`, residuals, and trend rows; tests cover Workbench performance details and attribution trend contracts. | Direct consumer. Must update in same RFC if `lotus-performance` attribution response or status contract changes. |
| `lotus-workbench` | `src/apps/performance/components/performance-analysis-attribution-section.tsx`, `performance-attribution-trend-panel.tsx`, `performance-attribution-presentations.ts`, integration tests, and e2e smoke tests render Attribution Detail and Attribution Over Time through Gateway/BFF. | Direct product surface. Must update in same RFC if Gateway contract changes or new warnings/statuses need display. |
| `lotus-report` | Search found report review allocation/performance/contribution references but no direct `/performance/attribution` consumer. | No direct consumer at baseline. Re-check before API contract changes and record no-change evidence if unchanged. |
| `lotus-risk` | Risk owns `/analytics/risk/historical-attribution` and consumes `lotus-performance` benchmark exposure/returns context for active-risk risk attribution, not the performance attribution endpoint. | Adjacent dependency. Update only if RFC 048 changes benchmark exposure/returns contracts used by risk. |
| `lotus-core` | Source authority for portfolio, position, benchmark, classification, and FX facts. | Upstream authority. Change only if attribution cannot be truthful from current source contracts. |
| `lotus-platform` | Platform automation and data-mesh governance authority. | Must receive reusable scaffolding/validator improvements if Slice 1 proves repeatable gaps. |

## Implementation Start Decision

The operator approved implementation on 2026-05-11 after RFC 048 was drafted and tightened. Slice 0
therefore changes documentation/status only and does not implement calculation behavior. The next
slice is Slice 1: platform automation and scaffolding improvement. No calculation/API changes may
start until Slice 1 is completed, validated, reviewed, and committed.

## Slice 0 Validation Plan

Required validation for this slice:

```powershell
git diff --check
python -m pytest tests\unit\docs\test_public_docs_contract.py -q
```

Slice 0 is complete only after this source-map artifact, RFC status, and RFC index updates pass the
validation commands and are committed/pushed to PR #160.
