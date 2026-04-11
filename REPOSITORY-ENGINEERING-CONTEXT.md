# Repository Engineering Context

This file provides repository-local engineering context for `lotus-performance`.

For platform-wide truth, read:

1. `../lotus-platform/context/LOTUS-QUICKSTART-CONTEXT.md`
2. `../lotus-platform/context/LOTUS-ENGINEERING-CONTEXT.md`
3. `../lotus-platform/context/CONTEXT-REFERENCE-MAP.md`

## Repository Role

`lotus-performance` is the authoritative performance analytics service in Lotus.

It owns benchmark-aware performance calculations, contribution, attribution, returns series, execution tracking, and lineage capture for performance workflows.

## Business And Domain Responsibility

This repository owns:

1. time-weighted and money-weighted return workflows,
2. benchmark analytics,
3. contribution and attribution analytics,
4. performance execution lifecycle tracking,
5. performance lineage and reproducibility evidence.

## Current-State Summary

Current repository posture:

1. `lotus-performance` is the authoritative performance analytics engine consumed by `lotus-gateway`,
2. stateful integration with `lotus-core` is active and important for live product flows,
3. the service already operates with enterprise-grade CI posture including security, migration, and Docker gates,
4. async execution, lineage capture, and benchmark-aware workflows are real parts of the contract, not future placeholders.

## Architecture And Module Map

Primary areas:

1. `app/`
   API and runtime application layer.
2. `engine/`
   Analytics and execution internals.
3. `core/`
   domain and calculation foundations.
4. `adapters/`
   integration seams and storage/runtime adapters.
5. `docs/`
   service guides, methodology, and technical runtime docs.
6. `scripts/`
   quality gates, migration checks, and dependency-health tooling.
7. `tests/`
   unit, integration, e2e, and benchmark or characterization coverage.

## Runtime And Integration Boundaries

Runtime model:

1. API service plus compute, lineage, and storage/runtime components,
2. consumed primarily through `lotus-gateway`,
3. depends on `lotus-core` for stateful portfolio and benchmark sourcing.

Boundary rules:

1. performance analytics authority stays here,
2. gateway and UI should consume governed outputs rather than reimplement analytics logic,
3. async and lineage behavior are contract features and should remain explicit,
4. benchmark and stateful integration behavior must remain truthful and documented.

## Repo-Native Commands

Use these commands as the primary local contract:

1. install
   `make install`
2. fast local gate
   `make check`
3. PR-grade local gate
   `make ci`
4. Docker-parity local gate
   `make ci-local`
5. full local test and characterization gate
   `make test-all`
6. run locally
   `make run`

## Validation And CI Expectations

`lotus-performance` uses explicit CI lanes:

1. `Remote Feature Lane`
2. `Pull Request Merge Gate`
3. `Main Releasability Gate`

Important validation expectations:

1. OpenAPI and API vocabulary governance are active,
2. migration smoke and project-scoped dependency health are required,
3. unit, integration, e2e, coverage, and Docker build are part of the real merge contract,
4. analytics quality and runtime characterization matter because downstream product surfaces depend on the truthfulness of these results.

## Standards And RFCs That Govern This Repository

Most relevant current governance:

1. `../lotus-platform/rfcs/RFC-0022-performance-analytics-engineering-alignment-to-dpm-standard.md`
2. `../lotus-platform/rfcs/RFC-0065-lotus-performance-to-lotus-performance-and-lotus-risk-split.md`
3. `../lotus-platform/rfcs/RFC-0067-centralized-api-vocabulary-inventory-and-openapi-documentation-governance.md`
4. `../lotus-platform/rfcs/RFC-0072-platform-wide-multi-lane-ci-validation-and-release-governance.md`
5. `../lotus-platform/rfcs/RFC-0073-lotus-ecosystem-engineering-context-and-agent-guidance-system.md`
6. `docs/technical/architecture.md`
7. `docs/technical/runtime_topology.md`

## Known Constraints And Implementation Notes

1. this service carries both analytics correctness and product-facing integration consequences, so changes must be checked for downstream gateway and UI impact,
2. async execution and lineage are already part of the contract and should not be treated as optional infrastructure details,
3. benchmark-aware stateful behavior must remain aligned with `lotus-core` sourcing and gateway expectations,
4. methodology and reproducibility documentation matter here as much as code.

## Context Maintenance Rule

Update this document when:

1. major analytics capabilities or runtime topology change,
2. repo-native commands or lane expectations change,
3. stateful integration boundaries with `lotus-core` change,
4. methodology, lineage, or execution posture changes materially,
5. current product-support posture changes.

## Cross-Links

1. `../lotus-platform/context/LOTUS-QUICKSTART-CONTEXT.md`
2. `../lotus-platform/context/LOTUS-ENGINEERING-CONTEXT.md`
3. `../lotus-platform/context/CONTEXT-REFERENCE-MAP.md`
4. `../lotus-platform/context/Repository-Engineering-Context-Contract.md`
5. [Lotus Developer Onboarding](../lotus-platform/docs/onboarding/LOTUS-DEVELOPER-ONBOARDING.md)
6. [Lotus Agent Ramp-Up](../lotus-platform/docs/onboarding/LOTUS-AGENT-RAMP-UP.md)
