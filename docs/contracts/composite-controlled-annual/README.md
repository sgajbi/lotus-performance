# Controlled annual source admission

The Slice A consumer recognizes separate `CompositeControlledYearBasis:v1`,
`CompositeSourceAuthority:v4`, `CompositeDefinition:v4` and
`CompositeEligibilityFinalizationReceipt:v5` wires. January retains its existing
`CompositeSubjectEvaluationApproval:v3`. These closed types preserve all old v1–v4
products and their hashes.

The declaration is a current-issued synthetic scenario with twelve immutable
candidate registry selections and monthly policy references. It contains no
definition, finalization or financial-result digest. The source signs exact raw
bytes. The independent verifier signs the canonical digest of its complete proof,
excluding only root `content_hash` and `verifier_credential`. New self hashes omit
only root `content_hash`, preserving every nested hash. Definition business hashing
also omits its root approval and business-digest fields to avoid a signature cycle.

The complete software fixture and consumer schemas live in
[`tests/fixtures/composite_controlled_annual`](../../../tests/fixtures/composite_controlled_annual/).
The fixture is a frozen registered-API producer export with exact January membership
and universe companions. Its inner signed source bytes remain unchanged. The
manifest records producer raw identity and the consumer's JSON representation.
The fixed software keys are synthetic and non-certifying.

Year authority is INTERNAL. Core owns asset evidence and Performance owns native
member returns. Rules specify actual enrolled product applicability rather than a
future financial cut or supplied return. Required beginning-asset and return
coverage follows each month's actual candidates; ending-asset authority applies
only where declared. Provider verification receipts preserve canonical rule order,
individual intervals and duplicate requests. The finalization request revision
binds the retained January subject revision; the raw basis revision remains in its
separate immutable reference. Registry generation may follow request creation while
source reads complete, but must not follow the retained proof's final admission.
Source actual issuance is separately bounded by the original request time.

The normal Manage reader joins the separately fetched definition, membership and
universe to the full finalization graph. A same-scope separately valid basis cannot
replace the pinned definition. Pending preparation does not establish evaluated
eligibility. Membership v2 and recurring monthly v5 remain unsupported by this
Slice A consumer.

Independent year verification defaults unavailable. API lifespan and compute-worker
startup share the retained public-only installer. An operator may set
`LOTUS_COMPOSITE_CONTROLLED_ANNUAL_DEPLOYMENT` to an absolute JSON package path.
The source/deployment owners must independently admit its custody and provision its
public anchors and registered evidence; this operator-controlled software artifact
does not establish bank IAM or source issuer authority. Runtime never imports test
fixtures, holds private signing material or contacts a source registry for this lookup.

The closed `controlled-annual-deployment.v1` package requires
`profile=CONTROLLED_SYNTHETIC_ONLY`, `revision`, `tenant_id`, timezone-aware
`valid_from`/`valid_until` and one to sixteen `registrations`. Optional
`revoked_request_digests` revoke new uses of exact registered requests. Each
registration carries `request_digest`, `proof_digest`, the complete original `proof`
and a separate `anchor`. That anchor supplies independent source/verifier principal
and public-key identities, key digests and original validity intervals, configuration,
revocation and source-evidence digests. The exact retained proof binds all twelve
candidate bodies and registry selections, original raw basis, provider enrollment,
authority rules and method references. Both full fingerprints must match; unknown or
changed requests cannot select another registration. Keys carried by proofs cannot
certify themselves. Existing source signature and full-proof admission validate the
original historical times, including the original five-minute interval, without
rewriting timestamps. Current package validity and revocation still gate every use.

Packages are bounded to 4 MiB; duplicate JSON keys, nonfinite numbers, unknown fields,
cross-tenant records, duplicate request registrations and non-public key fields refuse.
Malformed or expired enabled packages fail startup. Installation is immutable for the
process: replacement/removal requires an orderly restart of the separately owned
API/worker roles. Installation metadata contains only package digest, revision,
profile and synthetic qualification. Source admission remains separate from existing
policy/method/provider trust and native financial custody.

## Tracked Docker activation

The ordinary `docker-compose.yml` passes no annual package or activation setting.
Select `docker-compose.composite-controlled-annual.yml` explicitly to deliver only
the API and compute executor a read-only operator package at the fixed container
path `/run/lotus/composite-controlled-annual.json`. The required host setting is
`LOTUS_COMPOSITE_CONTROLLED_ANNUAL_DEPLOYMENT_FILE`; the overlay refuses an omitted
setting and disables automatic host-path creation. Resolve an existing admitted
public package file to an absolute path before selection. No package, private key
or test fixture is embedded in the overlay. Base environment, volumes and dependencies
remain composed with the opt-in settings; lineage/schema/database services receive
no annual package. Other source/principal/provider configuration is separate.
Retain any other reviewed overlays required by the deployment in the same Compose
selection; append the annual overlay rather than replacing existing configuration.

From the Performance checkout, after reviewed images are available and the base
database/schema services are healthy, the runtime owner selects the two consumers.
Set `LOTUS_WORKSPACE_ROOT` to the directory holding the checkouts and set the package
file environment variable to the source/deployment owners' admitted file first.

PowerShell:

```powershell
Set-Location "$env:LOTUS_WORKSPACE_ROOT/lotus-performance"
$env:LOTUS_COMPOSITE_CONTROLLED_ANNUAL_DEPLOYMENT_FILE = (Resolve-Path -LiteralPath $env:LOTUS_COMPOSITE_CONTROLLED_ANNUAL_DEPLOYMENT_FILE).Path
docker compose -f docker-compose.yml -f docker-compose.composite-controlled-annual.yml up -d --no-deps --force-recreate performance-analytics performance-compute-executor
```

POSIX:

```bash
cd "$LOTUS_WORKSPACE_ROOT/lotus-performance"
export LOTUS_COMPOSITE_CONTROLLED_ANNUAL_DEPLOYMENT_FILE="$(python -c 'import os; from pathlib import Path; print(Path(os.environ["LOTUS_COMPOSITE_CONTROLLED_ANNUAL_DEPLOYMENT_FILE"]).resolve(strict=True))')"
docker compose -f docker-compose.yml -f docker-compose.composite-controlled-annual.yml up -d --no-deps --force-recreate performance-analytics performance-compute-executor
```

Each successful process installation emits one structured
`Composite controlled annual verification installed` log with package digest,
revision, profile and synthetic qualification. Repeated bootstrap emits no duplicate;
default-off or failed installation emits no success log. Anchors, source/proof bodies,
credentials, principals and host paths are excluded. To disable, remove the overlay
from the runtime owner's Compose selection and recreate the same consumers using
the base file. Configuration replacement/revocation likewise requires an orderly
recreation; independently re-admit the new package before selecting it. Actual
Compose model, package/image identities and live behavior require separate runtime
owner validation; host-process tests do not provide Docker acceptance.
Configuration validation failures are redacted at the bootstrap boundary so startup
tracebacks do not serialize retained Pydantic proof/credential inputs.

The native materialization reader and existing fingerprint, money, Core-snapshot,
membership and publication checks remain authoritative. This contract supplies no
ending-asset authority merely because a native receipt retains an ending value.
Existing native fact publication requests ending assets and therefore requires an
explicit source-owned ending rule; a two-rule source graph remains readable but
cannot clear that positive financial-publication prerequisite. This contract supplies no
financial values, fabricated internal calculation IDs, implicit zero months or
official activation. `UNQUALIFIED`, `UNVERIFIED` and profile-review boundaries remain.
Twelve distinct actual COMPLETE months with one unchanged actual definition hash
and policy are still required by annual analysis. Controlled source corrections,
reporting-profile approval and live cross-service qualification require later gates.

From the Performance repository root, with the pinned Python environment active,
the command is identical in PowerShell and POSIX shells:

```text
python -m pytest tests/unit/models/test_composite_controlled_annual_contract.py tests/unit/adapters/test_composite_controlled_annual_consumer.py tests/unit/services/test_composite_controlled_annual_materialization.py tests/unit/adapters/test_composite_controlled_annual_deployment.py tests/integration/test_composite_controlled_annual_deployment.py -q
```

These tests provide local software source/custody and refusal evidence. They do not
provide canonical Docker, PostgreSQL deployment, actual member-financial or bank
authority qualification.
