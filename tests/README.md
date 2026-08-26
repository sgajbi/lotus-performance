# Tests Pack

## Purpose

This pack contains unit, integration, e2e, benchmark, docs-contract, and script tests for
`lotus-performance`.

## Audience

- engineers selecting focused proof for a change,
- reviewers checking meaningful coverage,
- agents avoiding superficial or misplaced tests.

## Test Families

| Family | Location | Use |
| --- | --- | --- |
| Unit | `unit/` | Fast behavior, model, service, script, and docs-contract proof. |
| Integration | `integration/` | API, runtime, observability, and cross-component behavior. |
| E2E | `e2e/` | Workflow journeys across supported public surfaces. |
| Benchmarks | `benchmarks/` | Query-plan and performance characterization evidence. |

## Common Commands

```bash
python -m pytest tests/unit/<area> -q
python -m pytest tests/integration/<file>.py -q
make test-unit
make test-unit-order-stability
make test-integration
make test-e2e
```

## Maintenance Notes

- Tests should prove business output, error behavior, contract truth, or operational evidence.
- Update docs-contract tests when README, wiki, or public guide truth changes.
- Keep test taxonomy in mind; do not hide important API/runtime or contract proof in uncategorized
  test files.
- Keep mutable payload fixtures function-scoped. Use the order-stability target to compare the
  collected unit-test node-id set and exercise the contribution regression surface under three
  deterministic random seeds. Threaded timeout tests must explicitly release their workers and
  avoid sub-scheduler timing margins that can make the shared executor order-dependent.
