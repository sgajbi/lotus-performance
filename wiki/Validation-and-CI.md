# Validation and CI

Use this page to map local proof, PR proof, and main-branch releasability evidence. The goal is to
make quality measurable and repeatable, not to treat CI as a ceremonial final step.

## Lane model

`lotus-performance` follows the Lotus multi-lane validation posture:

1. `Remote Feature Lane`
2. `Pull Request Merge Gate`
3. `Main Releasability Gate`

## Local command mapping

- `make check`
  fast engineering proof: lint, repository hygiene, static quality gates, no-alias gate, typecheck,
  OpenAPI gate, API vocabulary gate, unit tests
- `make repository-hygiene-gate`
  tracked-source hygiene proof that local Python caches, virtual environments, coverage files,
  build outputs, logs, and local databases were not committed
- `make quality-observability-readiness-gate`
  static quality proof that health/metrics endpoint, correlation propagation, structured logging,
  metrics, and readiness implementation markers have no missing entries
- `make ci`
  PR-grade proof: static quality gates, migration smoke, security audit, unit, integration, e2e,
  coverage, Docker build
- `make ci-local`
  local Docker-parity coverage run
- `make test-all`
  full local pytest plus coverage gate
- `make branch-coverage-baseline`
  report-only branch coverage baseline. It runs unit, integration, and e2e suites with
  `pytest --cov-branch`, writes raw JSON under `output/branch-coverage/`, and refreshes
  `quality/coverage_inventory.md` without enforcing a branch threshold
- `make quality-baseline`
  report-only baseline refresh that writes raw scanner snapshots under `output/quality-baseline/`
  and refreshes the baseline report used by the enterprise refactor evidence trail

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
| API contract quality | `make check`, Contract Security Gates | OpenAPI quality, API vocabulary, domain data-product contracts, migration smoke, security scans |
| Runtime behavior | `make ci`, unit/integration/e2e lanes | calculation behavior, API behavior, async/runtime flows, coverage floor |
| Docker parity | `make ci`, `make ci-local`, Validate Docker Build | image buildability and local-runtime parity for release confidence |
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
[docs/guides/demo_readiness.md](../docs/guides/demo_readiness.md) before presenting.

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

## References

- [docs/operations/development-workflow-and-ci-strategy.md](../docs/operations/development-workflow-and-ci-strategy.md)
- [docs/technical/runtime_topology.md](../docs/technical/runtime_topology.md)
