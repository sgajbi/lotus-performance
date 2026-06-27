# Development Workflow

## Daily loop

1. branch from `main`
2. make a small truthful slice
3. run targeted validation first
4. run the lane command that matches the change risk
5. update docs when repo truth changes

## Common commands

```bash
make install
make run
make test-unit
make test-integration
make test-e2e
make repository-hygiene-gate
make check
make ci
```

## Repo-specific expectations

- preserve OpenAPI and vocabulary truth
- keep local cache, coverage, build, log, virtual-environment, and database artifacts out of Git
- treat async execution and lineage as contract behavior, not implementation detail
- keep benchmark and stateful integration language aligned to RFC-0082
- respect the docs regression pack when changing `README.md` or public guides

Targeted documentation proof:

```bash
python -m pytest tests/unit/docs/test_public_docs_contract.py -q
```

## References

- [docs/operations/development-workflow-and-ci-strategy.md](../docs/operations/development-workflow-and-ci-strategy.md)
- [Validation and CI](Validation-and-CI)
