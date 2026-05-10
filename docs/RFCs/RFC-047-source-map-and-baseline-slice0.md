# RFC 047 Slice 0 - Source Map, Branch Hygiene, and Baseline Assessment

Status: Complete

Date: 2026-05-10

Branch: `docs/rfc-contribution-carino-alignment`

PR: `sgajbi/lotus-performance#157`

Head commit at assessment start: `585178bc3ee8651d78bc3cafdf76e21afcbe0bbf`

## Purpose

This artifact records the implementation-safe baseline for RFC 047 before methodology or contract
code changes. It maps the supplied contribution and Carino documentation to current
`lotus-performance` implementation truth, classifies integration impact, and defines the concrete
work that later slices must prove.

## Branch And Stranded-Truth Reconciliation

Commands run:

```powershell
git fetch origin --prune
git branch -r --no-merged origin/main
```

Result:

| Branch | Classification | Rationale |
| --- | --- | --- |
| `origin/docs/rfc-contribution-carino-alignment` | `active` | Current RFC 047 branch and PR. It contains the approved RFC planning truth and this slice evidence. |

No other unmerged remote branch was reported for `lotus-performance`, so there is no additional
durable RFC, docs, wiki, context, contract, migration, OpenAPI, supported-features, or CI truth to
merge or cherry-pick before starting implementation.

## Source Documentation Map

The source package was reviewed from:

`C:\Users\Sandeep\Downloads\contribution-carino-docs.zip`

For local review only, the archive was extracted under ignored output:

`output/rfc-047-source-docs/contribution-carino-docs/`

| Source document | Lotus adoption decision | Implementation implication |
| --- | --- | --- |
| `README.md` | Adopt principles only | Production minimum requires raw contribution, Carino smoothing, residual evidence, QA coverage, support-safe audit output, and explicit income/fee/tax/FX classification. |
| `01-contribution-methodology.md` | Adopt as Lotus methodology vocabulary | Keep the distinction between component return, raw contribution, smoothed contribution, and relative attribution explicit in API and docs. |
| `02-single-period-contribution-calculation.md` | Adopt for source-economics and reconciliation | Later slices must preserve buy/sell as internal component flow, external deposit as non-performance flow, income/fee/tax treatment, FX posture, and residual policy. |
| `03-multi-period-contribution-and-linking.md` | Adopt for raw-vs-linked behavior | Response evidence must explain why raw summed contribution can differ from linked portfolio return. |
| `04-carino-smoothing-methodology.md` | Adopt as formula authority | Defines `k_t = ln(1 + r_t) / r_t`, `K = ln(1 + R) / R`, and `F_t = k_t / K`; deterministic proof must tie smoothed contribution to linked return. |
| `05-data-classification-and-inputs.md` | Adopt for upstream source assessment | Later slices must classify holdings, valuations, flows, income, fees, taxes, FX, corporate actions, derivatives, cash, and hierarchy metadata as supported, degraded, or unsupported. |
| `06-implementation-design.md` | Adopt as architecture guidance | Smoothing must not repair bad raw contribution; pipeline should expose statuses and reason codes from raw data through final output. |
| `07-edge-cases-and-controls.md` | Adopt for regression scope | Zero/near-zero denominator, negative NAV, -100% return, shorts, partial views, missing classification, multi-parent hierarchy, fees/taxes, FX, derivatives, and residual controls become test candidates. |
| `08-qa-regression-pack.md` | Adopt as test matrix | Later slices must convert high-value cases into unit, integration, contract, e2e, or live proof without shallow coverage-only tests. |
| `09-production-support-agent-playbook.md` | Adopt as Lotus support-runbook source | Support output must expose safe raw/smoothed, factor, residual, source, and status evidence without leaking restricted payloads. |
| `contribution-carino-playbook-all-in-one.md` | Reference only | Consolidated source used for review; generic wording must not be copied into Lotus docs. |

## Current Lotus Implementation Map

| Area | Current evidence | Baseline assessment |
| --- | --- | --- |
| Contribution endpoint | `app/api/endpoints/contribution.py` | Strong API baseline with stateless/stateful modes, sync/async handling, and result retrieval. |
| Request models | `app/models/contribution_requests.py`, `app/models/contribution_analytics_requests.py` | Existing controls cover hierarchy, emit options, weighting, smoothing, currency mode, stateful input, and reporting currency. |
| Response models | `app/models/contribution_responses.py` | Response exposes totals, position rows, daily series, hierarchy, supportability, diagnostics, and audit counts. It does not yet expose first-class smoothing status, factor evidence, raw-vs-smoothed contribution evidence, or residual classification. |
| Engine | `engine/contribution.py` | Computes raw contribution and Carino-style smoothed contribution inline. Current code applies an adjustment using `K_total / k_t`; RFC source methodology requires direct `k_t / K` factor proof. |
| Service orchestration | `app/services/contribution_service.py` | Adds period slicing, reset-aware average-weight shadow diagnostics, residual adjustment, supportability, lineage, async lifecycle, and audit counts. It still relies on hidden residual allocation to force period tie-out after smoothing. |
| Stateful upstream input | `app/services/stateful_contribution_input_service.py` | Resolves portfolio and position timeseries from `lotus-core`, splits cash flows by basis, supports local/base/BOTH currency posture, and preserves selected metadata. It does not yet expose a normalized source-economics ledger for income, fees, taxes, corporate actions, derivatives, and residual P&L categories. |
| Tests | `tests/unit/engine/test_contribution.py`, `tests/integration/test_contribution_api.py`, `tests/e2e/test_workflow_journeys.py` | Good current coverage for existing behavior, stateful mode, async, hierarchy, row coverage, reset-heavy tie-out, invalid Carino domain fallback, and lineage. Needs deterministic source-doc Carino factor examples, reason codes, source-economics, and raw-vs-smoothed evidence tests. |
| Domain product | `contracts/domain-data-products/lotus-performance-products.v1.json` | TWR, MWR, returns series, and benchmark exposure context are declared. `ContributionAnalytics:v1` is missing. |
| Trust telemetry | `contracts/trust-telemetry/` | TWR and returns-series telemetry exist. Contribution telemetry is missing. |
| Documentation | `docs/guides/contribution.md`, `docs/methodologies/metrics/metric-contribution-total.md`, `docs/technical/contribution-endpoint-certification.md` | Useful baseline. Needs v3 methodology depth, implementation-backed Carino factor examples, source-economics posture, support runbook, and API evidence fields after implementation. |

## Confirmed Current Strengths

1. `lotus-performance` already owns the contribution methodology boundary and exposes
   `/performance/contribution`.
2. Stateful contribution input is already integrated with `lotus-core` position timeseries.
3. Gateway and Workbench already consume contribution through the governed product path rather than
   direct UI-to-service calls.
4. Existing tests prove current contribution tie-out, hierarchy row preservation, async behavior,
   stateful input, and reset-heavy diagnostics.
5. Supportability metadata and bounded metrics are already present for contribution responses.

## Confirmed Implementation Gaps

| Gap | Severity | Evidence | Required slice |
| --- | --- | --- | --- |
| Carino factor semantics require correction/proof | P0 | Source document `04-carino-smoothing-methodology.md`; code path in `engine/contribution.py` uses residual-adjusting `K_total / k_t` logic rather than direct `k_t / K` factor proof. | Slice 3 |
| Smoothing is mixed into raw contribution calculation | P1 | `_calculate_daily_instrument_contributions` computes weights, raw contribution, Carino factors, fallback behavior, and smoothed contribution in one function. | Slice 2 / Slice 3 |
| Per-period smoothing status and reason codes are absent | P1 | Response model lacks smoothing status/factor evidence fields; invalid Carino is mostly audit/diagnostic notes. | Slice 4 |
| Raw-vs-smoothed contribution evidence is not first-class | P1 | Position and hierarchy responses expose final totals but not raw totals, smoothed totals, factor, linked return, residual type, or smoothing residual. | Slice 4 |
| Source economics are incomplete for bank-grade contribution | P1 | Stateful input currently maps market value and cash flows; no normalized source-economics ledger for income, fees, taxes, corporate actions, derivatives, FX P&L categories, and classification effective dates. | Slice 5 |
| Contribution is not a first-class mesh product | P1 | No `ContributionAnalytics:v1` in `contracts/domain-data-products/lotus-performance-products.v1.json`; no contribution trust telemetry snapshot. | Slice 6 |
| OpenAPI examples do not show post-RFC evidence contract | P1 | Current response models cannot yet carry evidence fields, so Swagger cannot show complete raw/smoothed examples. | Slice 7 |
| Downstream consumers need contract preservation work | P1 | Gateway, Workbench, Report, Manage, and AI consume contribution values or shaped contribution context. | Slice 7 / Slice 10 |

## Downstream Consumer Map

| Repository | Evidence | Impact classification |
| --- | --- | --- |
| `lotus-gateway` | `src/app/clients/lotus_analytics_client.py`, `src/app/services/performance_workspace_service.py`, `tests/unit/test_upstream_clients.py`, `tests/unit/test_performance_workspace_service.py`, `tests/integration/test_workbench_router.py` | Direct consumer. Must preserve any new evidence fields and must not synthesize contribution quality state. |
| `lotus-workbench` | `src/features/workbench/types.ts`, `src/apps/performance/*`, `tests/e2e/performance-workbench.smoke.spec.ts`, performance workspace unit/integration tests | Product-surface consumer. Must render safe supported/degraded contribution status when Gateway exposes it. |
| `lotus-report` | `src/app/clients/performance_client.py`, `src/app/reporting_lineage/capture_service.py`, `src/app/services/reporting_read_service.py`, `docs/supported-features.md` | Direct report consumer. Must preserve or consciously classify contribution evidence if response shape changes. |
| `lotus-manage` | `src/core/outcomes/performance_sources.py`, WTBD/RFC docs and supported features | Indirect outcome-feedback consumer. Must keep selected contribution measures source-owned and update adapter/tests if field names change. |
| `lotus-ai` | Advisor brief stubs and tests consume shaped contribution context | Indirect narrative consumer. Must not receive unsupported smoothing claims; update only if Gateway/advisor brief context changes. |
| `lotus-risk` | Mostly risk contribution vocabulary and migrated active analytics docs | No direct current `lotus-performance` contribution API consumer found in code search. Re-check if shared Carino helpers move across repos. |
| `lotus-core` | Source transaction specs and position-timeseries source routes | Upstream source-data owner. Update only if Slice 5 proves required source-economics fields are missing and within same-RFC scope. |

## Source-Economics Baseline

Current stateful contribution input can already use:

1. portfolio valuation observations from `lotus-core`;
2. position valuation rows;
3. beginning and ending market value in portfolio, reporting, or position currency;
4. cash-flow split by value basis;
5. management fees where carried in cash-flow payload;
6. position currency, cash-flow currency, and FX rate metadata;
7. hierarchy dimensions supplied by upstream position rows.

Missing or not first-class for RFC 047:

1. normalized performance P&L category fields such as price, income, fee, tax, FX, corporate-action,
   derivative, cash, and residual P&L;
2. explicit external versus internal component-flow reason codes beyond current cash-flow split;
3. source snapshot identifiers for valuation, transaction, classification, FX, and configuration
   evidence at contribution-output level;
4. component-level source-quality reason codes tied to missing classification, stale price, missing
   FX, partial view, or unsupported instrument family.

Slice 5 must decide whether these are implemented as additive `lotus-core` contracts, explicit
degraded/source-limited evidence in `lotus-performance`, or both.

## Test Baseline

Existing coverage already proves:

1. basic daily contribution and BOD weighting;
2. current Carino factor helper and invalid-domain fallback;
3. zero portfolio capital behavior;
4. hierarchy and position contribution rows;
5. residual-adjusted hierarchy and daily series tie-out;
6. top-N `Other` behavior;
7. no resolved periods and error handling;
8. stateful contribution input, cash-flow handling, FX requirements, async offload, and replay;
9. e2e stateful TWR/returns-series/contribution consistency;
10. reset-heavy tie-out and reset-aware average-weight diagnostics.

Required test deltas:

1. deterministic source-doc two-day `+10%/-10%` Carino example;
2. `F_t = k_t / K` factor proof and explicit factor evidence;
3. zero daily return using tolerance, not exact comparison;
4. zero linked return behavior;
5. invalid `-100%` period return and invalid total return status;
6. raw contribution mismatch before smoothing;
7. first-class smoothing status and reason-code response tests;
8. source-economics classification cases for internal trade, external deposit, income, fee, short,
   FX, missing classification, and partial hierarchy;
9. downstream Gateway/Workbench/report/manage preservation where contract shape changes.

## Slice 0 Go/No-Go

Go for Slice 1 with these controls:

1. Do not change contribution formulas until Slice 3.
2. Do not add response fields until Slice 4 after module boundaries are clean enough.
3. Treat Gateway, Workbench, Report, and Manage as downstream consumers that may need same-RFC
   updates if contribution API shape changes.
4. Treat `lotus-core` as upstream source authority but change it only after Slice 5 proves missing
   source economics cannot be truthfully handled by existing contracts and degraded evidence.
5. Keep documentation target-state language out of README/wiki until implementation proof exists.

## Validation

Commands run for Slice 0:

```powershell
git diff --check
python -m pytest tests/unit/docs/test_public_docs_contract.py -q
```

Result: passed.

No runtime tests were required for this slice because it only creates baseline RFC evidence and
does not change application behavior.
