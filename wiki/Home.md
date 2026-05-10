# lotus-performance wiki

`lotus-performance` is the Lotus performance analytics authority. It owns benchmark-aware
performance calculations, returns-series integration, durable execution tracking, and lineage-backed
reproducibility for downstream platform consumers.

## Start here

- Repo entrypoint: [README.md](../README.md)
- Repo context: [REPOSITORY-ENGINEERING-CONTEXT.md](../REPOSITORY-ENGINEERING-CONTEXT.md)
- Architecture: [docs/technical/architecture.md](../docs/technical/architecture.md)
- Runtime topology: [docs/technical/runtime_topology.md](../docs/technical/runtime_topology.md)
- API reference: [docs/guides/api_reference.md](../docs/guides/api_reference.md)
- Complete service reference: [docs/guides/complete_service_reference.md](../docs/guides/complete_service_reference.md)

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

## Common commands

```bash
make install
make run
make check
make ci
```

## Navigation

- [Overview](Overview)
- [Architecture](Architecture)
- [API Surface](API-Surface)
- [Time-Weighted Return](Time-Weighted-Return)
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
