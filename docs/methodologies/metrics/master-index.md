# Lotus-Performance Metrics Methodology Index

This index maps implemented lotus-performance metrics to detailed methodology documents.

| Metric | Primary Endpoint(s) | Modes | Document |
|---|---|---|---|
| TWR Base Return | POST /performance/twr | Stateless + Stateful | [metric-twr-base-return.md](./metric-twr-base-return.md) |
| TWR Local Return | POST /performance/twr | Stateless + Stateful | [metric-twr-local-return.md](./metric-twr-local-return.md) |
| TWR FX Return | POST /performance/twr | Stateless + Stateful | [metric-twr-fx-return.md](./metric-twr-fx-return.md) |
| MWR (XIRR) | POST /performance/mwr | Stateless + Stateful | [metric-mwr-xirr.md](./metric-mwr-xirr.md) |
| MWR (Modified Dietz fallback / Dietz explicit) | POST /performance/mwr | Stateless + Stateful | [metric-mwr-dietz.md](./metric-mwr-dietz.md) |
| Position Total Contribution | POST /performance/contribution | Stateless + Stateful | [metric-contribution-total.md](./metric-contribution-total.md) |
| Position Local Contribution | POST /performance/contribution | Stateless + Stateful | [metric-contribution-local.md](./metric-contribution-local.md) |
| Position FX Contribution | POST /performance/contribution | Stateless + Stateful | [metric-contribution-fx.md](./metric-contribution-fx.md) |
| Attribution Allocation Effect | POST /performance/attribution | Stateless + Stateful | [metric-attribution-allocation.md](./metric-attribution-allocation.md) |
| Attribution Selection Effect | POST /performance/attribution | Stateless + Stateful | [metric-attribution-selection.md](./metric-attribution-selection.md) |
| Attribution Interaction Effect | POST /performance/attribution | Stateless + Stateful | [metric-attribution-interaction.md](./metric-attribution-interaction.md) |
| Attribution Total Active Return | POST /performance/attribution | Stateless + Stateful | [metric-attribution-active-return.md](./metric-attribution-active-return.md) |
| Currency Local Allocation | POST /performance/attribution | Stateless + Stateful (multi-currency path) | [metric-currency-local-allocation.md](./metric-currency-local-allocation.md) |
| Currency Local Selection | POST /performance/attribution | Stateless + Stateful (multi-currency path) | [metric-currency-local-selection.md](./metric-currency-local-selection.md) |
| Currency Allocation | POST /performance/attribution | Stateless + Stateful (multi-currency path) | [metric-currency-allocation.md](./metric-currency-allocation.md) |
| Currency Selection | POST /performance/attribution | Stateless + Stateful (multi-currency path) | [metric-currency-selection.md](./metric-currency-selection.md) |
| Portfolio Return Series | POST /integration/returns/series | Stateless + Stateful | [metric-returns-series-portfolio.md](./metric-returns-series-portfolio.md) |
| Benchmark Return Series | POST /integration/returns/series | Stateless + Stateful | [metric-returns-series-benchmark.md](./metric-returns-series-benchmark.md) |
| Active Return Series | POST /integration/returns/series | Stateless + Stateful | [metric-returns-series-active.md](./metric-returns-series-active.md) |
| Risk-Free Return Series | POST /integration/returns/series | Stateless + Stateful | [metric-returns-series-risk-free.md](./metric-returns-series-risk-free.md) |

## Notes
- simulation mode is not exposed on lotus-performance public analytics contracts in this slice.
- Stateful execution currently applies to the returns-series integration endpoint and to
  `POST /performance/mwr`. Stateful MWR resolves lotus-core portfolio timeseries into canonical
  MWR inputs and preserves source-owned capital-flow supportability instead of making downstream
  consumers reconstruct investor cash-flow schedules.
- `POST /performance/contribution` also supports stateful execution. Stateful contribution resolves
  lotus-core portfolio and position timeseries into canonical contribution inputs while keeping
  contribution methodology, smoothing, hierarchy aggregation, and response supportability owned by
  `lotus-performance`.
- `POST /performance/attribution` also supports stateful execution. Stateful attribution resolves
  lotus-core portfolio and position timeseries, benchmark assignment or explicit benchmark override,
  benchmark component inputs, and source currency evidence into canonical attribution panel inputs
  while keeping Brinson, active-return, linking, and Karnosky-Singer methodology owned by
  `lotus-performance`.
- In current engine behavior, `mwr_method=MODIFIED_DIETZ` uses dated cash-flow weights and
  `mwr_method=DIETZ` keeps the midpoint Simple Dietz path.


## Documentation Standard
Each metric document in this set follows the strict v3 methodology standard with this exact section order:
- `## Metric`
- `## Endpoint and Mode Coverage`
- `## Inputs`
- `## Upstream Data Sources`
- `## Unit Conventions`
- `## Variable Dictionary`
- `## Methodology and Formulas`
- `## Step-by-Step Computation`
- `## Validation and Failure Behavior`
- `## Configuration Options`
- `## Outputs`
- `## Worked Example`

This standard is intentionally audit-oriented:
- symbols in formulas are defined explicitly
- units are stated as decimal vs percentage-point outputs
- validation and failure behavior are derived from the shipped implementation
- worked examples map final values back to exact response fields
