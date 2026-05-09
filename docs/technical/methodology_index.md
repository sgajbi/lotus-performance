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
- MWR XIRR and Dietz paths, including stateless caller-owned inputs and stateful lotus-core
  source normalization
- contribution metrics, including stateless caller-owned inputs and stateful lotus-core portfolio
  and position timeseries normalization
- attribution metrics
- returns-series portfolio, benchmark, and risk-free series

## Technical references

- [architecture.md](architecture.md)
- [runtime_topology.md](runtime_topology.md)
- [engine_config.md](engine_config.md)
- [data_model.md](data_model.md)
- [attribution-endpoint-certification.md](attribution-endpoint-certification.md)
- [contribution-endpoint-certification.md](contribution-endpoint-certification.md)

## Scope notes

- The current public TWR, contribution, and attribution contracts use `analyses` and do not use the
  older `period_type` plus top-level `frequencies` shape.
- The current returns-series integration contract and `POST /performance/mwr` support stateful
  execution. Stateful MWR uses lotus-core portfolio timeseries to resolve the investor
  capital-timing input schedule; downstream callers should use the source-owned response fields and
  must not reconstruct MWR inputs from TWR, benchmark, or workspace summary payloads.
- `POST /performance/contribution` also supports stateful execution. Stateful contribution resolves
  lotus-core portfolio and position timeseries into source-normalized contribution inputs; callers
  should consume emitted contribution results and supportability rather than reconstructing
  position contribution from TWR, MWR, attribution, or raw source rows downstream.
- Contribution, attribution, and returns-series may run synchronously or asynchronously depending on
  workload size and executor policy.
- OpenAPI is the canonical field-level contract source for descriptions and examples.
