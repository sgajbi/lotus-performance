# Platform Surfaces Endpoint Certification

## Covered Endpoints

- `GET /`
- `GET /health`
- `GET /health/live`
- `GET /health/ready`
- `GET /metrics`

## Purpose And Ownership

These routes are the lotus-performance platform-support surfaces rather than analytics endpoints.
They exist for service entry, process health, durable readiness, and Prometheus observability.

`GET /` is informational only and points callers to `/docs`. It is not a strategic analytics,
integration, or operator workflow endpoint.

`GET /health`, `GET /health/live`, and `GET /health/ready` are operational contracts. `GET /metrics`
is the Prometheus scrape contract for platform observability and alerting.

Implementation ownership is split so scrape-source collection and metric construction remain
reviewable:

| Module | Ownership |
| --- | --- |
| `app.services.queue_metrics_service` | Prometheus collector orchestration, runtime metric source loading, availability sample emission, and source-to-builder wiring. |
| `app.services.queue_metric_builders` | Reusable queue, lineage storage, recovery-drill, runtime-retention, policy-threshold, latest-age, and prunable-item metric construction with governed labels. |
| `app.services.runtime_status_policy` | Shared runtime threshold extraction used by both `/integration/runtime-status` and `/metrics` runtime breach samples. |

## Behavior And Feature Checks

Certified behavior:

- `GET /` returns a stable service-entry message that points callers to `/docs`
- `GET /health` returns lightweight process reachability without durable dependency checks
- `GET /health/live` returns liveness without durable dependency checks
- `GET /health/ready` returns `200` only when the service is not draining and durable metadata plus lineage storage are usable
- `GET /health/ready` returns `503` with concrete `reason` values for draining and durable dependency failures
- readiness failures may include `remediation_hint` when the service can offer a concrete recovery action
- `GET /metrics` exposes Prometheus-formatted queue, storage, recovery-drill, and runtime-retention gauges
- metrics continue to expose store unavailability truthfully instead of publishing false zero samples

## Upstream And Downstream Posture

These routes do not call lotus-core. They reflect lotus-performance-owned process and durable-store
state.

Known downstream posture:

- platform monitors and scrape jobs consume `GET /metrics`
- runtime checks, runbooks, and deployment tooling consume the health routes
- no duplicate lotus-performance health or metrics endpoint was found

## Swagger Readiness

Swagger now distinguishes:

- service-entry routing at `/`
- lightweight health versus liveness versus durable readiness
- `GET /metrics` as a `text/plain` Prometheus exposition surface rather than a fake JSON payload

## Test Pyramid Assessment

Current test posture is sufficient and production-grade:

- integration tests cover health, liveness, readiness success/failure, and metrics content
- lower-level durability and queue-metrics tests cover the underlying failure and signal paths
- OpenAPI/docs tests now prevent root, health, and metrics documentation drift

## Validation Commands

```bash
python -m pytest tests/unit/app/test_platform_surfaces_openapi_contract.py tests/integration/test_integration_capabilities_api.py tests/unit/docs/test_public_docs_contract.py -q
python scripts/openapi_quality_gate.py
python scripts/api_vocabulary_inventory.py --validate-only
python -m ruff check app/api/endpoints/health.py app/models/platform_surfaces.py app/openapi_enrichment.py main.py tests/unit/app/test_platform_surfaces_openapi_contract.py tests/unit/docs/test_public_docs_contract.py
python -m ruff format --check app/api/endpoints/health.py app/models/platform_surfaces.py app/openapi_enrichment.py main.py tests/unit/app/test_platform_surfaces_openapi_contract.py tests/unit/docs/test_public_docs_contract.py
python -m mypy --config-file mypy.ini app/api/endpoints/health.py app/models/platform_surfaces.py app/openapi_enrichment.py main.py
```
