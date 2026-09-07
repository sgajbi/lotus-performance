# Validation and CI

Use this page to map local proof, PR proof, and main-branch releasability evidence. The goal is to
make quality measurable and repeatable, not to treat CI as a ceremonial final step.

| Current scope | Evidence posture | Next action |
| --- | --- | --- |
| `lotus-performance` local gates, PR gates, main releasability, and container supply-chain proof | Implementation-backed through repo-native `make` targets, GitHub Actions lanes, generated quality inventories, and runtime `GET /version` build identity | Run the mapped command before PR/merge; publish repo-authored wiki source after merge when this page changes |

## Lane model

`lotus-performance` follows the Lotus multi-lane validation posture:

1. `Remote Feature Lane`
2. `Pull Request Merge Gate`
3. `Main Releasability Gate`

After a PR merges to `main`, the merged-PR dispatcher creates or verifies an immutable
`main-releasability-<merge_sha>` tag and dispatches Main Releasability with the expected SHA and PR
number. The gate asserts that checkout before any other release job starts. Direct non-PR pushes do
not automatically launch Main Releasability; manual operator dispatch remains supported. The
synthetic tag identifies the immutable checkout only—automatic container build identity remains
branch `main` at the exact merged SHA, while manual dispatch retains its selected branch or tag.

## Local command mapping

- `make check`
  fast engineering proof: lint, repository hygiene, static quality gates, no-alias gate, typecheck,
  OpenAPI gate, API vocabulary gate, unit tests
- `make repository-hygiene-gate`
  tracked-source hygiene proof that local Python caches, virtual environments, coverage files,
  build outputs, logs, and local databases were not committed
- `make calculation-engine-version-gate`
  reproducibility proof that production calculation code uses the governed
  `CALCULATION_ENGINE_VERSION` token for calculation hashes instead of deployable build identity or
  legacy per-family literals
- `make clean`
  local cleanup for ignored `artifacts/`, `output/`, `lineage_data/`, SQLite/log sidecars, caches,
  coverage files, and build outputs; durable source truth under `docs/`, `contracts/`, `wiki/`, and
  `quality/` is preserved
- `make quality-observability-readiness-gate`
  static quality proof that health/metrics endpoint, correlation propagation, structured logging,
  metrics, and readiness implementation markers have no missing entries
- `make ci`
  PR-grade proof: static quality gates, migration smoke, security audit, unit, integration, e2e,
  coverage, Docker build, and container supply-chain evidence
- `make migration-apply`
  operator schema apply/verify proof: runs the shared durable metadata bootstrap against the
  configured metadata database and writes structured evidence under
  `artifacts/durable-schema-apply/`
- `make container-supply-chain-evidence`
  image release evidence: builds the production `runtime` Dockerfile target with support-safe
  Git/build metadata, installs only runtime dependencies, runs as non-root user `lotus`, writes a
  CycloneDX SBOM, and writes a high/critical Trivy vulnerability report under
  `output/container-security/`
- `make ci-local`
  local Docker-parity coverage run
- `make lineage-volume-recovery-smoke`
  isolated persisted-volume proof: seeds root-owned lineage evidence, requires bounded ownership
  repair, validates non-root API and worker health, restarts the workloads, rechecks retained
  evidence, and removes only the generated test project
- `make test-all`
  full local pytest plus coverage gate
- `make branch-coverage-baseline`
  report-only branch coverage baseline. It runs unit, integration, and e2e suites with
  `pytest --cov-branch`, writes raw JSON under `output/branch-coverage/`, and refreshes
  `quality/coverage_inventory.md` without enforcing a branch threshold
- `make quality-baseline`
  report-only baseline refresh that writes raw scanner snapshots under `output/quality-baseline/`
  and refreshes the baseline report used by the enterprise refactor evidence trail
- `make performance-characterization`
  benchmark characterization evidence path. It writes JUnit XML, log, and summary JSON artifacts
  under `output/performance-characterization/`. The Performance Characterization Evidence workflow
  runs it with a live PostgreSQL service and uploads the artifacts for PR/main/scheduled/manual
  review.

## Why the gates matter here

- downstream product surfaces trust the emitted figures
- contract drift breaks gateway and operator consumers
- runtime-control surfaces are part of supportability, not optional extras
- observability-readiness drift can make an API appear healthy while losing operational evidence
- repository-hygiene drift turns local agent byproducts into source truth and makes future
  reviews noisier than necessary
- public docs are regression-tested and should stay aligned to shipped behavior

## Quality signal map

| Signal | Local command or workflow | What it protects |
| --- | --- | --- |
| Static quality | `make check`, Static Quality Gates | lint, format, typecheck, complexity, architecture boundaries, duplicate-code hotspots, observability markers, no-alias governance |
| Reproducibility identity | `make calculation-engine-version-gate`, `make lint` | calculation hashes are governed by `CALCULATION_ENGINE_VERSION`, not `APP_VERSION`, image labels, or legacy literal tokens |
| API contract quality | `make check`, Contract Security Gates | OpenAPI quality, API vocabulary, domain data-product contracts, migration smoke, security scans |
| Runtime behavior | `make ci`, unit/integration/e2e lanes | calculation behavior, API behavior, async/runtime flows, coverage floor |
| Performance characterization | `make performance-characterization`, Performance Characterization Evidence workflow | benchmark budget posture plus live PostgreSQL query-plan and concurrency contracts, with artifact evidence under `output/performance-characterization/` |
| Container supply-chain | `make container-supply-chain-evidence`, PR/Main container evidence jobs, `GET /version` | production runtime image buildability, non-root/runtime-dependency posture, API and worker healthchecks, runtime-to-image build identity, SBOM inventory, high/critical vulnerability evidence, and main-branch SBOM provenance attestation |
| Lineage restart recovery | `make lineage-volume-recovery-smoke`, PR/Main Lineage Volume Recovery jobs | first-create or restored-volume ownership repair, UID/GID `10001` workload access, health after restart, retained artifact evidence, and isolated cleanup |
| Documentation contract | docs regression tests, wiki source check | public contract language, command accuracy, source wiki publication readiness |
| Baseline evidence | `make quality-baseline`, Quality Baseline Snapshot | before/after scorecard data for the enterprise refactor program |

## Documentation contract proof

When a slice changes `README.md` or public guides, run:

```bash
python -m pytest tests/unit/docs/test_public_docs_contract.py -q
```

That pack protects the shipped public contract language and examples, not just formatting.

When a slice changes repo-local `wiki/`, also run the governed platform wiki check before merge:

```powershell
..\lotus-platform\automation\Sync-RepoWikis.ps1 -CheckOnly -Repository lotus-performance
```

After the PR merges to `main`, publish the wiki source with:

```powershell
..\lotus-platform\automation\Sync-RepoWikis.ps1 -Publish -Repository lotus-performance
```

## Demo API certification

For demo preparation and report-only branch evidence, run:

```bash
make demo-api-certification
```

The command calls the supported demo-critical API routes, checks expected domain figures, verifies
enabled capability publication, and writes JSON evidence to
`output/demo-api-certification/latest.json`. Review the output with
[docs/guides/demo_readiness.md](https://github.com/sgajbi/lotus-performance/blob/main/docs/guides/demo_readiness.md) before presenting.

The Quality Baseline Snapshot workflow uploads this evidence as report-only CI output. It is not a
blocking readiness gate until CI-enforcement governance proves the signal is deterministic,
low-noise, policy-backed, and stable in the intended lane.

## Quality baseline evidence

For enterprise refactor planning and before/after scorecard refreshes, run:

```bash
make quality-baseline
```

The command is report-only. It refreshes `quality/baseline_report.md`, while writing raw scanner
snapshots to ignored `output/quality-baseline/`. The curated health report and scorecard remain
source documents updated by meaningful refactor slices. The Quality Baseline Snapshot workflow uses
the same target so local and GitHub evidence stay aligned.

## Branch coverage evidence

For branch coverage planning, run:

```bash
make branch-coverage-baseline
```

The command is report-only. It measures branch coverage with `pytest --cov-branch`, refreshes
`quality/coverage_inventory.md`, and keeps raw JSON under ignored `output/branch-coverage/`. It does
not replace the 99% line-coverage gate and does not promote a branch threshold until repeated
evidence, false-positive policy, remediation guidance, and lane placement are agreed.

## Performance characterization evidence

For benchmark characterization evidence, run:

```bash
make performance-characterization
```

The command writes JUnit XML, a pytest timing log, and summary JSON under
`output/performance-characterization/`. The dedicated GitHub workflow runs on pull requests to
`main`, pushes to `main`, weekly schedule, and manual dispatch. It provisions PostgreSQL, runs the
full characterization target, reruns the PostgreSQL plan/concurrency subset with non-skipped proof
required, and uploads the artifacts. The lane is evidence-producing rather than required for merge
today, but benchmark regressions and all-skipped PostgreSQL characterization fail the workflow.

## Container supply-chain evidence

For release-image evidence, run:

```bash
make container-supply-chain-evidence
```

The command builds the CI image with Git SHA, branch, build timestamp, repository URL, CI run id,
and image-digest metadata fields, creates `output/container-security/lotus-performance-image-sbom.cdx.json`,
and creates `output/container-security/lotus-performance-image-vulnerabilities.json`. Runtime
`GET /version` exposes the same support-safe metadata shape for release audit. PR Merge Gate and
Main Releasability upload those artifacts. Main Releasability also attests SBOM provenance.

`make container-vulnerability-gate` is blocking. It ran report-only until the first artifacts were
reviewed,
and promotion required every high/critical finding to be zero or explicitly accepted with owner,
expiry, advisory identity, affected version, and remediation path. The accepted set is
`quality/container_vulnerability_acceptances.v1.json`; `make container-acceptance-gate` validates
it against the live scan and refuses an acceptance that has gained an upstream fix, lost its
package match after a base image change, or passed its expiry.

## References

- [docs/operations/development-workflow-and-ci-strategy.md](https://github.com/sgajbi/lotus-performance/blob/main/docs/operations/development-workflow-and-ci-strategy.md)
- [docs/technical/runtime_topology.md](https://github.com/sgajbi/lotus-performance/blob/main/docs/technical/runtime_topology.md)
