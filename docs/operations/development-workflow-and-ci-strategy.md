# Development Workflow and CI Strategy

This repository follows the platform standard for engineering workflow, CI tiering, and merge hygiene.

Canonical standard:
- `lotus-platform/platform-standards/Development-Workflow-and-CI-Strategy-Standard.md`

## Required model
1. Branch from `main` and keep one branch per RFC/slice.
2. Use PR-first delivery (no direct commits to `main`).
3. Keep PR checks fast and meaningful (blocking).
4. Run heavier checks in scheduled/manual/mainline tiers.
5. Merge only with green required checks.
6. Always finish with `local = remote = main`.

## Repository-specific quality gates

`make check`, `make ci`, and the GitHub quality lanes enforce the repo-native quality gates. In
addition to lint, typecheck, OpenAPI, API vocabulary, no-alias, duplicate-code, architecture, and
router-thinness checks, `lotus-performance` now enforces:

```bash
make quality-observability-readiness-gate
make domain-product-validate
make quality-evaluation-gate
make quality-test-taxonomy-gate
make license-compliance-gate
make container-supply-chain-evidence
make lineage-volume-recovery-smoke
make performance-characterization
```

The observability-readiness gate fails when health/metrics endpoint, correlation propagation,
structured logging, metrics, or health/readiness implementation markers have any missing entries.
The domain-product validator keeps governed product contracts aligned with implementation truth. The
validator resolves `lotus-platform` through `LOTUS_PLATFORM_ROOT`, a sibling checkout, or the
`.lotus-platform` checkout used by GitHub Actions contract/security jobs. The quality evaluation
gate delegates to `make demo-api-certification`, which exercises deterministic demo-critical API
behavior, and to `make quality-test-taxonomy-gate`, which blocks regression below the current
API/runtime and contract/governance test breadth floors and blocks growth in uncategorized tests.
These gates must not be soft-failed with `continue-on-error`. Because local `make ci` runs that
evaluation before `docker-build`, `.dockerignore` excludes generated `output`, `lineage_data`, and
local SQLite database artifacts from the Docker build context.

License compliance is a blocking release-readiness gate. `make license-compliance-gate` validates
the repo MIT license declaration, `contracts/license-compliance-policy.v1.json`, and the generated
`quality/license_compliance_inventory.md`. After any runtime or development dependency change,
regenerate the inventory with `python scripts/license_compliance_inventory.py --write`, review new
license families, and keep review-required package exceptions owner-bound and time-bound before
release.

Container supply-chain evidence is produced in the PR Merge Gate and Main Releasability Gate after
coverage passes. `make container-supply-chain-evidence` builds `lotus-performance:ci` from the
production `runtime` Dockerfile target with non-secret Git SHA, branch, build timestamp, repository
URL, CI run id, and image-digest metadata fields, generates a CycloneDX SBOM, and writes a
high/critical Trivy vulnerability report under `output/container-security/`. The runtime target
installs only `requirements.txt`, runs as non-root user `lotus`, owns only required writable paths,
and carries Docker/Compose healthchecks for the API and worker processes. The same support-safe
metadata shape is exposed by runtime `GET /version` so operators can correlate a live service to
OCI labels, SBOM, vulnerability, and provenance evidence. The artifacts are uploaded by GitHub
Actions; Main Releasability also attests SBOM provenance. The vulnerability report is intentionally
report-only until the first PR/main baseline artifacts are reviewed. Promotion to a blocking image
vulnerability gate must use `make container-vulnerability-gate` and the exception policy in
`quality/container_supply_chain_report.md`.

`make lineage-volume-recovery-smoke` is the isolated restart-safety proof for the shared lineage
artifact volume. It creates only a generated `lotus-performance-lineage-recovery-*` Compose
project, seeds root-owned persisted evidence, requires the bounded initializer to repair ownership,
proves API and worker health as UID/GID `10001`, restarts the workloads, rechecks retained evidence,
and removes the owned containers, volume, network, and local images. PR Merge Gate feeds this job
into the required compatibility aggregate; Main Releasability repeats it on the merged SHA.

Performance characterization evidence is produced by the dedicated Performance Characterization
Evidence workflow on pull requests to `main`, pushes to `main`, weekly schedule, and manual
dispatch. The workflow provisions PostgreSQL, runs `make performance-characterization`, reruns the
PostgreSQL plan/concurrency subset with non-skipped proof required, and uploads JUnit, log, and
summary artifacts from `output/performance-characterization/`. This is an evidence lane, not a
required merge check yet, but benchmark regressions and all-skipped PostgreSQL contracts fail the
workflow instead of being soft-failed.

Broader observability maturity scoring remains report-only in
`quality/observability_readiness_inventory.md`.
