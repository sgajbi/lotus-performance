# Validation and CI

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

## Why the gates matter here

- downstream product surfaces trust the emitted figures
- contract drift breaks gateway and operator consumers
- runtime-control surfaces are part of supportability, not optional extras
- observability-readiness drift can make an API appear healthy while losing operational evidence
- repository-hygiene drift turns local agent byproducts into source truth and makes future
  reviews noisier than necessary
- public docs are regression-tested and should stay aligned to shipped behavior

## Documentation contract proof

When a slice changes `README.md` or public guides, run:

```bash
python -m pytest tests/unit/docs/test_public_docs_contract.py -q
```

That pack protects the shipped public contract language and examples, not just formatting.

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

## References

- [docs/operations/development-workflow-and-ci-strategy.md](../docs/operations/development-workflow-and-ci-strategy.md)
- [docs/technical/runtime_topology.md](../docs/technical/runtime_topology.md)
