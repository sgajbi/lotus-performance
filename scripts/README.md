# Scripts Pack

## Purpose

This pack contains repo-native validators, inventories, certification utilities, migration checks,
and operational automation used by Make targets and CI lanes.

## Audience

- engineers running local proof,
- CI maintainers wiring repository-native targets,
- agents choosing the smallest validation command for a slice.

## Command Families

| Family | Examples | Primary entrypoint |
| --- | --- | --- |
| API and contract gates | `openapi_quality_gate.py`, `api_vocabulary_inventory.py`, `validate_domain_data_product_contracts.py` | `make check` |
| Quality inventories | `python_complexity_inventory.py`, `python_duplicate_code_inventory.py`, `python_observability_readiness_inventory.py` | `make quality-baseline` or focused quality targets |
| Runtime operations | `durable_recovery_drill.py`, `runtime_retention_cleanup.py`, `validate_lineage_volume_recovery.py` | named Make smoke targets |
| Demo and certification | `demo_api_certification.py`, endpoint certification helpers | `make demo-api-certification` |
| Hygiene and safety | `repository_hygiene_gate.py`, `clean_generated_artifacts.py` | `make lint`, `make clean` |
| Test determinism | `pytest_collection_stability.py` | `make test-unit-order-stability` |

## Maintenance Notes

- Prefer adding threshold arguments to an existing script before creating a parallel scanner.
- Keep blocking modes worktree-clean; report generation should be explicit.
- Scripts used by Make targets are part of the CI contract and need focused tests under
  `tests/unit/scripts/`.
- Dependency license generation assumes exact direct-dependency pins and fails when the active
  environment does not match them; never refresh compliance evidence from a drifting environment.
  Keep overlapping `pyproject.toml` declarations and `poetry.lock` aligned to the same exact pins.
