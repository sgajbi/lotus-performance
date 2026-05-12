# RFC 049 Slice 3 - Source Authority and Member-Return Fact Foundation

Status: completed

Branch: `draft/rfc-049-composite-performance-alignment`

PR: `sgajbi/lotus-performance#162`

Completed: 2026-05-12

## Purpose

Slice 3 establishes the governed source, membership, and persisted member-return fact foundation for
composite performance. It does not calculate composite returns yet. Later RFC 049 slices must
consume this foundation rather than calculating composites from hidden request-time TWR fan-out.

## Implementation

| Area | Files | Outcome |
| --- | --- | --- |
| Composite contract models | `app/models/composites.py` | Added source-authority, composite definition, effective-dated membership, and persisted member-return fact models with strict validation and private-banking vocabulary. |
| Durable composite store | `app/services/composite_metadata_store.py` | Added a SQLAlchemy-backed store for composite definitions, memberships, and member-return facts using the repository's existing durable metadata store pattern. |
| Bootstrap integration | `app/services/durable_metadata_bootstrap.py` | Added composite metadata schema creation to the standard durable metadata bootstrap flow. |
| Model tests | `tests/unit/models/test_composite_models.py` | Validates date windows, required exclusion reasons, required degraded fact reason codes, and ready persisted facts. |
| Store tests | `tests/unit/services/test_composite_metadata_store.py` | Validates round-trip storage and restatement/upsert semantics for member-return facts. |

## Domain Decisions

1. `lotus-manage` is modeled as the source authority for composite definitions and membership.
2. `lotus-performance` is modeled as the source authority for persisted member-return facts.
3. `lotus-core` is modeled as the source authority for member assets and benchmark assignment.
4. RFC 049 starts with `ASSET_WEIGHTED` composite calculation method support. Aggregate virtual
   portfolio, sleeves/carve-outs, composite MWR, composite contribution, and composite attribution
   remain unsupported until explicitly implemented and proven by later approved slices.
5. Member-return facts persist decimal values as text in the durable store so SQLite and other local
   test paths do not coerce return facts through binary floating point. This is required for
   banking-grade restatement and audit behavior.

## Current Capability Boundary

This slice adds internal implementation foundation only:

1. no public composite API exists yet;
2. no composite calculation engine exists yet;
3. no supported composite feature claim is promoted yet;
4. no downstream Gateway or Workbench change is required yet;
5. no wiki feature page is created yet because the capability is not product-supported.

## Validation

```powershell
python -m ruff check app\models\composites.py app\services\composite_metadata_store.py app\services\durable_metadata_bootstrap.py tests\unit\models\test_composite_models.py tests\unit\services\test_composite_metadata_store.py
python -m pytest tests\unit\models\test_composite_models.py tests\unit\services\test_composite_metadata_store.py tests\unit\services\test_durable_metadata_bootstrap.py -q
python -m pytest tests\unit\docs\test_public_docs_contract.py -q
git diff --check
```

Result:

- Ruff targeted check -> passed.
- Composite model/store/bootstrap tests -> 8 passed.
- Docs contract tests -> 42 passed.
- `git diff --check` -> passed.
- PR #162 checks before this slice commit were green; checks must rerun after this slice is pushed.
