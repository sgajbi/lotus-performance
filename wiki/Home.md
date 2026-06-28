# lotus-performance Wiki

`lotus-performance` is the Lotus domain service for benchmark-aware performance analytics,
returns-series integration, durable execution tracking, and lineage-backed reproducibility.

Use this wiki as the governed navigation layer for current implementation truth. It summarizes the
repo, links to deeper evidence, and separates supported product claims from roadmap intent.

## Start here

| Need | Start with |
| --- | --- |
| Repository orientation | [README.md](../README.md), [Overview](Overview) |
| Engineering context | [REPOSITORY-ENGINEERING-CONTEXT.md](../REPOSITORY-ENGINEERING-CONTEXT.md), [Development Workflow](Development-Workflow) |
| Runtime architecture | [Architecture](Architecture), [docs/technical/runtime_topology.md](../docs/technical/runtime_topology.md) |
| API and contracts | [API Surface](API-Surface), [docs/guides/api_reference.md](../docs/guides/api_reference.md) |
| Operations and support | [Operations Runbook](Operations-Runbook), [Troubleshooting](Troubleshooting) |
| Demo and sales boundaries | [Supported Features](Supported-Features), [docs/guides/demo_readiness.md](../docs/guides/demo_readiness.md) |

## Repo role

This repo owns:

- time-weighted return, money-weighted return, benchmark, contribution, attribution, and workspace summary analytics
- canonical returns-series integration for downstream Lotus consumers
- execution polling, runtime-status, work-item, recovery, and retention operator surfaces
- lineage artifacts and reproducibility evidence for durable workflows

This repo does not own:

- source-of-record portfolio, benchmark, index, FX, or reference datasets
- gateway-facing product shaping or frontend experience composition
- upstream performance conclusions from `lotus-core`

## Runtime posture

The implemented runtime is a four-service topology with an optional retention worker:

1. `performance-analytics`
2. `performance-compute-executor`
3. `performance-lineage-worker`
4. `performance-lineage-db`
5. optional `performance-runtime-retention-worker`

Async execution and lineage are real contract features, not optional background conveniences.

## Evidence standard

Every claim in this wiki should be traceable to at least one of:

- implementation in `app/`, `engine/`, `core/`, `adapters/`, or `main.py`
- public API contracts, OpenAPI, or domain data-product declarations
- repo-native validation commands, CI gates, or certification evidence
- current runbooks, standards, RFCs, or repo-local context

Planned capabilities belong in [Roadmap](Roadmap), not in [Supported Features](Supported-Features)
or client-facing demo language.

## Common commands

```bash
make install
make run
make check
make ci
make demo-api-certification
```

## Audience paths

| Audience | Start with | Why |
| --- | --- | --- |
| Business, sales, and demo teams | [Supported Features](Supported-Features), [Demo Readiness Guide](../docs/guides/demo_readiness.md) | Understand which analytics claims are implementation-backed and how to review repeatable demo evidence. |
| Operators and support | [Operations Runbook](Operations-Runbook), [Troubleshooting](Troubleshooting), [Validation and CI](Validation-and-CI) | Review runtime posture, readiness, recovery, retention, metrics, and support triage paths. |
| Engineers and agents | [API Surface](API-Surface), [Development Workflow](Development-Workflow), [REPOSITORY-ENGINEERING-CONTEXT.md](../REPOSITORY-ENGINEERING-CONTEXT.md) | Keep API contracts, docs, tests, and repo-native gates synchronized with implementation truth. |

## Navigation

- [Overview](Overview)
- [Architecture](Architecture)
- [API Surface](API-Surface)
- [Time-Weighted Return](Time-Weighted-Return)
- [Contribution Analytics](Contribution-Analytics)
- [Attribution Analytics](Attribution-Analytics)
- [Composite Performance](Composite-Performance)
- [Supported Features](Supported-Features)
- [Getting Started](Getting-Started)
- [Development Workflow](Development-Workflow)
- [Validation and CI](Validation-and-CI)
- [Operations Runbook](Operations-Runbook)
- [Integrations](Integrations)
- [Security and Governance](Security-and-Governance)
- [RFC Index](RFC-Index)
- [Roadmap](Roadmap)
- [Troubleshooting](Troubleshooting)
