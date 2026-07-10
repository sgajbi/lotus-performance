# Issue Fix Closure Matrix

This matrix records the current local closure posture for the GitHub issue batch on branch
`feat/performance-architecture-boundary-refactor`.

It is intentionally stricter than "code changed": an issue is only safe to close after the fix is
merged to `main`, required checks are green, and any changed repo-authored wiki source is published.
Until then, the local status can be `Fixed locally` while the GitHub issue remains open.

## Current Batch Summary

| Category | Count | Notes |
| --- | ---: | --- |
| Open GitHub issues reviewed | 22 | Includes the tracking ledger issue `#380`. |
| Actionable issues fixed locally | 21 | Issues `#387`, `#388`, `#389`, `#390`, `#391`, `#392`, `#393`, `#396`, `#397`, `#398`, `#399`, `#400`, `#401`, `#415`, `#417`, `#424`, `#425`, `#442`, `#452`, `#453`, and `#454`. |
| Tracking ledger issues | 1 | Issue `#380` remains open as the discovery ledger, not as a fix ticket. |
| Issues safe to close now | 0 | Closure waits for PR merge, CI evidence, and wiki publication where applicable. |

## Verification Baseline

Latest local pre-PR verification for this batch:

- Local `make check`: passed with `3301 passed`.
- `make quality-test-taxonomy-gate`: passed with 297 modules, 3,449 source test functions, 658
  API/runtime test functions, 132 contract/governance test functions, and 969 uncategorized test
  functions.
- `make openapi-gate` and `python scripts/api_vocabulary_inventory.py --validate-only`: passed.
- Wiki check-only: expected unpublished branch drift where repo-authored wiki source changed; publish
  with the governed wiki automation after merge to `main`.

## Issue Matrix

| Issue | Local status | Ledger evidence | Same-pattern and regression posture | Close condition |
| --- | --- | --- | --- | --- |
| `#415` Certify mandate health in integration capabilities publication | Fixed locally | `LP-CR-1654` | The certification page now lists `mandate_performance_health_context` as a certified analytics surface with its stateless DPM supportability boundary. Docs regression now compares the certified surface list with both the canonical example payload and the generated runtime report, preventing future capability-publication drift. | Close after merge and green PR evidence. |
| `#417` Stop presenting static trust telemetry fixtures as runtime proof | Fixed locally | `LP-CR-1655` | Repo-owned `contracts/trust-telemetry/` files are now explicitly classified as static fallback fixtures, not runtime proof. Tests verify the README wording and fixture `source_artifact_uri` classification so contract fixtures cannot be mislabeled as runtime telemetry without separate runtime output evidence. | Close after merge and green PR evidence. |
| `#424` Make migration-apply exercise durable schema upgrades, not only contract prose | Fixed locally | `LP-CR-1656` | `make migration-apply` now runs executable durable schema bootstrap apply/verify through `scripts/durable_schema_apply.py`, emits structured operator evidence under `artifacts/durable-schema-apply/`, verifies owned execution, compute, async-result, lineage, and composite metadata tables, and checks additive lineage/composite schema columns. Same-pattern scan kept prose-only validation in clearly named contract/inventory/runbook targets while blocking `migration-apply` from reverting to the prose checker. | Close after merge, green PR evidence, and wiki publication. |
| `#425` Clarify and enforce returns-series strict-intersection fill semantics | Fixed locally | `LP-CR-1657` | Returns-series normalization now applies selected benchmark/risk-free fill before strict intersection, while strict no-fill behavior remains unchanged. Diagnostics expose `fill_evidence` so filled side-series dates are distinguishable from observed source dates, and freshness continues to use source frames. Same-pattern coverage includes benchmark and risk-free side series, forward-fill and zero-fill, API behavior, active/cumulative active outputs, docs certification, method docs, runbook, and wiki source. | Close after merge, green PR evidence, and wiki publication. |
| `#452` Publish an endpoint-by-endpoint RFC-020 multi-currency support matrix | Fixed locally | `LP-CR-1658` | Added the canonical RFC-020 multi-currency support matrix covering TWR, MWR, Contribution, Attribution, Benchmark, Returns Series, and Workspace Summary. RFC-020/RFC index, API reference, endpoint guides, methodology docs, certification pages, and wiki source now point to endpoint-specific support truth. Docs-contract coverage parses the matrix and guards MWR `SINGLE_REPORTING_CURRENCY` / `SOURCE_PRECONVERTED_WITH_FX_EVIDENCE`, Attribution `currency_mode=\"BOTH\"`, Contribution local/FX reconciliation, and returns-series non-decomposition semantics. | Close after merge, green PR evidence, and wiki publication. |
| `#397` Protect TWR inspection artifact downloads with privileged-read authorization | Fixed locally | `LP-CR-1625` | Central privileged-read rule family now covers `/performance/inspections`; same-class file-backed evidence route scan found lineage already governed and inspections aligned; unit and integration authz tests cover parent and child artifact paths. | Close after merge and green PR evidence. |
| `#396` Normalize stateful source currency codes before mixed-currency FX gating | Fixed locally | `LP-CR-1626` | Shared `normalized_currency_code(...)` helper replaces raw string comparisons across contribution, attribution, and cash-flow currency checks; blank, whitespace, case-only, and true mixed-currency regressions are covered. | Close after merge and green PR evidence. |
| `#388` Normalize legacy ITD period usage to canonical SI across performance APIs | Fixed locally | `LP-CR-1627` | Since-inception aliases normalize to canonical `SI` before calculations, metadata, lineage windows, and response keys; current authored examples reject `"period": "ITD"` unless documenting alias compatibility. | Close after merge and green PR evidence. |
| `#401` Add jitter and retry-budget controls to upstream HTTP retries | Fixed locally | `LP-CR-1628` | Shared outbound HTTP retry helper now uses bounded fallback jitter, preserves safe `Retry-After`, records retry-budget diagnostics, and has entropy/bounds tests to avoid concurrent retry waves. | Close after merge and green PR evidence. |
| `#400` Declare active benchmark and index upstream products in the data-mesh consumer contract | Fixed locally | `LP-CR-1629` | Active benchmark/index dependencies are machine-readable consumer declarations; watchlist-only dependencies remain explicitly documented until upstream producer declarations exist; domain-product validation covers the contract. | Close after merge, green PR evidence, and wiki publication. |
| `#399` Promote runtime alert templates into deployable validated monitoring artifacts | Fixed locally | `LP-CR-1630` | Deployable PrometheusRule and Grafana artifacts are repo-owned; observability readiness gate validates alert metrics, labels, links, dashboard panels, and sensitive-label policy. | Close after merge, green PR evidence, and wiki publication. |
| `#398` Add local README indexes for major repository packs | Fixed locally | `LP-CR-1631` | Major source, docs, contracts, quality, scripts, tests, monitoring, and wiki packs now have local README indexes; documentation inventory enforces 12/12 coverage. | Close after merge, green PR evidence, and wiki publication. |
| `#393` Align repo context with full performance trust telemetry coverage | Fixed locally | `LP-CR-1632` | Repository context now follows the all-active-product trust telemetry rule derived from domain-product declarations and trust telemetry snapshots; docs tests block the stale single-product claim. | Close after merge and green PR evidence. |
| `#392` Make governed agent reading order discoverable from repo context surfaces | Fixed locally | `LP-CR-1633` | README, repo context, docs pack index, and wiki Home expose `AGENTS.md`, procedural memory, skill routing, and wiki publication navigation; docs tests protect the reading-order surface. | Close after merge, green PR evidence, and wiki publication. |
| `#391` Align cleanup scope with generated runtime artifact policy | Fixed locally | `LP-CR-1634` | `make clean` now plans runtime/evidence roots, local coverage variants, SQLite sidecars, and logs while preserving durable source truth; cleanup and hygiene tests cover the policy. | Close after merge, green PR evidence, and wiki publication. |
| `#389` Align integration-capabilities examples with runtime capability truth | Fixed locally | `LP-CR-1635` | OpenAPI and JSON examples now match runtime capability output for TWR inspection notes, sync path-template nulls, and mandate health wording; model and docs regressions compare runtime truth to published examples. | Close after merge and green PR evidence. |
| `#390` Refresh integration-capabilities certification after Gateway query-param fix | Fixed locally | `LP-CR-1636` | Endpoint certification now reflects current Gateway canonical `consumer_system` and `tenant_id` behavior; docs regression blocks stale camelCase/current-issue wording. | Close after merge and green PR evidence. |
| `#387` Refresh stale quality evidence after post-fix suite and architecture drift | Fixed locally | `LP-CR-1637` | Quality taxonomy, baseline, scorecard, and CI gate evidence are refreshed from repo-native scanners; docs guard derives current taxonomy counts to prevent future stale evidence. | Close after merge and green PR evidence. |
| `#442` Add polling cadence guidance to async 202 responses | Fixed locally | `LP-CR-1651` | Shared async accepted response projection now emits `recommended_poll_after_seconds` and matching `Retry-After` headers for initial submissions and pending-result responses across TWR, benchmark, contribution, attribution, returns-series, workspace-summary, and TWR inspection; OpenAPI, docs, and representative integration tests distinguish analytics polling cadence from manual operator-action cooldowns. | Close after merge, green PR evidence, and wiki publication. |
| `#454` Complete attribution diagnostics and audit footer parity | Fixed locally | `LP-CR-1652` | Completed attribution responses now require non-null shared `diagnostics` and `audit` footer blocks, with bounded period-status, residual-materiality, supportability-evidence, input, level, group, reason, supportability, residual, and benchmark-context counts. Same-pattern coverage adds a cross-endpoint footer parity contract for TWR, MWR, Contribution, and Attribution, and RFC-014-D02 is closed in the delta backlog. | Close after merge, green PR evidence, and wiki publication. |
| `#453` Enforce or retire flags.fail_fast consistently across core analytics endpoints | Fixed locally | `LP-CR-1653` | Shared fail-fast policy now covers completed TWR, MWR, Contribution, and Attribution responses. Same degraded requests return `200` when `flags.fail_fast=false` and `422` with `FAIL_FAST_SOFT_WARNING` when true. Same-pattern coverage verifies TWR daily evidence warnings, MWR fallback warnings, Contribution diagnostic notes, and Attribution supportability reasons; RFC-014-D01 is closed in the delta backlog. | Close after merge, green PR evidence, and wiki publication. |
| `#380` Lotus Performance Issue Discovery Ledger | Tracking ledger | Review ledger plus this matrix | This remains the parent discovery ledger for the campaign. Do not close it as part of one batch unless the broader campaign owner explicitly signs off. | Keep open. |

## No-PR-Yet Decision

No PR should be raised from this branch until the issue matrix remains complete, the branch is pushed,
and current local or remote validation evidence is available. This file does not close the issues by
itself; it gives the PR author and reviewers a single place to confirm that the local fixes, similar
pattern scans, docs/context/wiki decisions, and closure gates line up.
