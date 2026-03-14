.PHONY: install check check-all test test-unit test-integration test-e2e test-all ci ci-local ci-local-docker ci-local-docker-down typecheck lint monetary-float-guard format clean run check-deps security-audit openapi-gate api-vocabulary-gate no-alias-gate migration-smoke migration-apply recovery-drill-smoke pre-commit docker-up docker-down docker-build

install:
	pip install -r requirements.txt
	pip install -r requirements-dev.txt
	pip install pre-commit
	pre-commit install

pre-commit:
	pre-commit run --all-files

check: lint no-alias-gate typecheck openapi-gate api-vocabulary-gate test

ci: lint no-alias-gate typecheck openapi-gate api-vocabulary-gate migration-smoke test-all security-audit

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

ci-local: lint check-deps
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

migration-smoke:
	python scripts/migration_contract_check.py --mode durable-schema
	python scripts/durable_schema_inventory_check.py
	python scripts/durable_recovery_runbook_check.py
	$(MAKE) recovery-drill-smoke

recovery-drill-smoke:
	python scripts/durable_recovery_drill.py --operator-id migration-smoke --backup-identifier migration-smoke-local

migration-apply:
	python scripts/migration_contract_check.py --mode durable-schema

lint:
	python -m ruff check .
	python -m ruff format --check .
	$(MAKE) monetary-float-guard

monetary-float-guard:
	python scripts/check_monetary_float_usage.py

format:
	python -m ruff format .

clean:
	python -c "import shutil, pathlib; [shutil.rmtree(p, ignore_errors=True) for p in ['__pycache__', '.pytest_cache', 'htmlcov', '.ruff_cache', '.mypy_cache']]; [pathlib.Path(p).unlink(missing_ok=True) for p in ['.coverage', '.coverage.unit', '.coverage.integration', '.coverage.e2e']]"

run:
	uvicorn main:app --reload --port 8000

check-deps:
	python scripts/dependency_health_check.py --requirements requirements.txt

security-audit:
	python scripts/dependency_health_check.py --requirements requirements.txt

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down


docker-build:
	docker build -f Dockerfile -t lotus-performance:ci .


