# Lotus-Performance Metrics Methodology Index

This index maps implemented lotus-performance metrics to detailed methodology documents.

| Metric | Primary Endpoint(s) | Modes | Document |
|---|---|---|---|
| TWR Base Return | POST /performance/twr | Stateless | [metric-twr-base-return.md](./metric-twr-base-return.md) |
| TWR Local Return | POST /performance/twr | Stateless | [metric-twr-local-return.md](./metric-twr-local-return.md) |
| TWR FX Return | POST /performance/twr | Stateless | [metric-twr-fx-return.md](./metric-twr-fx-return.md) |
| MWR (XIRR) | POST /performance/mwr | Stateless | [metric-mwr-xirr.md](./metric-mwr-xirr.md) |
| MWR (Dietz fallback / explicit) | POST /performance/mwr | Stateless | [metric-mwr-dietz.md](./metric-mwr-dietz.md) |
| Position Total Contribution | POST /performance/contribution | Stateless | [metric-contribution-total.md](./metric-contribution-total.md) |
| Position Local Contribution | POST /performance/contribution | Stateless | [metric-contribution-local.md](./metric-contribution-local.md) |
| Position FX Contribution | POST /performance/contribution | Stateless | [metric-contribution-fx.md](./metric-contribution-fx.md) |
| Attribution Allocation Effect | POST /performance/attribution | Stateless | [metric-attribution-allocation.md](./metric-attribution-allocation.md) |
| Attribution Selection Effect | POST /performance/attribution | Stateless | [metric-attribution-selection.md](./metric-attribution-selection.md) |
| Attribution Interaction Effect | POST /performance/attribution | Stateless | [metric-attribution-interaction.md](./metric-attribution-interaction.md) |
| Attribution Total Active Return | POST /performance/attribution | Stateless | [metric-attribution-active-return.md](./metric-attribution-active-return.md) |
| Currency Local Allocation | POST /performance/attribution | Stateless (multi-currency path) | [metric-currency-local-allocation.md](./metric-currency-local-allocation.md) |
| Currency Local Selection | POST /performance/attribution | Stateless (multi-currency path) | [metric-currency-local-selection.md](./metric-currency-local-selection.md) |
| Currency Allocation | POST /performance/attribution | Stateless (multi-currency path) | [metric-currency-allocation.md](./metric-currency-allocation.md) |
| Currency Selection | POST /performance/attribution | Stateless (multi-currency path) | [metric-currency-selection.md](./metric-currency-selection.md) |
| Portfolio Return Series | POST /integration/returns/series | Stateless + Stateful | [metric-returns-series-portfolio.md](./metric-returns-series-portfolio.md) |
| Benchmark Return Series | POST /integration/returns/series | Stateless + Stateful | [metric-returns-series-benchmark.md](./metric-returns-series-benchmark.md) |
| Risk-Free Return Series | POST /integration/returns/series | Stateless + Stateful | [metric-returns-series-risk-free.md](./metric-returns-series-risk-free.md) |

## Notes
- simulation mode is not exposed on lotus-performance public analytics contracts in this slice.
- Stateful execution currently applies to the returns-series integration endpoint; core performance analytics endpoints remain request-data driven.
- In current engine behavior, `mwr_method=MODIFIED_DIETZ` is mapped to the same Dietz computation path as `DIETZ`.


## Documentation Standard
Each metric document in this set follows the same architecture review template:
- endpoint and mode scope
- upstream data dependencies
- explicit inputs
- formulas and methodology
- output field semantics
- configuration levers
- assumptions and edge-case handling
- worked numerical example
