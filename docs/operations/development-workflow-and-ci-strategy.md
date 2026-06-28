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
```

The observability-readiness gate fails when health/metrics endpoint, correlation propagation,
structured logging, metrics, or health/readiness implementation markers have any missing entries.
The domain-product validator keeps governed product contracts aligned with implementation truth. The
validator resolves `lotus-platform` through `LOTUS_PLATFORM_ROOT`, a sibling checkout, or the
`.lotus-platform` checkout used by GitHub Actions contract/security jobs. The quality evaluation
gate delegates to `make demo-api-certification`, which exercises deterministic demo-critical API
behavior and must not be soft-failed with `continue-on-error`. Because local `make ci` runs that
evaluation before `docker-build`, `.dockerignore` excludes generated `output`, `lineage_data`, and
local SQLite database artifacts from the Docker build context.

Broader observability maturity scoring remains report-only in
`quality/observability_readiness_inventory.md`.
