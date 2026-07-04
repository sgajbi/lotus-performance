# Application Pack

## Purpose

This pack contains the FastAPI application layer: API routers, request and response models,
application services, runtime workers, middleware, observability, and enterprise boundary controls.

## Audience

- backend engineers changing API or runtime behavior,
- operators tracing runtime surfaces to implementation,
- agents deciding whether a change belongs at the API boundary or in a lower domain layer.

## Layering Rules

| Area | Owns |
| --- | --- |
| `api/` | HTTP route metadata, dependencies, DTO adaptation, and response conversion. |
| `models/` | API request and response models. |
| `services/` | Application workflow, source integration, supportability, and policy orchestration. |
| `workers/` | Durable background execution and lineage/runtime worker loops. |

## Maintenance Notes

- Keep FastAPI and Starlette imports at the API adapter boundary unless a module is explicitly
  runtime composition.
- Services should use framework-neutral `core.errors.APIError` subclasses and typed application
  responses.
- Update OpenAPI, docs, tests, and repo context when public API or runtime truth changes.
