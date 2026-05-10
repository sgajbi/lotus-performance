# RFC-046 Slice 8 Composite, Group, and Sleeve Boundary

| Field | Value |
| --- | --- |
| RFC | RFC-046 - TWR Industry Methodology Alignment, Evidence Contract, and Data Product Hardening |
| Slice | 8 - Composite/Group/Sleeve Boundary Documentation |
| `lotus-performance` branch | `feat/rfc-046-twr-industry-evidence` |

## Implementation

Slice 8 keeps RFC-046 focused on implementation-backed portfolio-level TWR and prevents unsupported
composite, group, or sleeve TWR claims from leaking into product material.

Changes made:

- renamed the TWR guide section from "Long and short sleeve handling" to "Long and short exposure
  handling" because the implementation is portfolio exposure compounding, not sleeve-level TWR
- added an explicit guide boundary that composite, group, and sleeve TWR calculation is not part of
  the current `POST /performance/twr` contract
- changed the integration capabilities feature description for `performance.analytics.twr` to
  "Portfolio-level time-weighted return analytics APIs"
- added `/integration/capabilities` TWR surface notes stating that the surface supports
  portfolio-level TWR only and does not advertise composite, group, or sleeve TWR calculation support
- refreshed the capabilities example payload so schema examples, docs examples, and runtime
  capabilities remain aligned
- replaced stale wiki "until RFC-046 slices are implemented" limitation wording with the current
  product boundary after Slices 4-7

No composite calculation code, first-class composite endpoint, group TWR endpoint, or sleeve TWR
endpoint was added.

## Boundary Review

The Slice 8 scan reviewed README, docs, wiki, app contract descriptions, tests, and integration
capability examples for misleading composite, group, or sleeve TWR language.

Findings:

- `docs/guides/twr.md` contained misleading "sleeve" wording for long/short exposure behavior and
  was corrected.
- `wiki/Time-Weighted-Return.md` already stated that composite, group, and sleeve TWR were not
  promoted, but its limitation section still described earlier RFC-046 slices as pending. It now
  describes the current supported boundary instead.
- `/integration/capabilities` previously described `performance.analytics.twr` too broadly as
  "Time-weighted return analytics APIs." It now advertises portfolio-level TWR explicitly.
- Existing older RFC files and backlog notes retain historical or planned composite language, but
  they are not current product, API, wiki, or supported-feature truth.

## Validation

Slice 8 validation commands:

- `python -m pytest tests/unit/docs/test_public_docs_contract.py tests/unit/models/test_integration_capabilities_models.py tests/integration/test_integration_capabilities_api.py -q`
  - Result: `61 passed`
- `make lint`
  - Result: passed, including the monetary-float guard with `135` findings and `135` allowlisted findings
- `make typecheck`
  - Result: `Success: no issues found in 159 source files`
- `python scripts/openapi_quality_gate.py`
  - Result: passed
- `python scripts/api_vocabulary_inventory.py --validate-only`
  - Result: passed with no vocabulary drift
- `python scripts/no_alias_contract_guard.py`
  - Result: passed
