# RFC 048 Slice 2 - Cleanup and Structure Evidence

| Field | Value |
| --- | --- |
| RFC | RFC-048 - Attribution Industry Methodology Alignment and Evidence Contract |
| Slice | 2 - Cleanup and Structure |
| Status | Complete |
| Date | 2026-05-11 |
| Branch | `feat/rfc-048-attribution-industry-alignment` |

## Purpose

Slice 2 simplifies the attribution documentation structure before behavior and contract changes are
made. The goal is to reduce documentation sprawl, make durable product material easier to find, and
avoid stale or misleading attribution statements before the RFC 048 implementation slices expand the
contract.

## Cleanup Review

| Area | Finding | Action |
| --- | --- | --- |
| Attribution docs structure | Attribution had a guide and endpoint certification note, but no documentation map or wiki product page equivalent to the TWR and contribution structures. | Added `docs/technical/attribution-documentation-map.md` and `wiki/Attribution-Analytics.md`. |
| Wiki navigation | Current wiki navigation linked TWR and contribution, but not attribution as a first-class product surface. | Added Attribution Analytics to `wiki/_Sidebar.md`, `wiki/Home.md`, `wiki/API-Surface.md`, and `wiki/Supported-Features.md`. |
| Supported-feature wording | Attribution wording was accurate but too thin for product/demo use and did not clearly state unsupported advanced models. | Expanded attribution supported-feature text with current evidence, RFC 048 improvement boundary, and explicit non-supported fixed-income factor, derivative, sleeve, and composite claims. |
| Endpoint certification | `docs/technical/attribution-endpoint-certification.md` still described `lotus-gateway#105` and `lotus-gateway#106` as open tracking issues. | Verified both issues are closed and updated the certification note to avoid stale "remaining issue" language. |
| Docs contract coverage | Public docs contract tests covered TWR documentation navigation but not attribution documentation navigation. | Added `test_attribution_documentation_map_and_wiki_navigation_are_present`. |
| Engine/code cleanup | No safe dead attribution engine code was proven in Slice 2. | No code deletion. Later slices may refactor after characterization tests prove behavior and integration boundaries. |

## Durable Documentation Boundary

The new attribution documentation structure keeps ownership clear:

1. `docs/guides/attribution.md` remains the developer-facing API usage guide.
2. `docs/methodologies/metrics/metric-attribution-*.md` remains the formula and metric-methodology
   authority.
3. `docs/technical/attribution-endpoint-certification.md` remains the endpoint certification and
   downstream-consumer proof note.
4. `wiki/Attribution-Analytics.md` is the durable product-facing overview for business,
   operations, sales/pre-sales, demos, and cross-functional onboarding.
5. RFC 048 slice files remain implementation-control artifacts, not product docs.

## Validation Evidence

Local validation completed on 2026-05-11:

1. `python -m ruff format tests\unit\docs\test_public_docs_contract.py` - passed
2. `python -m ruff check tests\unit\docs\test_public_docs_contract.py` - passed
3. `python -m pytest tests\unit\docs\test_public_docs_contract.py -q` - `42 passed`
4. `git diff --check` - passed

Wiki publication drift check before commit:

```powershell
powershell -ExecutionPolicy Bypass -File ..\lotus-platform\automation\Sync-RepoWikis.ps1 -CheckOnly -Repository lotus-performance
```

Result: expected pre-merge drift reported for `_Sidebar.md`, `API-Surface.md`,
`Attribution-Analytics.md`, `Home.md`, and `Supported-Features.md` because Slice 2 changed the
repo-local wiki source. This is not published from the feature branch. RFC 048 final closure must
rerun the check after merge and publish with `Sync-RepoWikis.ps1 -Publish -Repository
lotus-performance`.

## Slice 2 Review

The slice is documentation-structure cleanup only. It deliberately avoids changing runtime behavior
before the attribution status, residual, alignment, evidence, data-product, and downstream slices
add characterization and contract tests.

No duplicate documentation was introduced: the wiki page is a product navigation layer and boundary
statement, while field-level API detail remains in `docs/guides/attribution.md` and formulas remain
in metric methodology docs.

## Closure Decision

Slice 2 is complete when:

1. the docs map and wiki product page are committed;
2. stale Gateway issue wording is corrected;
3. public docs tests pass and expected pre-merge wiki publication drift is recorded;
4. PR #160 CI remains green after push.
