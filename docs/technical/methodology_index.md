# Methodology Index

This index maps the current `lotus-performance` documentation set to the implemented public
analytics and integration surfaces.

## Public API guides

- [guides/twr.md](../guides/twr.md)
- [guides/mwr.md](../guides/mwr.md)
- [guides/contribution.md](../guides/contribution.md)
- [guides/attribution.md](../guides/attribution.md)
- [guides/workspace_summary.md](../guides/workspace_summary.md)
- [guides/multi_currency.md](../guides/multi_currency.md)
- [guides/robustness_policies.md](../guides/robustness_policies.md)
- [guides/reproducibility.md](../guides/reproducibility.md)
- [guides/api_reference.md](../guides/api_reference.md)

## Metric methodology set

Canonical metric-level methodology documents live in:

- [methodologies/metrics/master-index.md](../methodologies/metrics/master-index.md)

That set is the authoritative metric-by-metric reference for:

- TWR base, local, and FX return
- MWR XIRR and Dietz paths
- contribution metrics
- attribution metrics
- returns-series portfolio, benchmark, and risk-free series

## Technical references

- [architecture.md](architecture.md)
- [runtime_topology.md](runtime_topology.md)
- [engine_config.md](engine_config.md)
- [data_model.md](data_model.md)

## Scope notes

- The current public TWR, contribution, and attribution contracts use `analyses` and do not use the
  older `period_type` plus top-level `frequencies` shape.
- The current returns-series contract is the only public surface with stateful execution mode.
- Contribution, attribution, and returns-series may run synchronously or asynchronously depending on
  workload size and executor policy.
- OpenAPI is the canonical field-level contract source for descriptions and examples.
