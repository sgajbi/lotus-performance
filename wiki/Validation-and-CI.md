# Validation and CI

## Lane model

`lotus-performance` follows the Lotus multi-lane validation posture:

1. `Remote Feature Lane`
2. `Pull Request Merge Gate`
3. `Main Releasability Gate`

## Local command mapping

- `make check`
  fast engineering proof: lint, no-alias gate, typecheck, OpenAPI gate, API vocabulary gate, unit tests
- `make ci`
  PR-grade proof: migration smoke, security audit, unit, integration, e2e, coverage, Docker build
- `make ci-local`
  local Docker-parity coverage run
- `make test-all`
  full local pytest plus coverage gate

## Why the gates matter here

- downstream product surfaces trust the emitted figures
- contract drift breaks gateway and operator consumers
- runtime-control surfaces are part of supportability, not optional extras
- public docs are regression-tested and should stay aligned to shipped behavior

## References

- [docs/operations/development-workflow-and-ci-strategy.md](../docs/operations/development-workflow-and-ci-strategy.md)
- [docs/technical/runtime_topology.md](../docs/technical/runtime_topology.md)
