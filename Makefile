.PHONY: install install-ci verify-dependencies check check-all test test-unit test-integration test-e2e test-all test-coverage coverage-gate ci ci-local ci-local-docker ci-local-docker-down typecheck lint quality-complexity-gate quality-architecture-gate quality-router-thinness-gate quality-duplicate-code-gate python-security-gate github-action-runtime-guard monetary-float-guard format clean run check-deps security-audit openapi-gate api-vocabulary-gate no-alias-gate domain-product-validate migration-smoke migration-apply recovery-drill-smoke runtime-retention-smoke performance-characterization performance-characterization-postgres pre-commit docker-up docker-down docker-build

install:
	pip install -r requirements.txt
	pip install -r requirements-dev.txt
	pip install pre-commit
	pre-commit install

install-ci:
	pip install -r requirements.txt
	pip install -r requirements-dev.txt

verify-dependencies:
	python scripts/dependency_health_check.py --skip-audit --skip-outdated --requirement requirements.txt --requirement requirements-dev.txt

pre-commit:
	pre-commit run --all-files

check: lint quality-complexity-gate quality-architecture-gate quality-router-thinness-gate quality-duplicate-code-gate no-alias-gate typecheck openapi-gate api-vocabulary-gate domain-product-validate python-security-gate test

test-coverage:
	COVERAGE_FILE=.coverage.unit python -m pytest tests/unit --cov=app --cov=engine --cov=core --cov=adapters --cov-report=
	COVERAGE_FILE=.coverage.integration python -m pytest tests/integration --cov=app --cov=engine --cov=core --cov=adapters --cov-report=
	COVERAGE_FILE=.coverage.e2e python -m pytest tests/e2e --cov=app --cov=engine --cov=core --cov=adapters --cov-report=
	python -m coverage combine .coverage.unit .coverage.integration .coverage.e2e
	python -m coverage report --fail-under=99

coverage-gate: test-coverage

ci: lint quality-complexity-gate quality-architecture-gate quality-router-thinness-gate quality-duplicate-code-gate no-alias-gate typecheck openapi-gate api-vocabulary-gate domain-product-validate migration-smoke security-audit python-security-gate test-unit test-integration test-e2e coverage-gate docker-build

test:
	$(MAKE) test-unit

test-unit:
	python -m pytest tests/unit

test-integration:
	python -m pytest tests/integration

test-e2e:
	python -m pytest tests/e2e

test-all:
	python -m pytest --cov=app --cov=engine --cov=core --cov=adapters --cov-report=term-missing --cov-fail-under=99

ci-local: lint check-deps domain-product-validate
	python -m pip check
	COVERAGE_FILE=.coverage.unit python -m pytest tests/unit --cov=app --cov=engine --cov=core --cov=adapters --cov-report=
	COVERAGE_FILE=.coverage.integration python -m pytest tests/integration --cov=app --cov=engine --cov=core --cov=adapters --cov-report=
	COVERAGE_FILE=.coverage.e2e python -m pytest tests/e2e --cov=app --cov=engine --cov=core --cov=adapters --cov-report=
	python -m coverage combine .coverage.unit .coverage.integration .coverage.e2e
	python -m coverage report --fail-under=99
	$(MAKE) typecheck

ci-local-docker:
	docker compose -f docker-compose.ci-local.yml up --build --abort-on-container-exit --exit-code-from ci-local ci-local

ci-local-docker-down:
	docker compose -f docker-compose.ci-local.yml down -v --remove-orphans

check-all: lint typecheck test-all

typecheck:
	python -m mypy --config-file mypy.ini

openapi-gate:
	python scripts/openapi_quality_gate.py

api-vocabulary-gate:
	python scripts/api_vocabulary_inventory.py --validate-only

no-alias-gate:
	python scripts/no_alias_contract_guard.py

domain-product-validate:
	python scripts/validate_domain_data_product_contracts.py

migration-smoke:
	python scripts/migration_contract_check.py --mode durable-schema
	python scripts/durable_schema_inventory_check.py
	python scripts/durable_recovery_runbook_check.py
	$(MAKE) recovery-drill-smoke

recovery-drill-smoke:
	python scripts/durable_recovery_drill.py --output-dir artifacts/durable-recovery-drill --retention-limit 30 --retention-max-age-days 90 --operator-id migration-smoke --backup-identifier migration-smoke-local

runtime-retention-smoke:
	python scripts/runtime_retention_cleanup.py --scheduled --output-dir artifacts/runtime-retention-cleanup --retention-limit 30 --retention-max-age-days 90

performance-characterization:
	python -m pytest tests/benchmarks -q

performance-characterization-postgres:
	docker compose up -d performance-lineage-db
	python -m pytest tests/benchmarks/test_postgres_query_plans.py tests/benchmarks/test_postgres_concurrency_contracts.py -q

migration-apply:
	python scripts/migration_contract_check.py --mode durable-schema

lint:
	python -m ruff check .
	python -m ruff format --check .
	$(MAKE) github-action-runtime-guard
	$(MAKE) monetary-float-guard

quality-complexity-gate:
	python scripts/python_complexity_inventory.py --limit 25 --max-cc 8 --max-high-complexity 0

quality-architecture-gate:
	python scripts/python_architecture_boundary_inventory.py --limit 40 --max-findings 0

quality-router-thinness-gate:
	python scripts/python_router_middleware_thinness_inventory.py --threshold 80 --limit 50 --max-findings 0

quality-duplicate-code-gate:
	python scripts/python_duplicate_code_inventory.py --min-lines 12 --limit 40 --max-groups 8

python-security-gate:
	python scripts/python_security_inventory.py --limit 30 --max-high 0 --max-medium 0 --max-low 0

github-action-runtime-guard:
	python scripts/github_action_runtime_guard.py

monetary-float-guard:
	python scripts/check_monetary_float_usage.py

format:
	python -m ruff format .

clean:
	python -c "import shutil, pathlib; [shutil.rmtree(p, ignore_errors=True) for p in ['__pycache__', '.pytest_cache', 'htmlcov', '.ruff_cache', '.mypy_cache']]; [pathlib.Path(p).unlink(missing_ok=True) for p in ['.coverage', '.coverage.unit', '.coverage.integration', '.coverage.e2e']]"

run:
	uvicorn main:app --reload --port 8000

check-deps:
	python scripts/dependency_health_check.py --skip-audit --skip-outdated --requirement requirements.txt --requirement requirements-dev.txt

security-audit:
	python scripts/dependency_health_check.py --skip-outdated --requirement requirements.txt --requirement requirements-dev.txt

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down


docker-build:
	docker build -f Dockerfile -t lotus-performance:ci .
