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
make container-supply-chain-evidence
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

Container supply-chain evidence is produced in the PR Merge Gate and Main Releasability Gate after
coverage passes. `make container-supply-chain-evidence` builds `lotus-performance:ci`, generates a
CycloneDX SBOM, and writes a high/critical Trivy vulnerability report under
`output/container-security/`. The artifacts are uploaded by GitHub Actions; Main Releasability also
attests SBOM provenance. The vulnerability report is intentionally report-only until the first
PR/main baseline artifacts are reviewed. Promotion to a blocking image vulnerability gate must use
`make container-vulnerability-gate` and the exception policy in
`quality/container_supply_chain_report.md`.

Broader observability maturity scoring remains report-only in
`quality/observability_readiness_inventory.md`.
