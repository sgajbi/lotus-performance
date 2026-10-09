# Composite result candidates

An explicit candidate capture preserves the original calculated composite response,
calculation ID, retained window vector, method version, release commit and verified
creator. Ordinary `/performance/composites/twr` calls continue to calculate without
creating a candidate. Candidates are calculated analysis; approval, official
selection, freeze, reopen and replacement remain separate #610 acceptance.

| Operation | Admission | Result |
| --- | --- | --- |
| `POST /performance/composites/result-candidates` | Verified bearer principal; current membership; `operations.runtime.manage`; every retained universe member in portfolio scope | Complete READY calculation and atomic original capture |
| `GET /performance/composites/result-candidates/{candidate_id}` | Verified bearer principal; current membership; `operations.runtime.read`; every captured member still in scope | Original response and provenance, without recalculation |
| Ordinary calculated replay | Existing calculation admission | No candidate or official authority |

The POST body contains `candidate_id` and `calculation`, using the existing TWR
request with a required explicit vector of 1–120 chronological materialization IDs.
It accepts no caller-supplied response, release identity, creator or approval.
Reuse the candidate ID for a retry. Equivalent request/vector/build/method retries
also find the original candidate when executor or candidate UUIDs differ. Changed
content under an existing identity refuses with 409. The original calculation ID,
creator, timestamp and numerical response remain unchanged.

Trust is unconfigured by default. Deployment must install
`CompositePrincipalDeployment` in the application's server-owned state, binding an
issuer, Performance audience, Ed25519 JWKS and current revocation/membership/grant
ports. A gateway-only credential does not authorize Performance. Delegated grants
and portfolio scope are the intersection of the user and application grants.
Unavailable trusted evidence refuses; asserted `X-Actor-Id`, `X-Tenant-Id`, `X-Role`
and `X-Capabilities` do not override the verified principal or audit identity on
these routes. Isolated test keys and source/verifier ports certify no institution.
Financial source makers retain their original qualification; signing the candidate
creator never approves legacy source actors.

The server must have its actual forty-character release commit configured in
`APP_GIT_COMMIT_SHA`. Local/unknown provenance refuses capture. Historical reads
keep the captured build and method even after the current implementation changes.
Missing originals, mismatched digests, malformed retained scope and inconsistent
purpose/tenant/vector evidence refuse with 503, without replacing the response.

The existing `CompositeMetadataStore` transaction inserts the original response in
`analytics_async_result` under `COMPOSITE_TWR_CANDIDATE` and a nonfinancial descriptor
in `composite_result_candidates`. Both configured and actual installed database
identities must match. In-memory and cross-database capture refuse. There is no
second financial ledger, distributed transaction or financial history JSON copy.
The response digest binds canonical UTF-8 JSON, preserving every response field and
value; it is not an assertion about HTTP whitespace or transport framing.

Captured results are immutable and excluded from ordinary async retention from
birth. Database guards refuse updates, reclassification and deletion. PostgreSQL
TRUNCATE refuses when a protected original exists; descriptor TRUNCATE always
refuses. Ordinary analytic results retain their existing retention behavior.
Statement guards also protect retained member facts and publications. Runtime
schema verification performs no repair. Apply the explicit schema owner before
API/worker restart; catalog repair never reconstructs lost financial content.
Use the [durable schema inventory](../standards/durable-schema-inventory.md) and
existing backup/restore runbook. Do not drop populated custody tables to roll back.

From the `lotus-performance` repository root with its pinned Python environment:

```powershell
python scripts/durable_schema_apply.py --output-dir artifacts/durable-schema-apply
python -m pytest tests/unit/services/test_composite_result_candidates.py tests/unit/services/test_composite_principal_credentials.py tests/integration/test_composite_result_candidate_api.py
```

```bash
python scripts/durable_schema_apply.py --output-dir artifacts/durable-schema-apply
python -m pytest tests/unit/services/test_composite_result_candidates.py tests/unit/services/test_composite_principal_credentials.py tests/integration/test_composite_result_candidate_api.py
```

Set `LINEAGE_METADATA_DATABASE_URL` to a reviewed test database before importing
the API in standalone local proofs. Required PostgreSQL controls run through
`make postgres-concurrency-contracts-gate` against its explicit test database.
