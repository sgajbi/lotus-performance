# RFC 049 Slice 7 - Benchmark, Assets, Fees, Dispersion, and Restatement Evidence

Date: 2026-05-12
Branch: `draft/rfc-049-composite-performance-alignment`
PR: `sgajbi/lotus-performance#162`
Status: Implemented and locally validated

## Purpose

Slice 7 strengthens composite TWR from a single return number into an auditable composite evidence
contract. The implementation remains intentionally bounded to persisted-fact composite TWR. It does
not introduce composite contribution, composite attribution, composite MWR, or unsupported benchmark
active-return claims.

## Implemented Changes

### Fee-View Separation

Added `CompositeReturnView` with:

1. `GROSS`;
2. `NET_ACTUAL`;
3. `NET_MODEL_FEE`.

Persisted member-return facts now carry `return_view`. The engine blocks a period with
`mixed_member_return_views` when ready member facts mix gross, net actual, and model-fee net views.
This prevents silent mixing of fee bases inside one composite result.

### Composite Currency and Asset Evidence

The engine now checks ready member facts for a single `reporting_currency`. It blocks a period with
`mixed_member_reporting_currencies` when ready facts are not in the same composite currency. The
response exposes period-level `reporting_currency`, beginning assets, ending assets, member counts,
excluded member counts, and member-level beginning-asset weights.

### Dispersion Policy

Equal-weight sample standard deviation remains the supported dispersion calculation. It is emitted
only when at least two ready member facts are available; otherwise it remains null. This avoids
presenting one-member dispersion as meaningful.

### Restatement and Source-Fingerprint Evidence

Persisted member-return facts now carry:

1. `source_fingerprint`;
2. `restatement_version`.

The API response exposes:

1. period-level ordered `source_fingerprints`;
2. period-level ordered `restatement_versions`;
3. member-contribution-level `source_fingerprint`;
4. member-contribution-level `restatement_version`.

This gives support, audit, and future restatement-diff workflows enough evidence to explain which
member facts were used without inventing methodology after the fact.

### Durable Schema Hardening

While validating the API against the existing local runtime metadata store, Slice 7 found a real
schema-upgrade gap: `create_schema()` created missing tables but did not add new columns to an
existing SQLite `composite_member_return_facts` table.

The store now performs an additive SQLite upgrade for:

1. `return_view` with default `NET_ACTUAL`;
2. `source_fingerprint` with bounded legacy marker `legacy-source-fingerprint-unavailable`;
3. `restatement_version` with default `v1`.

This keeps older local/runtime stores usable while making the missing lineage evidence explicit.

## Unsupported or Deferred Within Slice 7

The following RFC 049 items remain intentionally deferred because they need later stores or source
contracts:

1. benchmark return and active return: deferred until composite benchmark source/version evidence is
   available;
2. restatement diff artifacts: deferred until composite result versions and artifact generation
   exist;
3. publish/restatement controls: deferred until operational APIs and result-version store exist;
4. model-fee net calculation: only the return view is guarded now; actual model-fee derivation needs
   policy/source support before it can be claimed;
5. composite contribution and attribution: still gated and unsupported.

## Validation Evidence

Local validation passed:

1. `python -m ruff check app\api\endpoints\composites.py app\models\composites.py app\services\composite_metadata_store.py engine\composites.py tests\unit\models\test_composite_models.py tests\unit\services\test_composite_metadata_store.py tests\unit\engine\test_composites.py tests\unit\services\test_composite_calculation_service.py tests\integration\test_composites_api.py`;
2. `python -m ruff format --check app\api\endpoints\composites.py app\models\composites.py app\services\composite_metadata_store.py engine\composites.py tests\unit\models\test_composite_models.py tests\unit\services\test_composite_metadata_store.py tests\unit\engine\test_composites.py tests\unit\services\test_composite_calculation_service.py tests\integration\test_composites_api.py`;
3. `python -m pytest tests\unit\models\test_composite_models.py tests\unit\services\test_composite_metadata_store.py tests\unit\engine\test_composites.py tests\unit\services\test_composite_calculation_service.py tests\integration\test_composites_api.py tests\unit\app\test_composites_openapi_contract.py -q`;
4. `python -m mypy --config-file mypy.ini`;
5. `python scripts\openapi_quality_gate.py`;
6. `make api-vocabulary-gate`;
7. `python -m pytest tests\unit\docs\test_public_docs_contract.py -q`.

## Slice 7 Conclusion

Slice 7 is complete for the currently implemented persisted-fact composite TWR surface. The result
is stronger: gross/net/model-fee facts cannot be mixed, composite currency must be consistent,
dispersion remains policy-bounded, member source fingerprints and restatement versions are exposed,
and durable schema upgrade behavior is safer for existing runtime stores.
