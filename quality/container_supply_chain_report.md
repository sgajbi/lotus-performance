# Container Supply-Chain Evidence

Report date: 2026-10-16
Mode: PR/Main release evidence; the vulnerability gate is blocking, with unfixable base-image
advisories accepted individually and validated against the live scan.

## Current Posture

The [October 16 individual technical decisions](https://github.com/sgajbi/lotus-performance/issues/624#issuecomment-6208242609)
reassess the eight advisories through October 23 against signed source `5af5f3cafff55a8baf3ed42ae9033ebb0256dcdf`
and application image/index `sha256:903d0ba002dd1bc2160ab7fd9c0e44455690bf36d08c8d2ac32b9a152bbe3880`.
All 44 HIGH package findings remain present, with zero CRITICAL and no reported FixedVersion.
The later acceptance/documentation successor needs its own protected final-image CI evidence;
this assessment does not authorize production or qualify financial results.

`lotus-performance` now has repo-native container supply-chain evidence for the production
`runtime` image stage:

```bash
make container-supply-chain-evidence
```

Run the command from the repository root (on Windows, use the existing Git Bash Make setup with
`MSYS_NO_PATHCONV=1`). The target builds `lotus-performance:ci` from Dockerfile target `runtime` with non-secret Git SHA,
branch, build timestamp, repository URL, CI run id, and image-digest metadata fields, generates an
inventory-only CycloneDX SBOM, and writes one retained high/critical container vulnerability report under
`output/container-security/`. Runtime `GET /version` exposes the same support-safe metadata shape
so operators can correlate a live service to OCI labels, SBOM, vulnerability, and provenance
evidence.

Runtime image contract:

| Control | Current posture |
| --- | --- |
| Docker target | `runtime`, selected by `CONTAINER_BUILD_TARGET ?= runtime` and Compose `target: runtime`. |
| Supported base | Official Python `3.11.17-slim-trixie`, pinned to linux/amd64 child `docker.io/library/python@sha256:e529028263dbe6910a2d96f7d2b8f5266385e917fd45d286ef166977c094a51e`. This is an architecture-specific manifest, not a multi-architecture index. |
| Dependency scope | Refreshes published Debian security packages before installing `requirements.txt` and `requirements-image.txt`. The second holds packages that ship inside the image without being imported by application code (pinned `setuptools`), declared there so the build and the licence inventory read one authority rather than two that drift. `pip` and `wheel` are pinned for the build and uninstalled afterwards, so they are not distributed and not scanned. Development/test dependencies from `requirements-dev.txt` are not installed. |
| Runtime user | Creates and runs as non-root user `lotus` with UID/GID `10001`. |
| Privilege elevation | Removes shipped `/usr` setuid/setgid bits after source copy. API, lineage, compute and retention Compose roles drop all capabilities and set `no-new-privileges:true`; this does not remove vulnerable packages or approve findings. |
| Writable paths | Owns `/app/lineage_data`, `/app/artifacts`, and `/app/output`; source files are copied with `--chown=lotus:lotus`. |
| API healthcheck | Dockerfile probes `/health/live`; Compose probes `/health/ready` for the API service. |
| worker healthchecks | Compose uses `python -m app.workers.healthcheck <worker>` for lineage, compute executor, and runtime-retention worker readiness against shared durable metadata and lineage storage dependencies. |

### Pinned Base And Qualification Boundary

The base pin selects the supported official Python 3.11.17 runtime with bundled Expat 2.8.5.
Supplier provenance binds docker-library/python commit
`cede844ace77284e32c03b61ebc35cdfc945e862`, directory `3.11/slim-trixie`, to the immutable
linux/amd64 child above. A future multi-architecture build needs separately reviewed platform
manifests; it must not silently replace this pin with the supplier index or a floating tag.

Platform [#945](https://github.com/sgajbi/lotus-platform/issues/945) authorizes acquisition of
that same immutable child through `public.ecr.aws/docker/library/python`. Docker Hub and ECR
Public manifest bytes match SHA256 `e529028263dbe6910a2d96f7d2b8f5266385e917fd45d286ef166977c094a51e`,
including identical config and layer descriptors. This changes the distribution prefix only;
the official supplier, Python version and linux/amd64 content remain fixed. Manifest equivalence
is not a hosted build qualification. Unavailable acquisition fails closed; no mutable fallback
or vulnerability acceptance change is authorized by the mapping.

The admitted acquisition set is enforced before service initialization or build/scan by the
existing Platform validators at their qualified revisions: Python and PG17 use
`cd7563c52008fffee8a37b1b6c3235480823a5cd`, PG16 uses
`f12dade6f294b8df5e236f4f49c117b81bed4cd6`, and Trivy retains
`386b40e13e76e60e761c6c4068fbe7a11256ca29`. Python/PG17/PG16 require explicit original
selection before distribution requests; supplier and admitted content identities remain fixed.

| Consumer | Original supplier reference | Distribution reference |
| --- | --- | --- |
| PR/characterization PostgreSQL16 | `docker.io/library/postgres@sha256:ca0bd484cb98bf4b24eb1010e73fb3fcbd6714d240fbc1a10eea5b7dbecb641d` | `public.ecr.aws/docker/library/postgres` at that same index digest |
| Recovery PostgreSQL17 | `docker.io/library/postgres@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3` | `public.ecr.aws/docker/library/postgres` at that same index digest |
| Trivy0.71.2 scanner | `docker.io/aquasec/trivy@sha256:f5d0e600ecda7449e2a9b272805aef698631d3bb3f3a739a750de2c6819acdc9` | `ghcr.io/aquasecurity/trivy` at that same index digest |

All consumers select linux/amd64. PG16 and Trivy preserve retained baseline digest content.
PG17 is explicitly a newly pinned selection replacing mutable `postgres:17`; the historical
recovery binary digest was not recoverable, so historical equivalence is unproven. The
[published admission](https://github.com/sgajbi/lotus-platform/issues/945#issuecomment-6089758654)
binds the actual child/config digests. Final hosted acquisition, recovery and release-image
checks must qualify the new cohort; prior failed cohorts remain failed. The base supplier name
and digest use OCI provenance labels separately from `lotus.image.base.distribution`.
Scanner/base pins and acceptance behavior are preserved. The report producer acquires the actual
vulnerability DB into a unique ignored cache, captures its raw metadata and hashes, then uses that
same DB read-only with `--skip-db-update` for the one vulnerability analysis.

The retained bounded application evidence in
[#624](https://github.com/sgajbi/lotus-performance/issues/624#issuecomment-6041708068) covers committed
application `8292151fce69fd3b289492d8f1698561b32e3b53` plus an external FROM-only change, producing
image `sha256:0b8f61ab78a78c1c8d3438efc42e08fa862d45cc4c16ecf167362e490eaae2d2`.
Its explicit shadow provenance is not a clean source revision or evidence for pending composite
changes. Actual API/worker imports, Python 3.11.17/Expat 2.8.5 and isolated hardening passed;
four-role readiness was not proven by that historical diagnostic.
The same retained HIGH/CRITICAL report still contains 44 HIGH findings across eight original Debian
OS advisory IDs, zero CRITICAL findings, and expired acceptances; native acceptance failed.
The interpreter fix does not remediate those OS packages or authorize expiry renewal.

Historical October 8 clean signed source `40a5507b24233e2b35fd7f3137f3bc0ad01e21b2` produced image/index
`sha256:719a30aab0f8b004244eb76dfb5e998adbbe7e75af95d2a5c045b20e2a047045`.
The [October 8 disposition](https://github.com/sgajbi/lotus-performance/issues/624#issuecomment-6058552287)
binds its platform manifest/config, inventory-only SBOM, unfiltered report, actual scanner DB,
and successful isolated PostgreSQL-backed four-role readiness/restart/volume proof.
Actual API, lineage, compute and retention roles ran as UID/GID 10001 with CapEff=0,
NoNewPrivs=1 and no `/usr` setuid/setgid files. Initializer and schema application exited zero;
task-owned resources were removed and inventories verified empty. This is runtime evidence,
not financial source qualification or production certification.

Pinning the base does not make the final build deterministic: the existing `apt-get upgrade`
refresh and dependency resolution still depend on package repositories at build time. Bind each
final image/config, source tree, dependency inventory, SBOM and verdict report to that actual build.
Historical Main `b7de3b30dfa37fd66c027720d530d1cc18c11bbe` ran two vulnerability-enabled analyses:
CycloneDX plus HIGH/CRITICAL JSON. Its accepted Main run `38858467603` judged the retained JSON,
but did not capture a DB binary hash or metadata artifact. Do not relabel that DB as the assessed
`bf1f…` DB or present its SBOM as inventory-only. The successor producer removes the SBOM scanner
override, as supported by [Trivy 0.71.2](https://github.com/aquasecurity/trivy/blob/v0.71.2/pkg/flag/options.go#L456-L473),
and records one HIGH/CRITICAL analysis with its actual before/after DB hashes. Its own native and
hosted image proof is required; the completed b7 release is not rerun or reinterpreted.

Build identity fields:

| Runtime field | OCI label or build input | Local default |
| --- | --- | --- |
| `service_version` | `org.opencontainers.image.version` / `APP_VERSION` | `0.1.0` |
| `git_commit_sha` | `org.opencontainers.image.revision` / `APP_GIT_COMMIT_SHA` | `local` |
| `git_branch` | `org.opencontainers.image.ref.name` / `APP_GIT_BRANCH` | `local` |
| `build_timestamp` | `org.opencontainers.image.created` / `APP_BUILD_TIMESTAMP` | `local` |
| `repository_url` | `org.opencontainers.image.source` / `APP_REPOSITORY_URL` | `https://github.com/sgajbi/lotus-performance` |
| `image_digest` | `lotus.image.digest` / `APP_IMAGE_DIGEST` | `unavailable-before-push` |
| `ci_pipeline_run_id` | `lotus.ci.pipeline_run_id` / `APP_CI_PIPELINE_RUN_ID` | `local` |

The image digest cannot be known by the Dockerfile before a registry push. CI/promotion should pass
the final digest into `APP_IMAGE_DIGEST` and the release manifest when that promotion path is added;
local and pre-push CI evidence use the explicit `unavailable-before-push` placeholder.

Generated artifacts:

| Artifact | Purpose | Source control posture |
| --- | --- | --- |
| `output/container-security/lotus-performance-image-sbom.cdx.json` | CycloneDX SBOM for the production `runtime` image stage. | Ignored generated evidence; uploaded by PR/Main workflows. |
| `output/container-security/lotus-performance-image-vulnerabilities.json` | Trivy vulnerability report scoped to `HIGH,CRITICAL`, **unfiltered**, so it contains the findings the blocking gate acts on. Fixability is read from each finding's own `FixedVersion` rather than a second filtered scan, so the gate cannot be told two different things about one image. | Ignored generated evidence; uploaded by PR/Main workflows. |
| `output/container-security/lotus-performance-trivy-db-metadata.json` | Raw metadata from the actual DB used for that report: schema, UpdatedAt, NextUpdate and DownloadedAt. | Ignored generated evidence; uploaded by the existing JSON glob. |
| `output/container-security/lotus-performance-scan-provenance.json` | Actual scanner/image/source/run identity, report hash, native operation exits and equal before/after DB binary/metadata hashes. A failed producer records failure rather than success. | Ignored generated evidence; uploaded by the existing JSON glob. |

Here **unfiltered** means no advisory/package/suppression filtering within the existing
HIGH/CRITICAL policy; the severity filter and acceptance gate are unchanged. Inventory extraction,
DB download-only and vulnerability analysis are three operations, with only the last enabling
vulnerability analysis. `scripts/container_scan_evidence.py` records producer completion separately
from the acceptance verdict. Missing/malformed inputs, native failure, wrong source/run/platform
or scanner identity, and changed DB bytes fail the producer. It invalidates only its fixed prior
report/metadata/provenance outputs and uses a fresh cache; other output files are preserved.
The ignored cache remains until runner teardown or owned output cleanup. The JSON upload does not
archive the DB binary, establish replayability, invent its OCI digest or impose a new freshness
threshold. Root operates local Docker proof; focused producer tests use synthetic files and mocked
native operations. Each successor PR/Main build must qualify its own actual artifacts and gate.

The PR Merge Gate and Main Releasability Gate publish those artifacts. Main Releasability also
attests SBOM provenance through GitHub artifact attestations using
`actions/attest-build-provenance@v3`.

## Exception And Promotion Policy

### Current Reassessment And Bounded Decision

Issue [#624](https://github.com/sgajbi/lotus-performance/issues/624) retains the historical 2026-10-07
reassessment of eight acceptances that expired on 2026-10-05. The exact pre-hardening source
`8605dec396edccd99ccd4da262235cbfcf58bd7a` produced runtime image
`sha256:50f20f38afbf55f22812adede17bd67d2b6c45940e0d9677474c605604fa74dd`, Debian 13.7.
Trivy 0.71.2 and its retained actual scan database reported 44 HIGH package findings, zero CRITICAL,
eight advisory IDs and no published stable-package fixes. All eight remain present. The same-scan
acceptance gate failed on their expired records; the scan itself succeeded. Hardening privilege
boundaries does not fix these advisories or authorize renewal.

The dated October 16 official Debian tracker evidence identifies the reviewed trixie source
versions as vulnerable for
[ncurses](https://security-tracker.debian.org/tracker/CVE-2025-69720),
[systemd](https://security-tracker.debian.org/tracker/CVE-2026-16742),
[ACL](https://security-tracker.debian.org/tracker/CVE-2026-54369),
[mount hooks](https://security-tracker.debian.org/tracker/CVE-2026-76642),
[nsenter](https://security-tracker.debian.org/tracker/CVE-2026-78408),
[mount subdirectories](https://security-tracker.debian.org/tracker/CVE-2026-78409),
[bind mounts](https://security-tracker.debian.org/tracker/CVE-2026-78410), and
[Perl Archive::Tar](https://security-tracker.debian.org/tracker/CVE-2026-9538).
Testing/unstable fixes are not supported stable-image remediation. Removal simulations either
fail dependency resolution or warn about essential packages; this slice does not purge them.

| Finding | Observed reachability and residual decision |
| --- | --- |
| CVE-2025-69720 | `infocmp` remains present. Untrusted terminal-description execution is unsupported. Same-user parsing/availability exposure remains; UID/capabilities/NNP do not fix parsing or prove every input-to-helper path unreachable. |
| CVE-2026-16742 | Libraries remain present; five checked homed binary/unit paths are absent and actual PID1 commands are Python. This is not global service/executable absence. Do not introduce homed or mounted service paths under this decision. |
| CVE-2026-54369 | `libacl1` remains present. Privileged pathname/ACL and attacker-controlled symlink callers remain relevant. Restrict the fixed initializer to owned volumes and its three measured capabilities; no arbitrary privileged ACL/path operation is authorized or complete call-path absence proven. |
| CVE-2026-76642 | `mount` remains present. The four roles have CapEff=0 and NoNewPrivs=1; the initializer lacks SYS_ADMIN. External privileged mount helpers/post-hooks remain prohibited; universal absence was not measured. |
| CVE-2026-78408 | `nsenter` remains present. No privileged operator may join attacker-controlled cgroups/namespaces through this image. Join-cgroup and inherited-descriptor exploit behavior was not tested. |
| CVE-2026-78409 | `mount` remains present. Elevated attacker-controlled `X-mount.subdir` paths/namespaces are prohibited. Kernel fast-path applicability and fstab contents were not measured. |
| CVE-2026-78410 | `mount` remains present. Elevated bind helpers and attacker-controlled authorized source paths are prohibited. The scoped `/usr` regular-file inventory found no setuid/setgid files or traversal errors; it does not audit all filesystem paths or external privilege policy. |
| CVE-2026-9538 | `perl-base` remains present; default module lookup exited 2 because `Archive/Tar.pm` was absent. This does not prove absence from every possible mounted module path. Perl archive parsing remains unsupported. |

The long-running roles retain their existing writable volumes and root filesystem behavior.
The root volume initializer retains only CHOWN, DAC_OVERRIDE and FOWNER, its read-only filesystem,
and no-new-privileges. Schema application retains its existing restricted boundary. An isolated
diagnostic's cap-drop settings are not evidence that a deployed workload uses these controls;
validate the actual rendered Compose and running container configuration.

On October 16, Codex authored the
[eight individual bounded technical decisions](https://github.com/sgajbi/lotus-performance/issues/624#issuecomment-6208242609)
under the human user's standing autonomous-delivery authority and the existing policy.
Reverified repository User owner `sgajbi`, with maintainer permissions, is accountable for
maintenance. This does not assert independent human review, institutional risk approval,
production authorization, financial qualification or bank-buyable certification.

The assessed clean signed source is `5af5f3cafff55a8baf3ed42ae9033ebb0256dcdf`, tree
`be7bea5a17ecf67bfbc95d821c68d14d0e580cd9`, application image/index
`sha256:903d0ba002dd1bc2160ab7fd9c0e44455690bf36d08c8d2ac32b9a152bbe3880`.
Actual Trivy 0.71.2 used immutable
`ghcr.io/aquasecurity/trivy@sha256:f5d0e600ecda7449e2a9b272805aef698631d3bb3f3a739a750de2c6819acdc9`.
The retained unfiltered HIGH/CRITICAL report SHA256 is
`b18a8b8c969136bc1273d8ac693e95c2cc936a07115bc3ebf27a92d0851b2432`; actual frozen DB SHA256 is
`bf1f1b29d76cae9ff085d418cb4bfdb3906b6069f837abdef06558b8102dd1db`.
Supplier DB UpdatedAt is `2026-10-16T01:13:54.947090392Z`, NextUpdate
`2026-10-17T01:13:54.947090202Z`, and actual DownloadedAt `2026-10-16T03:32:44.639600526Z`.
Download time is not publication time or complete current knowledge. Both offline analyses
preserved the same DB hashes. All 44 advisory/package/version/severity/fix tuples match the
old records across eight advisories and 17 distinct packages, with zero new, absent, drifted or
duplicate tuples, zero CRITICAL and zero reported FixedVersion. The old-record native verdict
exited 1 with eight expiry refusals; scanner exit 0 is artifact generation, not gate success.

The [actual live assessment](https://github.com/sgajbi/lotus-performance/issues/624#issuecomment-6208072585)
and [independent factual review](https://github.com/sgajbi/lotus-performance/issues/624#issuecomment-6208259087)
bind the same image to four-role startup/restart, actual PID1 and exec UID/GID 10001,
CapEff=0 and NoNewPrivs=1, expected commands, retained synthetic markers and non-root
write/read/removal. API live/ready/version returned 200 with source `5af5f3c`; container/image IDs
were unchanged across restart. The fixed owned-volume initializer completed exit 0 with its
read-only rootfs, NNP and only CHOWN/DAC_OVERRIDE/FOWNER despite its inherited unhealthy
health field. Schema application completed exit 0 as configured non-root under its restricted
boundary; no live schema PID1 probe is claimed. Database plus four long-running roles were healthy.
Rendered configuration declares an internal network; actual container bindings and empty endpoint
gateways were observed, but the scoped packet has no network-inspect Internal boolean and does
not establish universal egress isolation. No ports or host binds were published. Owned temporary
containers/network/two volumes were removed and all 46 original container bindings preserved.
This synthetic restart/storage proof does not qualify graceful drain, financial processing,
scale, trace export, evaluated alerts or financial disaster recovery.

These decisions assess source `5af5f3c` and image `903d0ba`. The later acceptance/documentation
successor has another source/tree and can produce different image bytes through source copy, labels and
time-dependent package resolution. Do not substitute a circular successor SHA for the assessed
source or call image `903d0ba` its final image. Final-head protected CI must independently bind its
actual image/report and reevaluate the exact tuples; final PR/Main and applicable live evidence
remain required. The October 7/8 diagnostics and decisions above remain historical.

The eight narrowly matched decisions expire October 23, seven days after reassessment. Each
record carries its review date, decision reference, exposure, controls and removal trigger.
The gate rejects future reviews, malformed dates and periods longer than seven days, as well
as existing fixability, package/version, severity, stale-record, owner and expiry violations.
Reassess earlier on a supported stable fix, new/fixable finding, package/version/severity drift,
newly reachable helper/module or weaker role/deployment control. Hold release/promotion and
stop affected roles until a supported verified image is available; do not roll back to the
interpreter-vulnerable predecessor.
The planned fix is a supported stable base/package refresh with an exact-image report and
four-role proof; remove stale records when findings disappear.

From the `lotus-performance` repository root with the pinned Python environment, use one fresh
scan for evidence and acceptance. On Windows with the supported Git Bash Make recipe shell:

```powershell
$env:MSYS_NO_PATHCONV = "1"
make container-supply-chain-evidence CONTAINER_IMAGE=lotus-performance:reviewed-security CONTAINER_SECURITY_OUTPUT_DIR=output/container-security/reviewed-security
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python scripts/container_acceptance_gate.py --scan output/container-security/reviewed-security/lotus-performance-image-vulnerabilities.json
```

```bash
make container-supply-chain-evidence CONTAINER_IMAGE=lotus-performance:reviewed-security CONTAINER_SECURITY_OUTPUT_DIR=output/container-security/reviewed-security
python scripts/container_acceptance_gate.py --scan output/container-security/reviewed-security/lotus-performance-image-vulnerabilities.json
```

Resolve a task-owned image tag/output folder before running; preserve image/source/scanner/DB
provenance and native exits. Do not repeat the scan merely to evaluate acceptance against a
different snapshot. Issue #613 owns Windows portability improvements; no Make or CI policy changes
are made here.

The gate is promoted and blocking. The report-only phase existed to avoid turning an unknown
base-image baseline into noisy release
lane failures. Promote `make container-vulnerability-gate` to blocking when:

1. at least one PR and one main run have produced reviewed artifacts,
2. current high/critical findings are zero or explicitly accepted with owner, expiry, and
   remediation path,
3. the exception policy is recorded in this report and in the review ledger,
4. the blocking target is wired into PR Merge Gate and Main Releasability without
   `continue-on-error`.

Accepted exceptions must be narrow, time-bound, and tied to image package identity, severity,
CVE/advisory identifier, affected version, fixed version if available, and owner. Do not use a broad
scanner allowlist to hide unknown image risk.

The gate's `ACCOUNTABLE_OWNERS` vocabulary names verified GitHub principals with actual repository
accountability. Its initial member is `sgajbi`: the GitHub repository API verified this existing
User owner and admin/maintain/push permissions on 2026-10-08, reverified on 2026-10-16.
Repository-name placeholders and unknown principals refuse even when every other acceptance
field matches. Before changing the
vocabulary, verify current repository ownership or maintainer access, document that evidence in
[#506](https://github.com/sgajbi/lotus-performance/issues/506), and review the source and acceptance
records together. CI uses the reviewed source vocabulary without requiring a privileged API token.
Repository maintenance accountability does not imply institutional risk approval or renew expiry.

## Security Tab Alignment

This slice benefits from GitHub Security features by publishing release artifacts that can be tied
to the repository's security evidence trail. Repository settings currently have secret scanning and
push protection enabled. Dependabot alerts/security updates are disabled, and CodeQL analysis still
needs a separate enablement or workflow/configuration slice.
