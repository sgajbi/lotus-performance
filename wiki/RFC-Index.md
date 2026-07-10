# RFC Index

## Platform-governing RFCs

- RFC-0067
  OpenAPI and API vocabulary governance
- RFC-0072
  multi-lane CI validation and release governance
- RFC-0073
  ecosystem engineering context and agent guidance
- RFC-0082
  lotus-core domain authority and analytics-serving boundary hardening

## High-value local RFCs

- RFC-016
  MWR enhancements: XIRR, Modified Dietz fallback, response supportability, and the
  single-reporting-currency boundary
- RFC-020
  multi-currency analytics; partially implemented through the endpoint-specific support matrix,
  with FX-aware MWR still gated by the implementation-readiness contract
- RFC-021
  gross/net analytics; current support is limited to endpoint `metric_basis=NET` and
  `metric_basis=GROSS` fee-basis treatment, while `costs` blocks and `gross_net` bridge output
  remain future implementation backlog
- RFC-023
  historical blended/dynamic benchmark design; the free-form `benchmark_spec` API is superseded by
  RFC-042 and current `benchmark_id` / `input_mode` / `return_source` benchmark contracts
- RFC-030
  integration capabilities contract API
- RFC-039
  returns-series integration contract for `lotus-risk`
- RFC-041
  API orchestrator, compute executor, and PostgreSQL durable state
- RFC-042
  core-sourced benchmark performance engine
- RFC-044
  interaction-efficient workspace analytics contract
- RFC-045
  TWR inspection and supportability contract
- RFC-049
  implemented composite-performance RFC; persisted-fact composite TWR and inspection are promoted
  through supported-feature material, while composite contribution, attribution, MWR, sleeves,
  carve-outs, and advanced composite structures remain unsupported

## Full local RFC estate

- [docs/RFCs/RFC-INDEX.md](../docs/RFCs/RFC-INDEX.md)
- [docs/RFCs/RFC_IMPLEMENTATION_STATUS.md](../docs/RFCs/RFC_IMPLEMENTATION_STATUS.md)
- [docs/RFCs/RFC-DELTA-BACKLOG.md](../docs/RFCs/RFC-DELTA-BACKLOG.md)
