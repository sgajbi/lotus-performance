# Scalability and Availability Standard Alignment

Service: lotus-performance

This repository adopts the platform-wide standard defined in lotus-platform/Scalability and Availability Standard.md.

## Implemented Baseline

- Stateless service behavior with externalized durable state.
- Explicit timeout and bounded retry/backoff for inter-service communication where applicable.
- Health/liveness/readiness endpoints for runtime orchestration.
- Observability instrumentation for latency/error/throughput diagnostics.
- API pagination/filter guardrails through bounded query parameters (`featureLimit`, `workflowLimit`).

## Required Evidence

- Compliance matrix entry in lotus-platform/output/scalability-availability-compliance.md.
- Service-specific tests covering resilience and concurrency-critical paths.

## Database Scalability Fundamentals

- Query plan checks are required for analytics endpoints that persist or read materialized results.
- Index coverage must be explicit for attribution/performance lookup keys and time-window filters.
- Data growth assumptions are maintained for analytics payload volume and stored result history.
- Retention and archival windows are documented for generated analytics artifacts.

## Availability Baseline

- Internal SLO baseline: p95 analytics API latency < 500 ms for cached reads; error rate < 1%.
- Recovery targets: RTO 30 minutes and RPO 15 minutes for persisted analytics state.
- Backup and restore validation: restoration drill evidence is required in environment runbooks before go-live.

## Caching Policy Baseline

- Cache usage is explicit for read-optimized analytics surfaces only.
- TTL, invalidation owner, and stale-read behavior must be documented before enabling cache-backed responses.
- Correctness-critical valuation/performance calculations cannot depend on stale cache values.

## Scale Signal Metrics Coverage

- lotus-performance exposes `/metrics` for latency/error/throughput and downstream dependency instrumentation.
- Runtime breach-gauge severity and response defaults are governed in `docs/standards/runtime-alert-policy.md`.
- Platform-shared metrics for CPU/memory, DB performance, and queue/consumer lag are sourced from:
  - `lotus-platform/platform-stack/prometheus/prometheus.yml`
  - `lotus-platform/platform-stack/docker-compose.yml`
  - `lotus-platform/Platform Observability Standards.md`

## Deviation Rule

Any deviation from this standard requires ADR/RFC with remediation timeline.

