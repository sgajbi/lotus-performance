.PHONY: shell-check install install-ci verify-dependencies check check-all test test-unit test-unit-order-stability test-integration test-e2e test-all test-coverage test-coverage-shard coverage-combine-gate branch-coverage-baseline coverage-gate ci ci-local ci-local-docker ci-local-docker-down typecheck lint quality-baseline quality-baseline-check quality-complexity-gate quality-architecture-gate quality-router-thinness-gate quality-duplicate-code-gate quality-observability-readiness-gate quality-test-taxonomy-gate postgres-concurrency-contracts-gate postgres-concurrency-contracts-local quality-evaluation-gate license-compliance-gate python-security-gate calculation-engine-version-gate github-action-runtime-guard monetary-float-guard repository-hygiene-gate demo-api-certification idea-opportunity-evidence-gate idea-opportunity-runtime-evidence format clean run check-deps security-audit openapi-gate api-vocabulary-gate no-alias-gate domain-product-validate migration-smoke migration-apply recovery-drill-smoke runtime-retention-smoke lineage-volume-recovery-smoke performance-characterization performance-characterization-postgres pre-commit docker-up docker-down docker-build container-supply-chain-evidence container-sbom container-vulnerability-report container-vulnerability-gate

SUITE ?= unit
TEST_PATH ?= tests/unit
COVERAGE_FAIL_UNDER ?= 99
COVERAGE_INPUTS ?= .coverage.unit .coverage.integration .coverage.e2e
CONTAINER_IMAGE ?= lotus-performance:ci
CONTAINER_SECURITY_OUTPUT_DIR ?= output/container-security
TRIVY_IMAGE ?= aquasec/trivy:0.71.2
TRIVY_SEVERITY ?= HIGH,CRITICAL
CONTAINER_SERVICE_VERSION ?= 0.1.0
# Quote a value for safe interpolation into a recipe. The value becomes data, never
# syntax: git accepts branch names containing `;`, `$`, backticks and quotes, and an
# unquoted expansion would let any of them change the command being run.
shellquote = '$(subst ','"'"',$(1))'
CONTAINER_GIT_HEAD ?= $(shell git rev-parse --verify HEAD 2>/dev/null || echo local)
CONTAINER_GIT_TREE_STATE := $(shell git status --porcelain 2>/dev/null | grep -q . && echo dirty || echo clean)
# A build from a modified tree is not the commit it names. The marker keeps local
# iteration working while making the difference visible, so acceptance can reject a
# dirty value instead of being unable to see one.
CONTAINER_GIT_SHA ?= $(CONTAINER_GIT_HEAD)$(if $(filter dirty,$(CONTAINER_GIT_TREE_STATE)),-dirty,)
CONTAINER_GIT_BRANCH ?= $(shell git rev-parse --abbrev-ref HEAD 2>/dev/null || echo local)
CONTAINER_BUILD_TIMESTAMP ?= $(shell python -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z'))")
CONTAINER_REPOSITORY_URL ?= https://github.com/sgajbi/lotus-performance
CONTAINER_IMAGE_DIGEST ?= unavailable-before-push
CONTAINER_CI_PIPELINE_RUN_ID ?= local

# Re-capture any provenance value that arrived from the environment as raw text.
#
# GNU Make imports environment variables as *recursively expanded*, so an env-supplied
# value containing `$(...)` is interpreted by Make before `shellquote` ever sees it: a
# branch literally named `feature/foo$(id)` reaches the build argument as
# `feature/foo`, and the image then records a branch that does not exist. That path is
# the supported one -- `.github/workflows/main-releasability.yml` supplies
# CONTAINER_GIT_SHA, CONTAINER_GIT_BRANCH, CONTAINER_REPOSITORY_URL and
# CONTAINER_CI_PIPELINE_RUN_ID through the environment.
#
# `$(value ...)` returns the unexpanded text, and the result of an expansion is not
# re-scanned, so the raw value survives into the recipe where shellquote makes it data.
# Values that did not come from the environment are left exactly as computed above.
#
# Applied to every provenance variable rather than only the ones that look risky today:
# deciding per variable which can contain a `$` is a judgement that goes stale, and the
# uniform rule costs nothing.
#
# Raised in review of #511. The `$(shell ...)` derivation is NOT affected -- Make does
# not re-expand shell output -- which is exactly why the first hostile-branch test
# missed this: it entered through the one door that was already safe.
raw_environment_value = $(if $(filter environment,$(origin $(1))),$(value $(1)),$(2))
CONTAINER_SERVICE_VERSION := $(call raw_environment_value,CONTAINER_SERVICE_VERSION,$(CONTAINER_SERVICE_VERSION))
CONTAINER_GIT_SHA := $(call raw_environment_value,CONTAINER_GIT_SHA,$(CONTAINER_GIT_SHA))
CONTAINER_GIT_BRANCH := $(call raw_environment_value,CONTAINER_GIT_BRANCH,$(CONTAINER_GIT_BRANCH))
CONTAINER_BUILD_TIMESTAMP := $(call raw_environment_value,CONTAINER_BUILD_TIMESTAMP,$(CONTAINER_BUILD_TIMESTAMP))
CONTAINER_REPOSITORY_URL := $(call raw_environment_value,CONTAINER_REPOSITORY_URL,$(CONTAINER_REPOSITORY_URL))
CONTAINER_IMAGE_DIGEST := $(call raw_environment_value,CONTAINER_IMAGE_DIGEST,$(CONTAINER_IMAGE_DIGEST))
CONTAINER_CI_PIPELINE_RUN_ID := $(call raw_environment_value,CONTAINER_CI_PIPELINE_RUN_ID,$(CONTAINER_CI_PIPELINE_RUN_ID))

CONTAINER_BUILD_TARGET ?= runtime
CI_LOCAL_COMPOSE_PROJECT ?= $(shell python scripts/ci_local_compose_project.py)

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

check: lint quality-complexity-gate quality-architecture-gate quality-router-thinness-gate quality-duplicate-code-gate quality-observability-readiness-gate no-alias-gate typecheck openapi-gate api-vocabulary-gate domain-product-validate quality-evaluation-gate license-compliance-gate python-security-gate test

test-coverage:
	$(MAKE) test-coverage-shard SUITE=unit TEST_PATH=tests/unit
	$(MAKE) test-coverage-shard SUITE=integration TEST_PATH=tests/integration
	$(MAKE) test-coverage-shard SUITE=e2e TEST_PATH=tests/e2e
	$(MAKE) coverage-combine-gate COVERAGE_INPUTS=".coverage.unit .coverage.integration .coverage.e2e"

test-coverage-shard:
	COVERAGE_FILE=.coverage.$(SUITE) python -m pytest $(TEST_PATH) --cov=app --cov=engine --cov=core --cov=adapters --cov-report=

coverage-combine-gate:
	python -m coverage combine $(COVERAGE_INPUTS)
	python -m coverage report --fail-under=$(COVERAGE_FAIL_UNDER)

branch-coverage-baseline:
	COVERAGE_FILE=.coverage.branch.unit python -m pytest tests/unit --cov=app --cov=engine --cov=core --cov=adapters --cov-branch --cov-report=
	COVERAGE_FILE=.coverage.branch.integration python -m pytest tests/integration --cov=app --cov=engine --cov=core --cov=adapters --cov-branch --cov-report=
	COVERAGE_FILE=.coverage.branch.e2e python -m pytest tests/e2e --cov=app --cov=engine --cov=core --cov=adapters --cov-branch --cov-report=
	python -m coverage combine .coverage.branch.unit .coverage.branch.integration .coverage.branch.e2e
	python -c "from pathlib import Path; Path('output/branch-coverage').mkdir(parents=True, exist_ok=True)"
	python -m coverage json -o output/branch-coverage/coverage.json
	python scripts/python_branch_coverage_inventory.py --coverage-json output/branch-coverage/coverage.json --write

coverage-gate: test-coverage

ci: lint quality-complexity-gate quality-architecture-gate quality-router-thinness-gate quality-duplicate-code-gate quality-observability-readiness-gate no-alias-gate typecheck openapi-gate api-vocabulary-gate domain-product-validate quality-evaluation-gate license-compliance-gate migration-smoke security-audit python-security-gate test-unit test-integration test-e2e coverage-gate docker-build

test:
	$(MAKE) test-unit

test-unit:
	python -m pytest tests/unit

test-unit-order-stability:
	python scripts/pytest_collection_stability.py tests/unit --seeds 1 2 3
	python -m pytest tests/unit/engine/test_contribution.py -q --randomly-seed=1
	python -m pytest tests/unit/engine/test_contribution.py -q --randomly-seed=2
	python -m pytest tests/unit/engine/test_contribution.py -q --randomly-seed=3

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
	docker compose --project-name "$(CI_LOCAL_COMPOSE_PROJECT)" -f docker-compose.ci-local.yml up --build --abort-on-container-exit --exit-code-from ci-local ci-local

ci-local-docker-down:
	docker compose --project-name "$(CI_LOCAL_COMPOSE_PROJECT)" -f docker-compose.ci-local.yml down -v --remove-orphans

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

license-compliance-gate:
	python scripts/license_compliance_inventory.py --check

migration-smoke:
	python scripts/migration_contract_check.py --mode durable-schema
	python scripts/durable_schema_inventory_check.py
	python scripts/durable_recovery_runbook_check.py
	$(MAKE) recovery-drill-smoke

recovery-drill-smoke:
	python scripts/durable_recovery_drill.py --output-dir artifacts/durable-recovery-drill --retention-limit 30 --retention-max-age-days 90 --operator-id migration-smoke --backup-identifier migration-smoke-local

runtime-retention-smoke:
	python scripts/runtime_retention_cleanup.py --scheduled --output-dir artifacts/runtime-retention-cleanup --retention-limit 30 --retention-max-age-days 90

lineage-volume-recovery-smoke:
	python scripts/validate_lineage_volume_recovery.py

performance-characterization:
	python scripts/run_performance_characterization.py --mode full

performance-characterization-postgres:
	docker compose up -d performance-lineage-db
	python scripts/run_performance_characterization.py --mode postgres --require-non-skipped

migration-apply:
	python scripts/durable_schema_apply.py --output-dir artifacts/durable-schema-apply

shell-check:
	@echo "make is running recipes through SHELL=$(SHELL)"
	LOTUS_SHELL_PROBE=posix eval 'test "$$LOTUS_SHELL_PROBE" = posix'
	@echo "Leading VAR=value assignments work, so the coverage targets will run."

lint:
	python -m ruff check .
	python -m ruff format --check .
	$(MAKE) calculation-engine-version-gate
	$(MAKE) github-action-runtime-guard
	$(MAKE) monetary-float-guard
	$(MAKE) repository-hygiene-gate

calculation-engine-version-gate:
	python scripts/calculation_engine_version_gate.py

quality-baseline:
	python scripts/generate_quality_baseline.py --write

quality-baseline-check:
	python scripts/generate_quality_baseline.py --check

quality-complexity-gate:
	python scripts/python_complexity_inventory.py --limit 25 --max-cc 8 --max-high-complexity 0

quality-architecture-gate:
	python scripts/python_architecture_boundary_inventory.py --limit 40 --max-findings 0

quality-router-thinness-gate:
	python scripts/python_router_middleware_thinness_inventory.py --threshold 80 --limit 50 --max-findings 0

quality-duplicate-code-gate:
	python scripts/python_duplicate_code_inventory.py --min-lines 12 --limit 40 --max-groups 0

quality-observability-readiness-gate:
	python scripts/python_observability_readiness_inventory.py --limit 30 --max-missing 0

postgres-concurrency-contracts-gate:
	python scripts/postgres_concurrency_contracts_gate.py

# The developer-facing form: provisions the database first, so the gate can be
# reproduced before pushing rather than discovered in a required lane. Mirrors
# `performance-characterization-postgres` rather than inventing a second convention,
# and needs no DSN because the compose service publishes the port the helper defaults
# to. A gate that only CI can run is one nobody checks.
postgres-concurrency-contracts-local:
	# `--wait` honours the service healthcheck. Without it `up -d` returns as soon as
	# the container starts, so a cold start races PostgreSQL accepting connections
	# and the gate refuses for a reason unrelated to the contracts.
	docker compose up -d --wait performance-lineage-db
	# Ask Compose which port it published rather than re-deriving it. The service
	# publishes `$${PA_LINEAGE_DB_PORT:-5435}`, and Compose resolves that from the
	# shell *and* from the repository `.env`. Reproducing that resolution here means
	# matching every source Compose consults, and reading only the shell is what
	# left the `.env` case broken after the first fix. `docker compose port` answers
	# from the running container, so it is right whatever the value came from. An
	# explicit DSN still wins. Raised in review of #489.
	published="$$(docker compose port performance-lineage-db 5432)"; \
	if [ -z "$$published" ]; then \
	  echo "performance-lineage-db published no port for 5432; is it running?" >&2; \
	  exit 1; \
	fi; \
	LOTUS_POSTGRES_PLAN_DATABASE_URL="$${LOTUS_POSTGRES_PLAN_DATABASE_URL:-postgresql+psycopg://lotus:lotus@127.0.0.1:$${published##*:}/lotus_performance}" \
	    python scripts/postgres_concurrency_contracts_gate.py

quality-test-taxonomy-gate:
	python scripts/python_test_taxonomy_inventory.py --limit 30 --min-api-runtime-tests 656 --min-contract-governance-tests 136 --max-uncategorized-tests 797

quality-evaluation-gate:
	$(MAKE) demo-api-certification
	$(MAKE) quality-test-taxonomy-gate

python-security-gate:
	python scripts/python_security_inventory.py --limit 30 --max-high 0 --max-medium 0 --max-low 0

github-action-runtime-guard:
	python scripts/github_action_runtime_guard.py

monetary-float-guard:
	python scripts/check_monetary_float_usage.py

repository-hygiene-gate:
	python scripts/repository_hygiene_gate.py

demo-api-certification:
	python scripts/demo_api_certification.py

idea-opportunity-evidence-gate:
	python -m pytest tests/unit/test_idea_opportunity_runtime_evidence.py -q

idea-opportunity-runtime-evidence:
	python scripts/generate_idea_opportunity_runtime_evidence.py

format:
	python -m ruff format .

clean:
	python scripts/clean_generated_artifacts.py

run:
	uvicorn main:app --reload --port 8000

check-deps:
	python scripts/dependency_health_check.py --skip-audit --skip-outdated --requirement requirements.txt --requirement requirements-dev.txt

security-audit:
	python scripts/dependency_health_check.py --skip-outdated --requirement requirements.txt --requirement requirements-dev.txt

docker-up:
	APP_VERSION=$(call shellquote,$(CONTAINER_SERVICE_VERSION)) \
	  APP_GIT_COMMIT_SHA=$(call shellquote,$(CONTAINER_GIT_SHA)) \
	  APP_GIT_BRANCH=$(call shellquote,$(CONTAINER_GIT_BRANCH)) \
	  APP_BUILD_TIMESTAMP=$(call shellquote,$(CONTAINER_BUILD_TIMESTAMP)) \
	  APP_REPOSITORY_URL=$(call shellquote,$(CONTAINER_REPOSITORY_URL)) \
	  APP_IMAGE_DIGEST=$(call shellquote,$(CONTAINER_IMAGE_DIGEST)) \
	  APP_CI_PIPELINE_RUN_ID=$(call shellquote,$(CONTAINER_CI_PIPELINE_RUN_ID)) \
	  docker compose up -d --build

docker-down:
	docker compose down


docker-build:
	docker build -f Dockerfile --target $(CONTAINER_BUILD_TARGET) -t $(CONTAINER_IMAGE) \
		--build-arg APP_VERSION=$(call shellquote,$(CONTAINER_SERVICE_VERSION)) \
		--build-arg APP_GIT_COMMIT_SHA=$(call shellquote,$(CONTAINER_GIT_SHA)) \
		--build-arg APP_GIT_BRANCH=$(call shellquote,$(CONTAINER_GIT_BRANCH)) \
		--build-arg APP_BUILD_TIMESTAMP=$(call shellquote,$(CONTAINER_BUILD_TIMESTAMP)) \
		--build-arg APP_REPOSITORY_URL=$(call shellquote,$(CONTAINER_REPOSITORY_URL)) \
		--build-arg APP_IMAGE_DIGEST=$(call shellquote,$(CONTAINER_IMAGE_DIGEST)) \
		--build-arg APP_CI_PIPELINE_RUN_ID=$(call shellquote,$(CONTAINER_CI_PIPELINE_RUN_ID)) \
		.

container-supply-chain-evidence: container-sbom container-vulnerability-report

container-sbom: docker-build
	python -c "from pathlib import Path; Path('$(CONTAINER_SECURITY_OUTPUT_DIR)').mkdir(parents=True, exist_ok=True)"
	docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v "$(CURDIR)/$(CONTAINER_SECURITY_OUTPUT_DIR):/output" $(TRIVY_IMAGE) image --scanners vuln --format cyclonedx --output /output/lotus-performance-image-sbom.cdx.json $(CONTAINER_IMAGE)

container-vulnerability-report: docker-build
	python -c "from pathlib import Path; Path('$(CONTAINER_SECURITY_OUTPUT_DIR)').mkdir(parents=True, exist_ok=True)"
	docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v "$(CURDIR)/$(CONTAINER_SECURITY_OUTPUT_DIR):/output" $(TRIVY_IMAGE) image --scanners vuln --severity $(TRIVY_SEVERITY) --format json --output /output/lotus-performance-image-vulnerabilities.json --exit-code 0 $(CONTAINER_IMAGE)

# One scan decides everything. The evidence artifact, the acceptance validation and the
# blocking verdict previously ran three separate `docker run --rm` invocations with no
# shared cache, so a vulnerability-database update between them could make the uploaded
# artifact omit the finding that failed the job. The report target produces the single
# unfiltered snapshot; this gate reads it and decides.
#
# --ignore-unfixed is deliberately absent: unfixable advisories are accepted explicitly
# in quality/container_vulnerability_acceptances.v1.json, with owner, expiry, package
# identity and severity, and validated against that scan. That is the difference between
# a recorded decision and a hidden one.
container-vulnerability-gate: container-vulnerability-report
	python scripts/container_acceptance_gate.py --scan $(CONTAINER_SECURITY_OUTPUT_DIR)/lotus-performance-image-vulnerabilities.json
