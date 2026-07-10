# RFC-021 Gross/Net Support Baseline

This page is the current implementation baseline for RFC-021. It separates the supported
`metric_basis` fee treatment from the broader gross-to-net bridge that the original RFC proposed.

## Current Contract

| Area | Current support | Evidence | Boundary |
| --- | --- | --- | --- |
| TWR `metric_basis` | Implemented for `NET` and `GROSS`. `NET` includes `mgmt_fees` in the daily return numerator; `GROSS` excludes those management fees. | `engine/ror.py`; `docs/methodologies/metrics/metric-twr-base-return.md`; `tests/unit/engine/test_ror.py`; `tests/integration/test_performance_api.py`. | This is fee-basis treatment, not a response-level cost bridge. |
| Workspace summary net/gross | Implemented by calling direct TWR semantics for `portfolio_twr.net` and `portfolio_twr.gross`. | `docs/technical/workspace-summary-endpoint-certification.md`; `tests/integration/test_performance_api.py`. | Workspace summary does not add a separate `costs` model or `gross_net` response block. |
| Contribution and attribution `metric_basis` | Implemented as endpoint input basis and source-economics posture. | `docs/guides/contribution.md`; `docs/guides/attribution.md`; endpoint tests. | Source-economics evidence is supportability evidence, not a full cost-allocation bridge. |
| Returns series `metric_basis` | Implemented for source-owned return series basis. | `docs/technical/returns-series-endpoint-certification.md`; returns-series tests. | No local/FX/base or cost-component decomposition is emitted. |

## Unsupported Current Scope

These RFC-021 concepts are not part of the current public API contract:

| Proposed RFC-021 concept | Current status | Required future implementation path |
| --- | --- | --- |
| Shared request `costs` block | Unsupported | Add endpoint DTOs, request mappers, application command fields, domain cost policy, engine integration, OpenAPI examples, and endpoint tests before documenting as supported. |
| Top-level response `gross_net` bridge | Unsupported | Add a reconciled response model with `gross_return`, component effects, `net_return`, diagnostics, and additive tie-out tests. |
| `engine/costs.py` cost engine | Unsupported | Implement a domain-owned cost service or engine module with unit coverage before endpoint integration. |
| Performance fee HWM/hurdle state machine | Unsupported | Split into its own implementation issue because it requires stateful period memory and crystallization policy. |
| Transaction-cost, tax, and fee allocation across contribution/attribution | Unsupported | Split by endpoint and cost component with source-authority, allocation-policy, and reconciliation tests. |

## No-Claim Rule

Current docs may say that lotus-performance supports `metric_basis=NET` and `metric_basis=GROSS`.
They must not claim that `costs` request blocks, `gross_net` response bridges, `engine/costs.py`,
performance-fee HWM/hurdle calculations, or full cost-component decomposition are implemented until
those behaviors exist in code, OpenAPI, endpoint docs, and tests.

## Future Backlog Shape

Future gross-to-net work should be split into small implementation issues:

1. TWR supplied-cost bridge and response model.
2. Computed management-fee policy and validation.
3. Performance-fee HWM/hurdle state machine.
4. Contribution cost allocation.
5. Attribution cost allocation.
6. MWR investor-cash-flow fee treatment, if a separate methodology is approved.

