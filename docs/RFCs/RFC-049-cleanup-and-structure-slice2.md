# RFC 049 Slice 2 - Cleanup and Structure Baseline

Status: completed

Branch: `draft/rfc-049-composite-performance-alignment`

PR: `sgajbi/lotus-performance#162`

Completed: 2026-05-12

## Purpose

Slice 2 removes ambiguity before implementation starts. Composite performance now has one approved
execution source: RFC 049. Older composite planning material remains available as history, but it
must not compete with RFC 049 or accidentally promote unsupported capabilities.

## Cleanup Performed

| Area | Change | Reason |
| --- | --- | --- |
| RFC 022 | Marked `RFC 022 - Composite & Sleeve Aggregation API` as historical and superseded by RFC 049. Added an explicit supersession notice. | RFC 022 assumed stateless `/composites/*` wrappers, broad composite analytics, and sleeve support. RFC 049 requires source authority, persisted member-return facts, batch/recalculation controls, composite TWR first, inspector/export evidence, lineage, and data-product certification before support claims. |
| RFC index | Updated RFC-022 to historical/superseded and updated RFC-049 Slice 1 evidence to reference the merged platform scaffold prerequisite. | The index should route implementers to the current source of truth and avoid stale implementation candidates. |
| Delta backlog | Reclassified RFC-022-D01 as `in_progress_via_rfc_049`. | RFC 022 no longer needs an ownership decision as a standalone RFC; RFC 049 owns the approved composite-performance delivery path. |
| Wiki roadmap | Added an RFC 049 current-state note. | Business, operations, sales, and engineering readers need to know composite performance is being implemented but is not yet a supported product claim. |
| Wiki RFC index | Added RFC 049 to the high-value local RFC list with an unsupported-until-proven boundary. | Wiki navigation should expose the active RFC without duplicating the full RFC body. |

## Documentation Structure Decision

No separate composite wiki feature page is created in this slice.

Reason:

1. composite performance is not yet implemented or supported;
2. a feature page at this point would either duplicate RFC 049 or become aspirational product
   material;
3. the final RFC 049 documentation slices will create implementation-backed wiki/product material
   after the API, data product, inspector, exports, lineage, downstream consumers, and live proof
   exist.

Until then, composite truth is intentionally split as follows:

| Truth type | Current source |
| --- | --- |
| Approved implementation plan | `docs/RFCs/RFC 049 - Composite Performance Industry Methodology Alignment and Evidence Contract.md` |
| Historical superseded plan | `docs/RFCs/RFC 022 - Composite & Sleeve Aggregation API.md` |
| Supported product claims | `wiki/Supported-Features.md` |
| Current roadmap posture | `wiki/Roadmap.md` |
| RFC navigation | `docs/RFCs/RFC-INDEX.md`, `wiki/RFC-Index.md` |

## Current Support Boundary

After this slice:

1. composite TWR, group TWR, sleeve TWR, composite MWR, composite contribution, composite
   attribution, and carve-out/sleeve analytics remain unsupported;
2. RFC 049 is the only approved route for promoting composite support;
3. no docs or wiki page claims composite support before implementation-backed proof exists.

## Validation

```powershell
git diff --check
python -m pytest tests\unit\docs\test_public_docs_contract.py -q
powershell -ExecutionPolicy Bypass -File ..\lotus-platform\automation\Sync-RepoWikis.ps1 -CheckOnly -Repository lotus-performance
```

Result:

- `git diff --check` -> passed.
- `python -m pytest tests\unit\docs\test_public_docs_contract.py -q` -> 42 passed.
- `Sync-RepoWikis.ps1 -CheckOnly -Repository lotus-performance` -> expected publication drift for
  `RFC-Index.md` and `Roadmap.md` because this slice changes repo-local wiki source on the RFC 049
  branch. Final closure must rerun the check and publish after merge to `main`.
