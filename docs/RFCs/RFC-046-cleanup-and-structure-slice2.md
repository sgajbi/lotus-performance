# RFC-046 Slice 2 Cleanup and Structure Evidence

| Field | Value |
| --- | --- |
| RFC | RFC-046 - TWR Industry Methodology Alignment, Evidence Contract, and Data Product Hardening |
| Slice | 2 - Cleanup and Structure |
| Status | Complete for Slice 2 implementation |
| Date | 2026-05-10 |
| Branch | `feat/rfc-046-twr-industry-evidence` |

## Purpose

Slice 2 cleans the implementation path before changing TWR response semantics. The goal is to
reduce documentation sprawl, make the wiki/source-doc boundary explicit, and avoid burying durable
TWR product truth in RFC-only execution artifacts.

## Stranded-Truth Check

Before starting Slice 2, RFC branch governance was rerun:

```powershell
git fetch origin --prune
git branch -r --no-merged origin/main
```

Result:

| Branch | Classification | Slice 2 decision |
| --- | --- | --- |
| `origin/feat/api-contract-hardening` | `superseded` for RFC-046 | No merge or cherry-pick. Slice 0 already proved the durable public-input hardening truth is present on current mainline and the branch is stale. |

No additional unclassified TWR, documentation, wiki, context, contract, OpenAPI, migration, or CI
truth was found before Slice 2 started.

## Cleanup Review

| Area | Finding | Action |
| --- | --- | --- |
| TWR engine code | No safe dead TWR calculation code was identified for deletion before denominator/linkability characterization. | No code deletion in Slice 2; defer any engine cleanup until Slice 4 and Slice 5 tests prove a path is dead or duplicated. |
| TWR documentation structure | TWR truth was spread across the TWR guide, metric methodology docs, reset scenarios, inspection certification, endpoint certification, and wiki pages without one routing map. | Added `docs/technical/twr-documentation-map.md`. |
| Wiki product navigation | The wiki had strong general API/integration pages but no dedicated TWR page for business, operations, sales/pre-sales, demos, and developer orientation. | Added `wiki/Time-Weighted-Return.md` and linked it from wiki navigation. |
| Duplicate docs risk | Copying formulas or full API payloads into the wiki would create a second source of truth. | The wiki page summarizes implemented capability and routes to implementation-backed docs instead of duplicating field-level contracts or formulas. |
| Documentation regression protection | No test guarded the new TWR docs/wiki navigation structure. | Added `test_twr_documentation_map_and_wiki_navigation_are_present`. |

## Implemented Changes

1. Added `docs/technical/twr-documentation-map.md`.
2. Added `wiki/Time-Weighted-Return.md`.
3. Linked the TWR map from `docs/technical/methodology_index.md`.
4. Linked the wiki TWR page from:
   - `wiki/_Sidebar.md`
   - `wiki/Home.md`
   - `wiki/API-Surface.md`
   - `wiki/Integrations.md`
5. Added a stateful TWR source-flow diagram to `wiki/Integrations.md`.
6. Added documentation contract coverage in `tests/unit/docs/test_public_docs_contract.py`.

## Wiki Layering Decision

The repo-local wiki is now the durable audience-facing entrypoint for TWR product explanation. It
does not own:

1. field-level API contracts,
2. detailed formula derivation,
3. RFC execution decisions,
4. unimplemented target-state claims.

Those remain in OpenAPI, `docs/guides/twr.md`, metric methodology docs, technical certification
docs, and RFC evidence artifacts.

## Validation

Targeted validation completed on 2026-05-10:

1. `python -m pytest tests/unit/docs -q` - `49 passed`
2. `python scripts/no_alias_contract_guard.py` - passed
3. `git diff --check` - no whitespace errors; existing LF/CRLF warnings only
4. `powershell -ExecutionPolicy Bypass -File ..\lotus-platform\automation\Sync-RepoWikis.ps1 -CheckOnly -Repository lotus-performance` - expected drift reported for `_Sidebar.md`, `API-Surface.md`, `Home.md`, `Integrations.md`, and `Time-Weighted-Return.md` because Slice 2 added repo-local wiki truth that must not be published before the RFC branch is merged. Final closure must publish the wiki after merge and rerun check-only clean.

## Closure Decision

Slice 2 is complete when the validation commands above pass and this evidence is committed:

1. documentation structure is clearer,
2. wiki/source-doc layering is explicit,
3. no unsupported composite, group, or sleeve TWR claim was introduced,
4. the new structure is protected by tests,
5. no risky code deletion was attempted before characterization evidence exists.

The only open Slice 2 publication item is governed wiki publication after merge. The repo-local
wiki source is intentionally ahead of the published wiki until RFC-046 is merged.
