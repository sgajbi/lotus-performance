# Container Supply-Chain Evidence

Report date: 2026-07-10
Mode: PR/Main release evidence; vulnerability report is report-only until the baseline is accepted.

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
| Dependency scope | Installs `requirements.txt` only; development/test dependencies from `requirements-dev.txt` are not installed in the runtime image. |
| Runtime user | Creates and runs as non-root user `lotus` with UID/GID `10001`. |
| Writable paths | Owns `/app/lineage_data`, `/app/artifacts`, and `/app/output`; source files are copied with `--chown=lotus:lotus`. |
| API healthcheck | Dockerfile probes `/health/live`; Compose probes `/health/ready` for the API service. |
| worker healthchecks | Compose uses `python -m app.workers.healthcheck <worker>` for lineage, compute executor, and runtime-retention worker readiness against shared durable metadata and lineage storage dependencies. |

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
| `output/container-security/lotus-performance-image-vulnerabilities.json` | Trivy vulnerability report scoped to `HIGH,CRITICAL` and ignoring unfixed findings during the report-only baseline phase. | Ignored generated evidence; uploaded by PR/Main workflows. |

The PR Merge Gate and Main Releasability Gate publish those artifacts. Main Releasability also
attests SBOM provenance through GitHub artifact attestations using
`actions/attest-build-provenance@v3`.

## Exception And Promotion Policy

The report-only phase exists to avoid turning an unknown base-image baseline into noisy release
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

## Security Tab Alignment

This slice benefits from GitHub Security features by publishing release artifacts that can be tied
to the repository's security evidence trail. Repository settings currently have secret scanning and
push protection enabled. Dependabot alerts/security updates are disabled, and CodeQL analysis still
needs a separate enablement or workflow/configuration slice.
