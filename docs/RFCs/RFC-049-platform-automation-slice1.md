# RFC 049 Slice 1 - Platform Automation and Scaffolding Baseline

Status: completed; platform prerequisite merged

Branch: `draft/rfc-049-composite-performance-alignment`

PR: `sgajbi/lotus-performance#162`

Platform PR: `sgajbi/lotus-platform#326` (merged)

Completed: 2026-05-12

## Purpose

Slice 1 reviews whether RFC 049 should improve `lotus-platform` automation before adding
composite-specific implementation inside `lotus-performance`.

The goal is to avoid solving repeatable platform concerns locally when they should belong to
platform scaffolding for future Lotus applications.

## Stranded Platform Truth Reconciliation

Commands run in `lotus-platform`:

```powershell
git fetch origin --prune
git branch -r --no-merged origin/main
```

Unmerged branches found:

| Branch | Classification | RFC 049 treatment |
| --- | --- | --- |
| `origin/feat/clarify-lotus-manage-role` | active | Other agent is actively working on this branch. It touches central context role wording only. RFC 049 will not edit or cherry-pick it. Final closure must re-check that no required platform truth remains stranded. |
| `origin/feat/rfc-0036-platform-scaffold-certification` | merged/delete | Other agent completed this branch. It directly covered platform scaffold endpoint-certification hardening. RFC 049 opened and merged `sgajbi/lotus-platform#326`, merging current `origin/main` into the branch first and resolving the scaffold/test conflicts by preserving mainline source-degraded guidance and endpoint-certification scaffolding. The remote branch was deleted by PR merge; the stale local remote-tracking ref was removed. |

`lotus-platform` changes in this slice were limited to reconciling and merging the completed
`feat/rfc-0036-platform-scaffold-certification` branch with current `origin/main` so the platform
scaffolding truth no longer remains stranded. No unrelated platform cleanup or RFC 049
composite implementation was added to `lotus-platform`.

## Platform Automation Baseline

Current and active platform evidence reviewed:

| Area | Evidence | Assessment |
| --- | --- | --- |
| Service scaffold automation | `automation/New-Lotus-Service.ps1` merged by `sgajbi/lotus-platform#326` | Platform main now adds/extends a one-command backend scaffold with FastAPI, health/readiness, metadata, structured logging, correlation/trace headers, problem details, docs, wiki baseline, supported-features placeholder, endpoint-certification ledger, source-degraded endpoint guidance, and automation registration. |
| Backend Makefile template | `platform-standards/templates/Makefile.backend.template` merged by `sgajbi/lotus-platform#326` | Platform main now includes `endpoint-certification-gate`, `supported-features-gate`, `no-sensitive-content-guard`, `openapi-gate`, coverage, security audit, Docker build, and CI targets. |
| Scaffold contract tests | `tests/unit/test_repository_hygiene_scaffold_contract.py` merged by `sgajbi/lotus-platform#326` | Platform main now tests generated service scaffolding for OpenAPI quality, endpoint certification, supported features, no-sensitive-content guard, correlation/trace headers, source-degraded guidance, docs, and repository hygiene. |
| Platform standards README | `platform-standards/README.md` merged by `sgajbi/lotus-platform#326` | Platform main now documents the scaffold output, including endpoint certification and supported-features placeholders. |
| Data-product onboarding automation | `automation/generate_domain_product_onboarding.py` on current main | Current platform already generates source-data and analytics-output product onboarding bundles, API certification checklist, trust metadata, source-data API profile, ingestion pipeline checklist, README, and onboarding checklist. |
| Mesh certification | `automation/mesh_certification_gate.py`, domain-product contracts, trust telemetry validators | Current platform already has generated catalog/certification paths for data-product promotion. |
| Wiki publication automation | `automation/Sync-RepoWikis.ps1` | Current platform already owns repo-local wiki check/publish flow. |

## Gap Assessment

| Gap | Classification | Treatment |
| --- | --- | --- |
| Endpoint certification should be part of default backend scaffold | Merged by `sgajbi/lotus-platform#326` | Use this pattern when certifying composite endpoints. |
| Supported-features gate should be scaffolded by default | Merged by `sgajbi/lotus-platform#326` | RFC 049 will use the pattern when composite support is promoted. |
| No-sensitive-content guard should be scaffolded by default | Merged by `sgajbi/lotus-platform#326` | RFC 49 hardening will use repo-local tests for logs/metrics/artifacts. |
| Correlation and trace headers should be scaffolded by default | Merged by `sgajbi/lotus-platform#326` | RFC 49 composite implementation still needs repo-specific propagation proof. |
| Composite batch worker/container scaffolding | Not a generic platform default yet | Defer local design to RFC 049 Slice 4/Slice 6. Promote platform-level template only if implementation proves it is reusable beyond `lotus-performance`. |
| Composite inspector/export artifact scaffolding | Not a generic platform default yet | Defer to RFC 049 Slice 7A. Promote reusable platform guidance only if repeated across other apps. |
| Data-product onboarding for analytics outputs | Already present | Use existing platform onboarding and mesh certification tooling; update only if composite reveals a generic gap. |

## Slice 1 Decision

RFC 049 uses the completed platform scaffold-certification work instead of duplicating it locally.

Reason:

1. the most relevant repeatable scaffold gap, endpoint certification in the backend scaffold, is
   already implemented on `feat/rfc-0036-platform-scaffold-certification`;
2. current platform main already contains data-product onboarding, trust telemetry validation,
   mesh certification, wiki publication, and context validation automation;
3. RFC 049 reconciled the completed scaffold branch with current platform main and merged
   `sgajbi/lotus-platform#326`, so the durable platform truth is no longer stranded;
4. composite-specific worker, inspector, export, lineage, and persisted-fact needs are not yet
   proven as reusable platform defaults.

Closure rule:

1. before RFC 049 final closure, rerun stranded-truth reconciliation in `lotus-platform`;
2. verify no RFC 049-required platform scaffold truth is stranded outside `main`;
3. if composite implementation discovers reusable scaffolding gaps, add them to `lotus-platform`
   in the relevant later slice rather than localizing the workaround.

## Validation

Validation:

```powershell
cd C:\Users\Sandeep\projects\lotus-platform
python -m pytest tests\unit\test_repository_hygiene_scaffold_contract.py -q
git diff --check

cd C:\Users\Sandeep\projects\lotus-performance
git diff --check
python -m pytest tests\unit\docs\test_public_docs_contract.py -q
```

Platform validation result before pushing PR #326 reconciliation:

- `python -m pytest tests\unit\test_repository_hygiene_scaffold_contract.py -q` -> 2 passed.
- `git diff --check` -> passed.
- GitHub PR #326 checks -> all passed: Cross-App Vocabulary Gate, Feature Lane / Platform Repo
  Contracts, Feature Lane / Workflow Lint, PR Merge Gate / Platform Repo Contracts, PR Merge Gate /
  Workflow Lint.
- `git checkout main; git pull --ff-only` in `lotus-platform` fast-forwarded to the merged PR.
- `git branch -r --no-merged origin/main` after stale-ref cleanup shows only
  `origin/feat/clarify-lotus-manage-role`, which is unrelated to RFC 049 composite scaffolding.
