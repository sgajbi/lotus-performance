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

### Docker delivery

The ordinary `docker-compose.yml` leaves attribution unavailable even when the host sets the
configuration variable. Opt in with the tracked `docker-compose.composite-attribution.yml`
overlay. It delivers configuration to both true consumers, `performance-analytics` and
`performance-compute-executor`; lineage, PostgreSQL, schema and retention roles are unchanged.
The required host setting `LOTUS_COMPOSITE_ATTRIBUTION_DEPLOYMENT_FILE` names an absolute,
caller-resolved regular sealed operator file. Both containers receive that file read-only at
`/run/lotus/composite-attribution.json`, and their `LOTUS_COMPOSITE_ATTRIBUTION_DEPLOYMENT`
is fixed to that container path. `bind.create_host_path: false` prevents a missing file from
being silently replaced by an automatically created directory. Configuration must be readable
by the existing non-root runtime user; do not broaden privileges to make a mount work.

From the `lotus-performance` root, these commands render the selected model without starting
containers. The supplied deployment directory must already be absolute.

PowerShell:

```powershell
Set-Location "$env:LOTUS_WORKSPACE_ROOT/lotus-performance"
$env:LOTUS_COMPOSITE_ATTRIBUTION_DEPLOYMENT_FILE = (Resolve-Path -LiteralPath "$env:LOTUS_DEPLOYMENT_ROOT/composite-attribution.json").Path
docker compose -f docker-compose.yml -f docker-compose.composite-attribution.yml config --quiet
```

Bash:

```bash
cd "$LOTUS_WORKSPACE_ROOT/lotus-performance"
export LOTUS_COMPOSITE_ATTRIBUTION_DEPLOYMENT_FILE="$(realpath -e "$LOTUS_DEPLOYMENT_ROOT/composite-attribution.json")"
docker compose -f docker-compose.yml -f docker-compose.composite-attribution.yml config --quiet
```

An omitted or empty host setting refuses model interpolation. Rendering does not stat the host
path, prove that it is a regular readable file, or install the profile. Relative input may be
normalized by Compose; it is not operator admission. Independently verify the resolved regular
file, owner-controlled permissions and SHA256 before and after admission, retain the digest
privately, and prohibit file mutation for the runtime lifetime. A read-only container bind does
not prevent the host from replacing bytes. The existing loader refuses relative container paths,
missing files, directories and malformed configuration; actual missing-mount and process startup
proof must be collected in the separately admitted Docker lane.

The overlay also explicitly delivers `COMPOSITE_RECEIPT_VERIFIER_CONFIG_JSON` and the single
supported outbound alias `LOTUS_COMPOSITE_RECEIPT_CREDENTIAL`. They default to empty, leaving
the independent receipt verifier unavailable. If that verifier is separately admitted, an
operator supplies its existing strict JSON registration and secret through these exact host
settings; every registration must name `credential_env=LOTUS_COMPOSITE_RECEIPT_CREDENTIAL`.
Other dynamic credential names are not forwarded. Missing, empty, oversized or multiline
credentials refuse before transport. There is no host `env_file`, arbitrary environment copy,
embedded credential or signing key in the overlay. Protect rendered models: the evaluated
environment can contain the outbound secret. Retain only approved digests/redacted evidence.
Installed sealed `source_authorities` retain the existing factory precedence; forwarding receipt
settings does not replace them or add a new provider.

For governed canonical Service-Refresh, select both tracked files explicitly through its
`ComposeFiles` input. Each must be committed and match the reviewed clean checkout; an external
override or untracked file is not an admitted input. Review the exact complete evaluated model
digest, including the mount path and explicit environment. The frozen model preserves an operator
bind path, not mounted file bytes, so file custody checks above remain required before/after
admission. The overlay mounts configuration only. Any absolute financial artifact paths inside
the sealed configuration must separately resolve inside the consuming container through reviewed
delivery; a matching host filename does not make them available. The initial `sources=[]` stage
does not require a financial artifact mount. Root owns canonical model admission, refresh and
actual API/compute digest and refusal evidence; these renderer commands do not authorize refresh.

### Process-local checks

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

Docker delivery and outbound credential controls use the existing native test modules:

```text
python -m pytest tests/unit/test_docker_compose_runtime_contract.py tests/unit/adapters/test_composite_receipt_verifier.py -q --no-cov
```

Structural guards prove the fixed opt-in consumer/mount/environment boundary and representative
regressions. Native Compose model rendering, loader refusals and actual container activation are
distinct evidence; none substitutes for a READY candidate or original source qualification.

The registered tests reuse an existing synthetic retained original for software coverage, then
use supported configuration, real source-authority factory delegation, the existing worker and
a fresh-interpreter retained GET. They do not prove native live upstream provisioning. PostgreSQL
counterparts reuse the existing isolated-schema helper; they must be executed by an admitted
database proof lane and cannot be claimed from SQLite or testserver success. Runtime refresh,
native historical producer/consumer parity, actual container worker startup receipts, protected main promotion and
wiki publication remain separately reviewed gates.
