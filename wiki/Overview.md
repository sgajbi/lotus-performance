# Overview

## Business role

`lotus-performance` is the authoritative Lotus service for performance analytics and performance
adjacent integration surfaces. It serves the contract that downstream services use for:

- TWR and MWR
- benchmark analytics
- contribution and attribution
- interaction-efficient workspace summaries
- canonical returns-series and benchmark exposure context
- execution polling and lineage retrieval

The current implementation-backed feature ledger is maintained in
[Supported Features](Supported-Features). Use that page for demo, sales, operations, and client
conversation boundaries; use [Roadmap](Roadmap) for target-state material.

For demo preparation, run `make demo-api-certification` and review the generated evidence with the
[Demo Readiness Guide](../docs/guides/demo_readiness.md). That guide explains the supported
request-level API sweep, expected calculation assertions, report-only CI posture, and boundaries
between backend API proof and broader Gateway or Workbench product-surface proof.

## Ownership boundaries

This repo owns:

1. performance methodology execution and emitted performance conclusions
2. durable execution lifecycle and async replay semantics
3. lineage materialization and reproducibility evidence
4. runtime control-plane surfaces for queue, recovery, and retention visibility

This repo does not own:

1. source portfolio, benchmark, index, FX, or reference truth
2. gateway payload shaping or UI orchestration
3. upstream benchmark or portfolio master-data stewardship

## Current posture

- `lotus-performance` is an active domain service in the Lotus runtime, not a prototype.
- Stateful sourcing from `lotus-core` is a governed shipped path under RFC-0082.
- The service already enforces OpenAPI, vocabulary, migration, and security gates.
- Async compute offload and lineage capture are contract features.

## Related pages

- [Architecture](Architecture)
- [Integrations](Integrations)
- [Supported Features](Supported-Features)
- [Demo Readiness Guide](../docs/guides/demo_readiness.md)
- [Operations Runbook](Operations-Runbook)
