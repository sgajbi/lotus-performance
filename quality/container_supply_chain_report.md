# Container Supply-Chain Evidence

Report date: 2026-10-07
Mode: PR/Main release evidence; the vulnerability gate is blocking, with unfixable base-image
advisories accepted individually and validated against the live scan.

## Current Posture

`lotus-performance` now has repo-native container supply-chain evidence for the production
`runtime` image stage:

```bash
make container-supply-chain-evidence
```

The target builds `lotus-performance:ci` from Dockerfile target `runtime` with non-secret Git SHA,
branch, build timestamp, repository URL, CI run id, and image-digest metadata fields, generates a
CycloneDX SBOM, and writes a high/critical container vulnerability report under
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

The retained bounded application evidence in
[#624](https://github.com/sgajbi/lotus-performance/issues/624#issuecomment-6041708068) covers committed
application `8292151fce69fd3b289492d8f1698561b32e3b53` plus an external FROM-only change, producing
image `sha256:0b8f61ab78a78c1c8d3438efc42e08fa862d45cc4c16ecf167362e490eaae2d2`.
Its explicit shadow provenance is not a clean source revision or evidence for pending composite
changes. Actual API/worker imports, Python 3.11.17/Expat 2.8.5 and isolated hardening passed;
four-role readiness remains unproven because no governed database-backed runtime was exercised.
The same retained HIGH/CRITICAL report still contains 44 HIGH findings across eight original Debian
OS advisory IDs, zero CRITICAL findings, and expired acceptances; native acceptance failed.
The interpreter fix does not remediate those OS packages or authorize expiry renewal.

Pinning the base does not make the final build deterministic: the existing `apt-get upgrade`
refresh and dependency resolution still depend on package repositories at build time. Bind each
final image/config, source tree, dependency inventory, SBOM and verdict report to that actual build.
The existing native SBOM command explicitly enables vulnerability analysis, so one SBOM plus one
HIGH/CRITICAL report performs two analyses. The acceptance verdict reads the retained report;
this base change does not repair scan-count orchestration or create readiness evidence.

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

The PR Merge Gate and Main Releasability Gate publish those artifacts. Main Releasability also
attests SBOM provenance through GitHub artifact attestations using
`actions/attest-build-provenance@v3`.

## Exception And Promotion Policy

### Current Reassessment And Pending Decision

Issue [#624](https://github.com/sgajbi/lotus-performance/issues/624) records the 2026-10-07
reassessment of eight acceptances that expired on 2026-10-05. The exact pre-hardening source
`8605dec396edccd99ccd4da262235cbfcf58bd7a` produced runtime image
`sha256:50f20f38afbf55f22812adede17bd67d2b6c45940e0d9677474c605604fa74dd`, Debian 13.7.
Trivy 0.71.2 and its retained actual scan database reported 44 HIGH package findings, zero CRITICAL,
eight advisory IDs and no published stable-package fixes. All eight remain present. The same-scan
acceptance gate failed on their expired records; the scan itself succeeded. Hardening privilege
boundaries does not fix these advisories or authorize renewal.

The official Debian tracker still lists bookworm/trixie as vulnerable for
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
| CVE-2025-69720 | `infocmp` is present. Its CLI parser is the affected surface; avoid untrusted terminal-description execution. Package presence remains a scanner finding. |
| CVE-2026-16742 | Libraries are present; `systemd-homed` executable/service is absent. Do not infer that a future image or mounted service has the same reachability. |
| CVE-2026-54369 | `libacl` is present. Privileged pathname/ACL callers and attacker-controlled symlinks are the relevant preconditions; keep the root volume initializer narrowly scoped. |
| CVE-2026-76642 | `mount` is present. Deny runtime privilege elevation/capabilities and external privileged mount helpers. |
| CVE-2026-78408 | `nsenter` is present. No privileged operator may join attacker-controlled cgroups through this image. |
| CVE-2026-78409 | `mount` is present. Do not authorize attacker-controlled `X-mount.subdir` paths or mount namespaces. |
| CVE-2026-78410 | `mount` is present. Deny elevated mount helpers and attacker-controlled authorized source paths. |
| CVE-2026-9538 | `perl-base` is present; the exact-image `Archive::Tar` module probe fails because that module is absent. No runtime contract invokes Perl archive parsing. |

The long-running roles retain their existing writable volumes and root filesystem behavior.
The root volume initializer retains only CHOWN, DAC_OVERRIDE and FOWNER, its read-only filesystem,
and no-new-privileges. Schema application retains its existing restricted boundary. An isolated
diagnostic's cap-drop settings are not evidence that a deployed workload uses these controls;
validate the actual rendered Compose and running container configuration.

Decision options remain pending independent review: retain the release block until supported
remediation exists, or approve narrowly matched per-advisory residual risk only after verifying
the actual controls and accountable owner. Any proposed temporary decision is bounded to seven
days from approval and must be reassessed earlier when a stable fix, package/version change,
new reachable helper/module, or weaker deployment control appears. This is a proposal, not a
renewal instruction. Repository owner `sgajbi` is a verifiable candidate for accountable release
maintenance; [#506](https://github.com/sgajbi/lotus-performance/issues/506) must resolve the owner
vocabulary and approval responsibility. No institutional approver is inferred from repository
ownership and no acceptance date is changed by this report.

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
User owner and admin/maintain/push permissions on 2026-10-08. Repository-name placeholders and
unknown principals refuse even when every other acceptance field matches. Before changing the
vocabulary, verify current repository ownership or maintainer access, document that evidence in
[#506](https://github.com/sgajbi/lotus-performance/issues/506), and review the source and acceptance
records together. CI uses the reviewed source vocabulary without requiring a privileged API token.
Repository maintenance accountability does not imply institutional risk approval or renew expiry.

## Security Tab Alignment

This slice benefits from GitHub Security features by publishing release artifacts that can be tied
to the repository's security evidence trail. Repository settings currently have secret scanning and
push protection enabled. Dependabot alerts/security updates are disabled, and CodeQL analysis still
needs a separate enablement or workflow/configuration slice.
