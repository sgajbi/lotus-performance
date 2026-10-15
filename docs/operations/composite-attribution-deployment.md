# Composite attribution deployment

This deployment composes the existing single-period Composite BF source, financial-purpose
verifier and original-source verification ports. The initial profile is explicitly
`CONTROLLED_SYNTHETIC_ONLY` / `SYNTHETIC_NON_CERTIFYING`. It supplies no institutional
method approval, official selection or real-source certification. Full #633 remains open.

The API lifespan and existing compute worker `run_forever` call one shared bootstrap before
admission or job claims. Worker startup emits an installation log receipt with the configuration
digest, revision, profile and qualification when configured. Local startup controls establish
ordering and refusal behavior; actual PID1/container receipts and positive-control release
qualification remain unearned.

## Deployment inputs

`LOTUS_COMPOSITE_ATTRIBUTION_DEPLOYMENT` names an operator-resolved absolute path to a sealed,
read-only UTF-8 JSON configuration. Missing configuration leaves the existing unavailable
ports unchanged. Enabled malformed, expired or conflicting configuration refuses startup.
Configuration and financial artifacts are bounded to 4 MiB. Duplicate configuration keys,
private signing keys, institutional profiles, duplicate actor/manifest/authority identities
and cross-tenant actor registrations refuse.

The runtime signs nothing. An independent deployment/source owner supplies original signed
evidence; a filesystem path, digest, COMPLETE flag or successful calculation cannot confer
financial authority. The configuration has these fields:

| Field | Contract |
| --- | --- |
| `version`, `profile`, `revision` | `v1`, `CONTROLLED_SYNTHETIC_ONLY`, immutable deployment revision. |
| `tenant_id`, `valid_until` | One allocated isolated tenant and timezone-aware current grant-snapshot expiry. Historical financial dates do not replace the current verification clock. |
| `expected_portfolio_ids` | Complete immutable population for original-source signer grants, available before BF candidate capture. |
| `principal_trust`, `producer_trust`, `purpose_trust`, `original_authority_trust` | Separately configured expected issuer, audience `lotus-performance` and bounded public Ed25519 JWKS. Reuse existing credential verification; no runtime private key. |
| `actors` | Exact subject, canonical identity, tenant, admitted runtime read/manage capabilities, portfolio scope and principal kind. Distinct subjects sharing one canonical person cannot approve each other. |
| `revoked_credential_ids` | Immutable current revocation snapshot; unknown subjects refuse. Expiry/revocation/grants remain synthetic controls, not bank IAM qualification. |
| `sources` | Exact existing CompositeAttributionRequest scope, complete expected population, absolute artifact path, SHA256 of original UTF-8 bytes, producer evidence and independent BF approval registrations. May be empty during original-source provisioning; BF then stays unavailable. Transient calculation/correction/current-selection IDs are excluded from source-scope digest; existing application controls still verify those identities. |
| `source_authorities` | Exact signed original-source registrations with kind `APPROVAL`, `PROVIDER` or `RECEIPT`. Empty registrations do not authorize any original. Manage published eligibility remains obtained through its existing resolver and separately admitted graph. |

Every signed registration contains `purpose`, `request_digest`, `result_wire`, `credential`
and `signer_subject`. Its Ed25519 credential binds issuer/audience/current expiry/not-before,
nonempty nonrevoked `jti`, configured subject/tenant, exact purpose/request digest,
`result_digest=authority_digest({"wire": result_wire})` and
`qualification=SYNTHETIC_NON_CERTIFYING`. The signer must currently hold manage capability
and the complete configured member scope. Signed `portfolio_scope_digest` binds
`authority_digest({"portfolio_ids": sorted(complete_expected_ids)})` before financial source reads.
Credentials are evidence, never request-selected
trust or grants. Keep configuration custody private; installation receipts expose only
configuration digest, revision, profile and non-certifying qualification.

## Source and financial purpose

The artifact is the existing `AttributionSourceBundle` JSON, including all original raw
bodies and exact normalized projections. The adapter owns original immutable bytes, validates
finite financial numbers and rejects duplicate keys; each read returns a fresh validated
nested projection. It never calculates or repairs group returns or imports a test factory.

The producer registration purpose is `COMPOSITE_ATTRIBUTION_SOURCE`; its request digest is
the existing request's exact financial source scope, and `result_wire` is the complete bundle's
`authority_digest`. Metadata-only admission verifies this registration before returning the
population; it does not open financial source files. The worker reads and hashes source bytes
on its first financial read, verifies the supplied bundle and four pins, and retains them through
the existing input owner. Subsequent reads reuse owned immutable bytes.

The independent approval registration purpose is `COMPOSITE_SINGLE_PERIOD_BRINSON_FACHLER`;
its request digest is the full bundle digest. Its strict `result_wire` object contains exactly
`maker_subject` and the full BF `policy_digest`. The maker must be the registered producer,
and the checker must be a separately mapped canonical user. Return the complete original
signed-registration wire in `AttributionApproval.evidence_wire`; publication rechecks the same
evidence. The existing application independently checks exact policy/window, original/vector,
all member/group economics, coverage and qualifications before publication.

The profile accepts supplied positive long-only single-period economics only. DEC-09 weighting
and actual-group-return applicability, DEC-10 fee/tax/benchmark/calendar/cash-fund treatment,
DEC-11 source authority and DEC-13 risk availability are not elected by deployment. The existing
institutional-authority refusal remains in force. Existing daily gross group-return evidence
with `NOT_PROVIDED_BY_SOURCE` revisions is not automatically a pinned pooled NET_ACTUAL BF source.

## Original-source registrations and candidate dependency

`APPROVAL` registrations verify the existing CompositeApprovalRequest, including definition,
method/eligibility binding, complete universe and original source evidence. Their result wire
contains exactly the original definition's `maker_subject`; the configured independent checker
cannot alias that maker. Only the existing economic-authority, eligibility and return-method
purposes are supported. Institutional definitions refuse.

The original approval request digest uses the command's existing `immutable_payload()`;
operational calculation attempts do not change retained financial authority. All other exact
request fields remain bound. `PROVIDER` registrations sign the existing full ProviderTrustRequest
and return its exact `registration_digest`, with `SYNTHETIC_TEST_ONLY` posture. `RECEIPT`
registrations sign the existing full VerificationRequest and complete original
CompositeEvidenceVerificationReceipt wire. Existing request/receipt hashing and synthetic
admission still apply. Qualified receipts are refused. No generic approve-all verifier exists.

A BF installer does not create a READY candidate. Manage #714/#778 must supply an actual native
definition, historical membership/decision/attestation and published approval graph; Performance
#540 owns that consumer acceptance. The additive historical consumer recognizes explicit
policy/evaluation v2 and finalization/receipt v3, with generic v1 bindings unchanged. Its repo-native
source fixture pack pins Manage's manifest SHA256
`2a0ed5df7ec2d3431d9db5d9c1983f64495d3cee96c9f369d3f2caee9d01bd99`, six source schemas, the
complete receipt and tampered/mixed vectors. Six examples derive from one retained graph and
match source raw/canonical hashes. This is static current in-process synthetic compatibility;
native upstream publication, deployed consumer admission and a READY candidate still require
their separate proof. Preserve original versions and hashes.
Retained native member TWR results then pass the existing materialization API/worker and the
existing result-candidate capture with its complete explicit vector. No direct financial SQL,
fixture restore, fixture member source or test signing helper belongs in ordinary startup.

Provisioning has two explicit sealed stages: first install original-source registrations and
the complete expected population with `sources=[]`; create the actual native original through
existing owners. Then restart into a final sealed configuration whose BF source/approval binds
that actual candidate/vector. A candidate ID must never be guessed to enable original-source
verification. The once-only installer prohibits changing configuration inside the running process.

## Startup and retained reads

Resolve all paths outside public requests. From the `lotus-performance` root, the following
read-only process-local composition check uses an already supplied deployment file. It creates
no candidate, job or financial result. Do not treat it as source qualification or worker proof.

PowerShell:

```powershell
Set-Location "$env:LOTUS_WORKSPACE_ROOT/lotus-performance"
$env:LOTUS_COMPOSITE_ATTRIBUTION_DEPLOYMENT = "$env:LOTUS_DEPLOYMENT_ROOT/composite-attribution.json"
python -c "from app.adapters.composite_attribution_bootstrap import bootstrap_composite_attribution; bootstrap_composite_attribution()"
```

Bash:

```bash
cd "$LOTUS_WORKSPACE_ROOT/lotus-performance"
export LOTUS_COMPOSITE_ATTRIBUTION_DEPLOYMENT="$LOTUS_DEPLOYMENT_ROOT/composite-attribution.json"
python -c 'from app.adapters.composite_attribution_bootstrap import bootstrap_composite_attribution; bootstrap_composite_attribution()'
```

Use one sealed configuration digest across actual API, worker and fresh retained-reader
processes. The bootstrap is once-only; repeating identical configuration reuses installation,
while changing/removing it in process refuses. A new deployment requires controlled process
restart and preserved original registrations. Do not overwrite another principal deployment
or infer compatible source from matching filenames.

Financial source reads and BF approval occur only in the existing worker path, outside write
fences. Reader startup does not read the BF source artifact or verify BF approval. Published
GET preserves no-recalculation/no-reapproval behavior even after the BF artifact/approval is
withdrawn. Captured-original source registrations and current caller grants remain necessary;
expired original authority is not repaired by rereading a different source or issuing new claims.

`app/workers/compute_executor_worker.py` invokes `bootstrap_composite_attribution` after worker
logging setup and before durable-store verification or job claims. Missing configuration emits
no installation receipt; invalid enabled configuration refuses startup before any claim.
The existing signal handling, drain behavior, executor and queues remain the owners.

Root alone admits eventual canonical-stack targeted service refresh with the sealed read-only
configuration mount. Before a positive request, bind actual image/source/engine, database/schema,
API/worker installation digests, principal grants, READY candidate/vector, source pins and
independent policy receipts. Run the prepared one-period OR17 at most eight calls, compare
every group effect at absolute `1e-12` ratio, and preserve original reread equality. This remains
controlled software evidence; real sources, corrections and downstream acceptance remain open.

## Validation and evidence limits

From the `lotus-performance` root in PowerShell or Bash, the focused local check is:

```text
python -m pytest tests/unit/adapters/test_composite_attribution_deployment_configuration.py tests/integration/test_composite_attribution_deployment.py -q --no-cov
```

The registered tests reuse an existing synthetic retained original for software coverage, then
use supported configuration, real source-authority factory delegation, the existing worker and
a fresh-interpreter retained GET. They do not prove native live upstream provisioning. PostgreSQL
counterparts reuse the existing isolated-schema helper; they must be executed by an admitted
database proof lane and cannot be claimed from SQLite or testserver success. Runtime refresh,
native historical producer/consumer parity, actual container worker startup receipts, protected main promotion and
wiki publication remain separately reviewed gates.
