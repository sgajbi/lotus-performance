# Composite Result Authority

The result-authority workflow records which complete captured original is selected for a
composite window and whether it is frozen or withdrawn from current use. It keeps financial
calculation, candidate capture, independent approval and selection as separate events.

The financial-purpose verifier defaults to unavailable. The signed conformance adapter emits
only `SYNTHETIC_NON_CERTIFYING`; it has no institutional activation option. Implementation and
synthetic evidence cannot approve a bank's financial policy, source population or release.
[Performance #610](https://github.com/sgajbi/lotus-performance/issues/610) remains open for its
full scope, coordinated through [Platform #923](https://github.com/sgajbi/lotus-platform/issues/923).

## Reader Decisions

| Need | Behavior |
| --- | --- |
| Calculate corrected analysis | Existing TWR and greatest-sequence behavior continues independently. |
| Preserve a calculated original | Use [candidate capture](composite_result_candidates.md). |
| Select an original | Propose an exact captured vector, obtain independent financial-purpose approval, then apply. |
| Protect a selected period | Approve and apply `FREEZE`; later candidates and ingestion remain possible. |
| Correct frozen selection | Independently approve/apply `REOPEN`, then obtain a new proposal and approval against its new revision. |
| Retrieve a historical report selection | Use `AS_REPORTED` with the exact committed decision identity. |
| Establish institutional authority | Unavailable; synthetic receipts and source/method approvals cannot supply it. |

## Operations And Identity

All paths have the `/performance/composites/result-authorities` prefix.

| Method and suffix | Result |
| --- | --- |
| `POST /proposals` | Immutable proposal, exact expected revisions and digest-bound local impact preview. |
| `POST /proposals/{proposal_id}/approvals` | Immutable independent financial-purpose approval; no pointer change. |
| `POST /proposals/{proposal_id}/apply` | One atomic decision, history append and revision compare-and-swap. |
| `GET /{scope_id}` | Snapshot-consistent selected or historical original. |

The [v1 contract](../contracts/composite-result-authority-v1.json) and
[strict wire models](../../app/models/composite_result_authority.py) define the commands.
Unknown fields, caller-asserted tenant/role/portfolio scope and duplicate targets are refused.
Multiple targets require an explicit immutable bundle identity. Commands retain their retry
identities: changed content conflicts; equivalent retries return the first retained receipt.
Committed decision replay preserves its receipt after the original approval expires, while still
requiring current access to the retained original.

Verified Ed25519 bearer credentials supply technical identity through the existing trusted
principal deployment. Current membership, revocation, capabilities and portfolio scope remain
required. The separate financial verifier checks the exact proposal, action, approval identity,
policy and canonical human maker/checker separation. Different usernames for the same person
cannot satisfy independence. Service principals cannot act as human checkers.

No source-provider, eligibility, method, calendar or monthly-cut approval grants this financial
purpose. Server-owned verifier configuration has no HTTP configuration route. Approval/apply
refuse before protected writes when financial authority is unavailable.

## Complete Vectors, Overlaps And Bundles

A scope includes trusted tenant, composite, inclusive window, return view, reporting currency and
TWR method family. Its vector binds the captured original digest/build/engine and every exact
retained command, source, outcome and publication dependency. The complete captured source
vector is revalidated on admission and replay; no authority read calculates or links returns.
Each wider window therefore needs its own captured original.

An interval fence serializes intersecting composite authority changes. Initial creation is
included, so a wider scope cannot bypass an existing frozen monthly dependency. A replacement
that changes a dependency atomically marks affected ordinary projections `STALE`; frozen
dependencies require approved reopen. The local overlap closure is bounded to 120 scopes and
each command to 120 retained windows. Exceeding a bound refuses rather than truncating impact.

An explicit bundle promises complete member closure. Every member must be included with its
expected revision; replacing or withdrawing a subset refuses. A dependent bundle cannot be
silently staled or partially replaced. Restore uses an exact previously selected original and
creates a new approval and decision; history is preserved. Withdrawal removes current financial
use while retaining original custody and any freeze protection.

The preview binds local dependency revisions. Report versions, recipients and institutional
materiality remain `UNAVAILABLE`, never assumed zero. `pending_impact_count` counts unapplied
proposals touching the scope, including proposals made obsolete by later revisions. It is an
unresolved-review indicator, not a certified material-error count or an external recipient graph.

## Temporal Reads

| Selector | Required input |
| --- | --- |
| `LATEST_APPROVED` | Default; reads the current selected revision and its decision. |
| `EXACT` | Exact `decision_id`. |
| `AS_REPORTED` | Exact `decision_id` retained by the reporting consumer. |
| `COMMITTED_TOKEN` | Exact token returned by a committed decision. |

The token identifies committed local history; it is not an access credential or arbitrary UTC
knowledge-time query. `recorded_at_utc` is a server recording timestamp, not a database commit-time
cutoff. Historical selection and current-use status appear separately. A historical original can
remain retrievable when its current projection is stale or withdrawn; consumers must enforce the
returned current-use restriction for new financial use.

## Persistence And Operations

`CompositeMetadataStore` owns six subordinate authority tables in the same installed database as
the retained materialization ledger, candidate descriptors and protected original result owner.
Proposals, approval evidence, decisions, scope-review links and revision history are append-only.
Pointers require exact next revisions and matching history; PostgreSQL statement guards reject
`TRUNCATE`, including cascading attempts. Normal runtime verification is read-only. Schema apply
belongs to the existing explicit migration owner; it does not replay or backfill financial approval.

Financial verification occurs outside write locks. The owning transaction rechecks expiry,
retained vectors, dependency preview, bundles and expected revisions. It appends decisions and
history and moves every pointer together. There is no distributed transaction or remote call
under the authority fence. Maker/apply credential and delegation lineage are retained; the existing
mandatory enterprise audit remains active for the route family.

| Failure | Operator response |
| --- | --- |
| `503 COMPOSITE_FINANCIAL_AUTHORITY_UNAVAILABLE` | Keep authority unavailable; obtain the approved integration and policy from the owning programme. |
| `409 COMPOSITE_AUTHORITY_CONFLICT` | Reload revisions/impact; obtain a new exact proposal and approval. |
| `503 COMPOSITE_RESULT_CUSTODY_REFUSED` | Stop financial use and follow reviewed recovery; do not repair by recalculating or relabeling the original. |
| `404 COMPOSITE_AUTHORITY_NOT_FOUND` | Check verified tenant and exact retained identity without disclosing foreign resources. |

## Evidence And Remaining Scope

[Policy and signed-purpose controls](../../tests/unit/services/test_composite_authority_policy.py)
exercise state and technical trust independently of a database.
[Owner storage controls](../../tests/unit/services/test_composite_authority_storage.py) and
[PostgreSQL controls](../../tests/benchmarks/test_postgres_composite_authority.py) define native
retained-original, revision, custody and concurrent transaction proof. Test source alone is not
execution evidence; frozen-source release checks, migration/crash proofs and protected-main/wiki
closure remain required. Extended owner tests cover monthly/wider overlap, complete bundles,
populated tenant isolation, rollback, independent restart, populated predecessor migration,
missing-guard refusal and abrupt death at each authority insert and commit. Registered ASGI tests
cover credential admission, default financial-purpose refusal, synthetic approval/apply/replay and
verified audit identity. These authored tests require executed evidence before being treated as
supportability proof. The synthetic conformance checkpoint executed 112 database-free cases and
the complete 62-case SQLite/PostgreSQL/registered-ASGI matrix with zero failures or skips,
including concurrent owner transactions and actual crash boundaries. Failed prior attempts and
native retirement evidence remain recorded on [issue #610](https://github.com/sgajbi/lotus-performance/issues/610).
These results do not establish production trust, institutional approval or protected-main release.

Composite-only imported history, manual financial overrides, arbitrary UTC knowledge time,
complete external report-recipient impact and institutional/GIPS activation remain unsupported.
Production issuer/grant hosting remains under
[Platform #775](https://github.com/sgajbi/lotus-platform/issues/775); institutional freeze,
correction and materiality decisions remain under Platform #923. This increment cannot close
those dependencies or full #610.
