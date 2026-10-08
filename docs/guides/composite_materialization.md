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

### Retained Member Currency Normalization

An optional `currency_normalization_binding` pins `CompositeFXNormalizationSource:v1`
by revision and digest. Omitting it preserves historical command identity and replay.
Adding or changing it under an existing materialization identity is a content conflict.
This increment consumes retained internal stateful TWR evidence; external or hybrid
aggregate conversion refuses with `COMPOSITE_FX_AGGREGATE_METHOD_UNAVAILABLE`.

Portfolio reference currency, source-money currency, composite native currency and
reporting currency are separate fields. A return already expressed in USD does not
make retained EUR assets or flows USD. The worker requires independently verified
source fixings and reuses the existing daily member engine to reconcile the applied
return before releasing normalized assets. Caller-supplied FX and hashes alone do
not establish source authority. Production resolver and verifier composition currently
remain unavailable; test receipts explicitly say `SYNTHETIC_TEST_ONLY` and official
activation `UNAVAILABLE`.

For a bound internal projection, the requested reporting currency may differ from
the composite's native currency in its exact admitted Manage definition. The verified
normalization source must repeat that native currency; a contradictory native label
refuses before any member facts are released and retains the full admitted population.
Without an FX binding, the historical native/report equality rule remains in force.
Registered EUR-native and GBP-native composites can report this example in USD without
altering membership, definition identity or inception metadata. Two individually
complete windows with different composite native regimes or a continuing member's
source-money currency change refuse with
`COMPOSITE_VECTOR_CURRENCY_REGIME_UNAVAILABLE`; no approved history treatment is
inferred from a reporting projection or a definition update.
Member order and admitted arrivals/departures alone do not constitute currency-regime drift.

The defined method is unhedged, direct pair, complete natural daily observations,
UTC EOD fixing and exact decimal monetary multiplication without intermediate rounding.
Beginning assets use the prior day's fixing; ending assets, EOD external flows and
management-fee amounts use the economic day's fixing. Identity conversion is explicit
and creates no invented FX retrieval. Beginning-of-day or intraday flow fixing,
triangulation, hedging and other calendars require their own defined method and refuse.
The engine retains its original return precision and fee-view policy.

Each fixing records direction (reporting units per source unit), date, original
`observed_at`, provider/product/revision, watermark/content hash and calendar binding.
The admitted UTC fixing instant and maximum observation age constrain the original
observation. `revision_available_at` is separate: it may occur later for a correction,
but cannot exceed `source_as_of_cut`. Retrieval time is neither of those timestamps.
Actual request/response fingerprints, query windows and retained raw wires must agree.
Overlapping windows may contain equal observations; conflicting rates for the same
pair/date refuse without choosing a response by order. A correction uses separately
pinned source evidence and a later restatement sequence.

Shared normalization wire custody lives once in the existing materialization source
record. Each `composite-member-source.v3` receipt retains its exact binding, original
native evidence, normalized assets/flows/fees, verifier receipt and genuine FX snapshots.
Reload reapplies independent verification and reconstructs money and returns without
refetching upstream inputs or relying on unexpired child executions. Missing verification
causes the existing retained-evidence refusal; it does not turn a stored receipt into
production authority.

For an internal calculation example, A has EUR 100 opening assets and EUR 102 ending
assets before flows, with USD/EUR 1.30 opening and 1.40 closing fixings. B has USD
200 to 210; C has USD 300 to 294. Converted opening assets are USD 630 and ending
assets USD 646.80. The independent composite return is `(646.80 - 630) / 630 = 2/75`.
An additional EUR 10 EOD external flow converts to USD 14 and makes ending assets
USD 660.80 while preserving that return. Correcting the closing fixing to 1.42 gives
USD 648.84 ending assets before flows and return `18.84/630 = 157/5250`; with the
same EUR 10 flow, its converted amount is USD 14.20 and ending assets USD 663.04.
Original and corrected receipts retain their own source pins and can be selected explicitly.

Actual management fees follow the existing signed-fee convention. With A's EUR 100
opening and EUR 102 closing valuation excluding a separately booked EUR -2 fee,
the closing fixing 1.40 translates that fee to USD -2.80. A's gross return is `32/325`
and its actual net return is `1/13`; the group's gross and actual net returns are
`2/75` and `1/45`. The opening USD 630 and closing USD 646.80 asset evidence,
flows and fee amounts are identical across views. This is actual-fee treatment, not
a model-fee schedule or an institutional fee policy.

Retained FLOAT64 return evidence keeps the original reporting projection. Six-place
percentage rounding reports A's gross return as `9.846154%`, or `0.09846154` as a
fraction. Normalization reuses the shipped engine pipeline at that retained precision;
it does not compare this published fraction to an unrounded ratio or widen an
economic mismatch tolerance. Composite weighting uses the actual retained fraction,
so rounding can affect the reported group return. Exact monetary conversion remains
separate from return precision, including for DECIMAL_STRICT calculations.

For a client explanation: the group return uses each member's opening value in the
same reporting currency. Money added at period end is reported as a flow, so it does
not appear as investment performance. A later fixing correction creates a separate
reported version; selecting the original version continues to reproduce its figures.
These examples demonstrate calculated evidence, not approved official publication.

Registered PostgreSQL controls exercise these figures, child-execution expiry, exact
replay/conflict, a separate writer and reader process, foreign-tenant read refusal and
unavailable-verifier refusal. Independent positive populations in two tenants reuse the
same composite and materialization identities while preserving tenant-specific sources,
member calculations and figures. Source ports and verification are synthetic; live
producer qualification and institutional approval remain separate obligations.

The existing explicit `materialization_ids` vector can select adjacent normalized
windows after each generation is COMPLETE. Historical Manage v1 definitions qualify
for this path only through an independently reverified retained normalization method
that specifies the existing daily member engine. Unbound v1 definitions still refuse
vector calculation. Selected windows must share return and normalization method bindings;
missing required windows and reversed selection refuse without a cumulative return.
Global restatement chronology still applies: adjacent publications use increasing
sequences, and explicit identities select each window's actual generation.

For the next day, A moves from EUR 102 to 103 with USD/EUR fixings 1.40 to 1.42;
B moves from USD 210 to 211 and C from USD 294 to 295. Opening and closing group
assets are USD 646.80 and 652.26. Its return is `5.46/646.80 = 91/10780`.
Linking the two daily returns gives `(1 + 2/75) * (1 + 91/10780) - 1 = 53/1500`.
This is evidence for the explicitly selected two-day window. Retained inception-date
metadata does not establish complete since-inception history or qualify a currency-regime change.

After Manage admission, FX source refusal retains the entire admitted member universe
with blocked or unavailable dispositions and no member financial facts. Retryable
source unavailability may subsequently pin the exact requested normalization source
while members are still pending. Already pinned sources and published economic evidence
remain immutable; a source correction requires a separate generation. Inspection exposes
the same retained dispositions without granting source authority.

For operations, inspect the queued execution and the materialization together. A
retryable resolver outage leaves `WAITING`, the admitted expected population and each
member's unavailable disposition; the existing worker retries that same job. Recovery
pins the requested source once and preserves Manage admission, rather than replacing
the universe. A malformed, missing-member or reversed fixing source leaves `BLOCKED`
with no member facts. Correct the producer evidence and submit a separately identified
generation with truthful pins; changing the original command is an identity conflict.
An unavailable configured verifier prevents release or retained replay. Restoring
qualified verification is an operator dependency, not permission to treat hashes as approval.

Executable registered HTTP/worker examples are in
[`test_composite_materialization_api.py`](../../tests/integration/test_composite_materialization_api.py):
`test_registered_fx_normalization_converts_actual_fee_without_changing_money_between_views`,
`test_registered_fx_normalization_preserves_float_return_projection_and_exact_money`,
`test_registered_fx_normalization_refuses_independently_admitted_incompatible_windows`
and `test_registered_fx_normalization_recovers_exact_pending_source_after_temporary_outage`.
They make actual stateful member requests, submit the pinned command, process the existing
worker, inspect full retained receipts, calculate the report and test replay after child expiry.
The owning PostgreSQL benchmark wrappers execute those same consumer calls against real
owned database schemas. Synthetic source/verifier composition is confined to test injection;
these examples cannot activate a production issuer.

The [complete materialization JSON example](../examples/composite-fx-materialization.v1.json)
retains one actual original command and its reported period from the registered PostgreSQL
controls. Its `request` member is the command body; the surrounding qualification and
expected-result fields are explanatory evidence. It is a historical synthetic example,
not a command whose child calculations exist in a new deployment. For a new calculation,
replace every definition, membership, attestation, member calculation and normalization
pin with the exact admitted producer revision; do not edit only the visible FX rate.

The client sequence is:

1. Submit `request` to `POST /performance/composites/materializations` with admitted
   `X-Tenant-Id`, `X-Actor-Id` and `X-Role`. HTTP 202 returns `calculation_id`,
   `materialization_id`, `poll_path` and `result_path`; it does not assert that calculation
   or source verification has completed.
2. Poll `result_path`. Require `COMPLETE`, `expected_count=3`, `ready_count=3` and
   the complete A/B/C population for this example. `WAITING` and `BLOCKED` do not
   permit reporting a successfully normalized composite return.
3. Call `POST /performance/composites/twr` with the command's `composite_id`,
   `period_start`, `period_end`, `reporting_currency`, `return_view` and explicitly
   selected `restatement_sequence`. This example yields USD 630 opening assets,
   USD 646.80 closing assets and a reported decimal-fraction return near `2/75`.
   The JSON retains the actual public output precision.
4. For an adjacent-window report, supply ordered `materialization_ids` for every
   required completed window instead of inferring latest or a common sequence.
   Preserve the returned selection manifest with the report. An original fixing
   generation remains selectable after a separately pinned correction.

For external or hybrid callers, this increment returns
`COMPOSITE_FX_AGGREGATE_METHOD_UNAVAILABLE`; it does not normalize an aggregate
return by revaluing terminal wealth. Use the separately documented external-fact method
and its native-currency supported contract until an aggregate FX method is defined and admitted.

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

## Versioned External And Hybrid Source Admission

Definition product version selects the consumer: historical `CompositeDefinition:v1` wires keep
their existing hash, timestamp and internal calculation behavior. `CompositeDefinition:v2` carries
an immutable economic authority profile. Policy text does not select a version. The consumer
independently verifies profile HP, pre-approval definition HB and final approval-bearing HC;
nested source/registry/evidence digests remain hashed inputs. Duplicate raw v2 JSON keys, floats,
unknown fields, contradictory identities, wrong source kinds, overlapping authority and missing
required intervals refuse. Adjacent authority changes are distinct from overlap: a materialization
that spans a change currently requires explicitly split periods and their correctly scoped returns.

Each required member/fact has one selected economic provider. Publishing through Manage does not
make Manage the return or asset authority. Returns, beginning assets and explicitly selected
ending assets may have different providers; internal returns require Performance and internal
assets require Core. When ending assets are selected, coverage must be complete across every
member and the profile horizon. Without that selection, ending assets stay null even if an
unselected wire contains a value. The current TWR response includes asset reporting and returns
HTTP 422 `COMPOSITE_ENDING_ASSETS_UNAVAILABLE` for that generation.

The separate `CompositeExternalMemberFacts:v1` observation model records tenant/provider, source
member identity, revision/watermark/cut, period, reporting currency, actual fee view, method binding,
decimal-fraction returns and dated asset amounts. Dated positive/negative cash flows are retained
with their explicit timing; supplied period returns are not reconstructed from ending wealth.
External returns have no fabricated internal calculation UUID. Hybrid internal inputs reuse the
genuine retained `CompositeMemberSourceEvidence` receipt and its Core window/snapshot proof.
For that retained-evidence selection, contract version is `composite-member-source.v1`, revision
is the genuine calculation UUID, digest is the recomputed receipt fingerprint, watermark pins the
actual input fingerprint, and source cut pins the Manage cut. It is not a new published product,
nor does a Manage cut claim to be a Core business watermark.
External observation cuts instead match each fact's selected provider cut exactly. They may differ
from the pinned Manage membership/universe cut and from one another. A summary
`source_authority_identity` identifies a selected component; it does not assign every fact to that
provider. The v2 receipt retains selection IDs and all independently selected observation wires,
plus the genuine internal receipt where applicable. Wholly internal v2 profiles without an ending
selection use this same receipt path with no external observations and retain the real calculation
UUID; their ending assets remain null.

Provider registration, authority-profile approval, evaluated eligibility approval and method/calendar
approval use separate server-composed verification ports. Their production defaults are unavailable;
request bodies and environment flags cannot choose a synthetic resolver. The recognized
`INSTITUTIONAL_ATTESTATION_REFERENCE` envelope preserves the agreed immutable issuer/artifact
reference and HP/HB/HC construction, but refuses admission until a qualified artifact/key verifier
exists. A digest or reference never grants trust. Owning tests inject exact synthetic records only;
their provider receipts explicitly carry `qualification=SYNTHETIC_TEST_ONLY`. COMPLETE denotes
controlled fact publication, not institutional or live-source activation.

The default adapter resolves the unchanged frozen producer pack's
`SyntheticMonthlyMemberFacts:v1` wire through its exact admitted profile and independently verified
method and actual command. The wire supplies member returns and beginning assets only: ending
assets remain null, no cash-flow fields are invented, and the asset-reporting TWR route refuses
with HTTP 422. The existing engine contribution primitive proves the original weighted return
1/60 and corrected return 49/3050. Missing admission, wrong fee view, invalid calendar dates and
changed wire identity fail closed. The adapter also resolves the separate explicit
`CompositeExternalMemberFacts:v1` observation contract. The explicit observation/profile example in
[`tests/composite_authority_helpers.py`](../../tests/composite_authority_helpers.py) includes flows
after the period return: A beginning100/return10%/ending160/flow+50;
B300/-2%/274/-20; C200/3%/206/0. The independent weighted return is 1/60 and ending wealth640,
not the inferred610. Correction B beginning310/ending283.8 yields return49/3050 and ending649.8;
the original generation remains retrievable. These synthetic observations are not institution policy.

The complete [external observation JSON example](../examples/composite-external-member-facts.v1.json)
is the exact canonical wire used by the original controlled adapter proof. A producer must retain
the immutable profile/definition and pin that wire's digest, revision, watermark and provider cut
in each applicable selection. Posting an observation to the calculation API is not supported;
the registered materialization command pins the approved Manage definition, membership and universe.
The existing command and inspection routes stay unchanged. Independent original/correction/replay,
ending-provider, internal and hybrid client calls are executable examples in
[`test_composite_provider_materialization_api.py`](../../tests/integration/test_composite_provider_materialization_api.py).

### Durable Upgrade And Rollback Boundary

The existing owner-invoked durable schema apply upgrades the fact table with nullable ending assets
and internal calculation identity plus explicit external source identity JSON. Internal facts retain
a database constraint requiring genuine calculation identity and ending assets. SQLite replacement
preserves populated rows, foreign keys, indexes and checks in the owner's transaction; PostgreSQL
uses bounded column/constraint alterations. Runtime readers still verify schema and refuse drift;
they do not run this migration.

From the `lotus-performance` repository root, after selecting the repository's pinned Python environment:

```powershell
make shell-check
python scripts/durable_schema_apply.py --database-url <approved-isolated-database-url>
```

```bash
python scripts/durable_schema_apply.py --database-url '<approved-isolated-database-url>'
```

Do not run an old reader against stored v2 receipts or provider facts. Disable new v2 admission
before rollback; retain a v2-capable reader until a separately proven restore/forward recovery
reconciles all new rows. Dropping provider identities or replacing null assets with invented amounts
is not rollback. Bounded isolated PostgreSQL owner-migration tests preserve populated internal
rows, foreign keys, indexes and checks; reject weakened guards; and prove transactional rollback
on an invalid populated partial schema. These storage fixtures are not live calculation evidence.

Registered HTTP/default-worker PostgreSQL proofs run original, correction, retained read/replay,
transient outage and recovery in distinct fresh Python processes for both frozen and explicit
observations. Exact replay returns 202 and conflicting replay 409 without changing either receipt.
A retryable observation outage leaves all members WAITING with no published facts; exhaustion
fails the executor job. Recovery uses a new executor UUID for the same immutable materialization
generation. This proves fresh-interpreter behavior, not an operating-system or deployed-service
restart. Existing PostgreSQL admission, publication, lineage-storage lease-fence and disjoint
compute-claim controls separately prove their bounded concurrency behavior; lineage lease tests
do not certify composite executor lease expiry. None of these tests certifies deployment rollback or actual
Manage publication.

Remaining #607 acceptance includes qualified external/internal/hybrid inputs, actual #714 universe,
selected independently evaluated/approved #778 content, approved return method/calendar/fee/currency/
precision, live joined producer/runtime qualification, deployment recovery and capacity acceptance.
Controlled registered/default-worker PostgreSQL replay, correction and recovery proofs satisfy
only those bounded test nodes; synthetic verification ports are not bank approval. #607 remains open.

## Completion And Recovery

### Explicit Retained Window Replay

The existing `POST /performance/composites/twr` request accepts an optional chronological
`materialization_ids` vector. It is mutually exclusive with `restatement_sequence`. Omitted vector
and single-sequence requests retain their existing selection behavior. Each selected window must
be COMPLETE, belong to the admitted tenant and requested composite/fee/currency, and cover the
requested interval contiguously without overlap. The same exact retained method/calendar binding
and policy must cover every window; different opaque method digests are refused. Window-specific
definition, membership, eligibility and source hashes remain independently retained and verified.
An omitted currency comes from the first selected immutable window, not a current live definition.

This is explicit historical calculated replay, including when a newer correction is pending or
complete. It does not select latest-approved or official authority and does not freeze edits.
PostgreSQL reads every selected receipt, publication and fact check under REPEATABLE READ; SQLite
starts an explicit read transaction. Modified or mixed retained manifests fail existing integrity
checks. The numerical engine remains unchanged.

The interactive request has a new explicit maximum of **120 retained windows**: this bounds the
number of receipt/publication validations per call and supports ten years of monthly evidence.
It is a request resource bound, not a limit on retained history or an institutional policy.
Empty, duplicate or larger vectors are refused with HTTP 422; no history is silently truncated.
Missing required windows or selected incomplete receipts return HTTP 409
`REQUIRED_PERIOD_UNAVAILABLE` with no financial payload. This represents an unavailable return;
it is an absent refused payload, not a returned numeric zero or a successful null-valued result.
Overlapping/out-of-order windows and incompatible scope/method are refused with HTTP 422.
Foreign or absent tenant-owned identities return HTTP 404. Ending-asset authority is still required
for this asset-reporting route.

Successful vector responses include `selection_manifest`: ordered IDs, per-window sequences,
definition/membership/attestation hashes, source cuts, exact method binding and retained-receipt
fingerprints. Its calculation fingerprint binds tenant, exact request, full vector, engine version
and result using the existing reproducibility helper. No singular sequence is claimed for multiple
generations. This returned manifest is not a durably captured calculation result; the owned durable
result/official-vector/approval/freeze obligations under #610 remain open.

The executable examples are `test_registered_external_month_matches_independent_or01`,
`test_registered_external_two_month_chain_matches_independent_or02`, and
`test_registered_external_missing_eligible_member_month_cannot_publish_survivor_chain` in
[`test_composite_provider_materialization_api.py`](../../tests/integration/test_composite_provider_materialization_api.py).
They bind the exact inputs and expected values from the Platform oracle source
`lotus-platform/docs/composite-performance/source/05_composite_numerical_oracles.json`, SHA-256
`faf40e73c552d117ac466c711ac430551f5e20d8907ec20069bc2f9493316f61`.
OR-01 weights 0.25/0.75 and contributions 0.025/-0.015 give decimal return 0.01; OR-02
geometrically links 0.01 and 0.02 to 0.0302. OR-18 deliberately omits one eligible member's middle
month: that window cannot publish partial facts, and the three-window request refuses instead of
linking the surviving months to 0.0302. Numeric tolerance is 1e-12; categorical and identity checks
are exact. All producer and approval fixtures are explicitly synthetic.

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

### Published Eligibility Evidence

Manage's staged lifecycle uses `CompositeSubjectEvaluationApproval:v1` as the existing eligibility
binding. For this product, Performance calls the configured read-only
`POST /api/v1/rebalance/composites/{composite_id}/definitions/{definition_version}/eligibility-evidence/resolve`
with that exact product/version/revision/digest and admitted tenant headers. It does not infer a
subject revision from a correlation ID or select the latest approval. Missing or staged-only
publication refuses admission; transient resolver failures remain retryable.
Resolver retries accept finite numeric or valid HTTP-date `Retry-After` values. Malformed
and nonfinite values use the configured bounded backoff; they cannot become a nonfinite sleep.
The default worker carries the job's retained service identity and capability headers to both
canonical reads and the resolver, preserving its original correlation. Header names are normalized
by case; duplicate/conflicting authority refuses before I/O. The selected tenant, actor and role
cannot be overwritten, unrelated headers are discarded, and absent capabilities are not invented.

The producer resolver joins its retained published graph before returning
`CompositeEligibilityFinalizationReceipt:v1`. Performance also reads and digest-checks the canonical
definition, membership and universe. It requires the same final definition, exact approval binding,
full member identity map, membership/universe revisions and hashes, source cut, source products and
evaluation decisions. The receipt and joined pins remain in existing retained source JSON; replay
reapplies the guards without rewriting raw decimal/timestamp strings or nested hashes. Definition
HP/HB/HC exclusions and the older membership/universe recursive hash convention remain unchanged.

Publication lookup does not verify an issuer. A separately composed verifier must return typed
purpose receipts and independently configured issuer/artifact expectations. Boolean results, staged
approvals, and receipt bodies without that configuration refuse. Production verification remains
unavailable; owning test verification is explicitly synthetic and non-certifying. Nested approval
`NOT_PUBLISHED`, receipt `UNVERIFIED` and official activation `UNAVAILABLE` labels remain intact.
The staged fixture's `SyntheticAssets` and `SyntheticReturns` are not supported financial inputs.

From this repository root with its pinned Python environment, run
`python -m pytest tests/unit/models/test_composite_eligibility_evidence.py tests/unit/adapters/test_manage_composite_eligibility_evidence.py tests/unit/services/test_http_resilience.py -q`.
This source/transport proof does not establish deployed cross-service custody, qualified production
approval or PostgreSQL acceptance of the new joined path.

From the repository root, run `make postgres-concurrency-contracts-gate` against the documented
live proof database, followed by the required delivery gates in the [CI guide](../../quality/ci_quality_gates.md).
Registered HTTP proof and independent three-member/large-decimal examples live in
[`test_composite_materialization_api.py`](../../tests/integration/test_composite_materialization_api.py).
PostgreSQL lock, atomic rollback and restart contracts live in
[`test_postgres_composite_materialization.py`](../../tests/benchmarks/test_postgres_composite_materialization.py).
Controlled source wires and store restart are not live Manage/Core, disaster-recovery or capacity acceptance.
