# Governed Composite Materialization

This bounded workflow creates immutable composite member facts from published Manage authority
and retained stateful Performance TWR results. It does not accept uploaded returns, invent missing
valuations, or certify a live upstream deployment. Live Manage universe qualification remains a
separate acceptance dependency.

Configure `MANAGE_BASE_URL` to the deployment's API prefix, including `/api/v1` for Manage's
standard routing. `MANAGE_TIMEOUT_SECONDS` defaults to 10; source HTTP retries use the existing
`CORE_MAX_RETRIES` and `CORE_RETRY_BACKOFF_SECONDS` policy. Both API and compute worker deployments
need this source configuration. An absent URL retains source-unavailable progress; it is not
successful live-source acceptance.

## API And Authority

| Operation | Contract |
| --- | --- |
| Submit | `POST /performance/composites/materializations`, HTTP 202 after atomic durable admission. |
| Inspect | `GET /performance/composites/materializations/{materialization_id}`, paginated member outcomes. |
| Calculate | `POST /performance/composites/twr`, after the exact generation is COMPLETE. |

Provide admitted `X-Tenant-Id`, `X-Actor-Id` and `X-Role`. With enterprise enforcement enabled,
persistable service identity must authorize both submission and member-result reads. Bearer
credentials are never persisted or replaced by a fabricated privileged identity.

OpenAPI defines the complete command. Pin the composite identity, definition version/digest,
membership revision/digest, universe-attestation version/digest, source cut, policy version,
inclusive dates, native reporting currency, fee view and positive restatement sequence. Each member
reference pins its portfolio, retained calculation UUID, input fingerprint and calculation hash.
`GROSS` and `NET_ACTUAL` are supported; `NET_MODEL_FEE` is refused before queued acceptance.

## Completion And Recovery

`materialization_id` identifies immutable financial content; `calculation_id` identifies one bounded
executor job. Exact replay preserves content and evidence. A changed command requires a new identity
and a higher sequence within the same composite/view/currency scope. Tenant-local chronology is
serialized; external identifiers reused by another tenant remain independent.

The reservation, execution and compute-job rows commit together. No job or reservation becomes
visible after failed admission. The existing compute worker owns retries, acquired-lease fencing
and attempt limits; source resolution is not request-time fan-out. Each attempt resolves at most
32 waiting members and retains earlier verified outcomes. It selects the least-inspected waiting
members first, with portfolio identity breaking ties. Durable `inspection_attempts` preserve this
ordering across restart and replacement jobs: unavailable earlier members cannot starve later ones.
An inspection count advances only with fenced, committed member progress; verified outcomes are immutable.

| State | Operator action |
| --- | --- |
| WAITING | Resolve unavailable pinned results or source availability; no survivor-only facts are released. |
| PUBLISHING | Resume immutable fact/manifest publication; do not repeat member resolution. |
| COMPLETE | Calculate or inspect the published generation. |
| BLOCKED | Correct the source or unsupported evidence through a new governed command; exact replay does not bypass refusal. |

An omitted eligible calculation reference blocks release rather than generating a return. Explicit
Manage exclusions are retained. All expected members must be verified or authoritatively excluded,
with at least one verified member, before the exact publication manifest permits COMPLETE.
If retries exhaust while evidence remains pending, submit a new calculation UUID for the same
immutable materialization. Replaying the exhausted job is not a new attempt.

For inspection, retain the first page's `revision` and pass it as `expected_revision` on later pages.
A missing or stale continuation identity returns HTTP 409
`COMPOSITE_MATERIALIZATION_PAGE_EVIDENCE_CHANGED`; restart from the first page.

## Financial And Retention Evidence

Beginning and ending assets use exact normalized Core decimals captured before the legacy TWR
FLOAT64 request projection. The member receipt retains the actual engine request, engine/precision
policy, verified linked period return, calculation digests, exact dated assets, and Core retrieval
identifiers/request-response digests. Manage membership identity is separate from Core valuation lineage. Retrieval timestamps
and request as-of dates are not claimed as source business dates.

A comparison-only tolerance of `max(abs(source_amount) × 10^-15, 10^-12)` verifies the existing
public monetary projection; composite fact money always comes from the exact source. This does
not change or certify legacy FLOAT64 TWR monetary precision. Foreign-currency asset conversion
without applied monetary evidence is refused, not inferred from requested currency or return FX.
The receipt preserves the published TWR precision and rounding policy: FLOAT64 percentage rounding
is not silently upgraded into extra digits, and DECIMAL_STRICT results remain as reported. Composite
weighting uses retained beginning assets under the existing asset-weighted methodology, not an
asset-change proxy for member returns.

Receipts survive ordinary member-execution expiry. Original fact sequences remain available for
explicit historical replay; an incomplete higher generation blocks latest selection rather than
falling back or publishing only survivors. Composite retention is distinct from compute-result TTL.
Reads revalidate command dimensions, member receipts, complete-universe outcomes and release evidence.
Malformed retained evidence returns `COMPOSITE_MATERIALIZATION_RETAINED_EVIDENCE_REFUSED` without
disclosing a usable result. Shared bootstrap refuses incompatible restored ledger columns, authority
keys, uniqueness or weakened constraints before repairing any adjacent schema; recovery requires a
reviewed migration, not guessed ownership or deletion.
PostgreSQL currency checks use ASCII codepoints, independent of database collation; accented
lookalikes are not canonical currency codes. Incompatible older ledger constraints require migration.
Original Manage wires are retained separately from normalized DTOs so lexical timestamp inputs and
producer digests can be revalidated after restart without changing legitimate source identities.
Existing fact-only clear/reseed operations refuse scopes containing materializations before any
deletion. Coordinated materialization/queue retention is not supplied by that legacy helper; use an
approved maintenance procedure rather than removing facts underneath retained progress.

## Verification

From the repository root, run `make postgres-concurrency-contracts-gate` against the documented
live proof database, followed by the required delivery gates in the [CI guide](../../quality/ci_quality_gates.md).
Registered HTTP proof and independent three-member/large-decimal examples live in
[`test_composite_materialization_api.py`](../../tests/integration/test_composite_materialization_api.py).
PostgreSQL lock, atomic rollback and restart contracts live in
[`test_postgres_composite_materialization.py`](../../tests/benchmarks/test_postgres_composite_materialization.py).
Controlled source wires and store restart are not live Manage/Core, disaster-recovery or capacity acceptance.
