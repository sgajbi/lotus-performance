# API Surface

## Surface groups

`lotus-performance` exposes three major surface families:

1. analytics surfaces
2. integration surfaces
3. operator and platform surfaces

Use this page as the short navigation layer. Use the deep guides for payload detail.

## Analytics surfaces

Authoritative analytics routes:

- `POST /performance/twr`
- `POST /performance/benchmark`
- `POST /performance/mwr`
- `POST /performance/workspace-summary`
- `POST /performance/contribution`
- `POST /performance/attribution`
- `POST /performance/composites/twr`
- `POST /performance/composites/inspect`
- `POST /performance/inspections/twr`
- `POST /performance/mandate-health-context`

`POST /performance/mandate-health-context` evaluates a bounded mandate performance health context
from source-owned active-return interpretation. It preserves threshold posture and methodology
ownership; it does not grant mandate authority. lotus-gateway composes it with Lotus Manage mandate
evidence for the Workbench risk review.

`POST /performance/twr` is the supported portfolio-level TWR contract. RFC-046 response evidence
includes daily calculation evidence, source-quality supportability, and benchmark supportability.
Use [Time-Weighted Return](Time-Weighted-Return) and
[Supported Features](Supported-Features) for the implementation-backed product boundary.

TWR, MWR, Contribution, and Attribution share the `flags.fail_fast` strict-mode contract. When
`fail_fast=true`, completed responses with governed warning, fallback, diagnostic-note, degraded
supportability, or supportability-reason evidence return HTTP `422` with
`FAIL_FAST_SOFT_WARNING` instead of a `200` degraded result. Initial async `202 Accepted` envelopes
are not rejected before execution completes because warning posture is not yet known.

Async and supportability routes:

- `GET /performance/executions/{calculation_id}`
- `GET /performance/twr/results/{calculation_id}`
- `GET /performance/benchmark/results/{calculation_id}`
- `GET /performance/workspace-summary/results/{calculation_id}`
- `GET /performance/contribution/results/{calculation_id}`
- `GET /performance/attribution/results/{calculation_id}`
- `GET /performance/inspections/{inspection_id}`
- `GET /performance/inspections/{inspection_id}/artifacts/{artifact_name}`
- `GET /performance/lineage/{calculation_id}`
- `GET /performance/lineage/{calculation_id}/artifacts/{artifact_name}`

The two `…/artifacts/{artifact_name}` routes are how an artifact is actually retrieved: call the
listing route first, then request one of the artifact links it returns. Only artifacts declared by
durable lineage or inspection metadata are downloadable, and the manifest must still match durable
evidence, so an undeclared or drifted artifact name is refused rather than served.

## Integration surfaces

Cross-service and downstream-facing routes:

- `GET /integration/capabilities`
- `POST /integration/returns/series`
- `GET /integration/returns/series/results/{calculation_id}`
- `POST /integration/benchmarks/exposure-context`

`POST /performance/mwr` supports both stateless caller-owned inputs and stateful lotus-core
timeseries sourcing. In stateful mode it is the source-owned investor capital-timing methodology
surface for downstream product experiences; clients should consume its emitted MWR response and
supportability block rather than rebuilding cash-flow schedules locally. The response now carries
calculation-quality metadata (`status`, `reason_codes`, `warnings`, `fallback_reason`,
`is_approximation`) plus `holding_period_return` and XIRR convergence diagnostics so demos,
support workflows, and downstream UI panels can explain whether the value is an annualized XIRR, a
Modified Dietz fallback, Simple Dietz result, or not calculable.
Current MWR inputs must be in one reporting currency. `cashflows_used` remains the legacy
calculation-schedule echo. Stateless callers may supply complete
`source_preconverted_fx_evidence`; lotus-performance validates it against the supplied
reporting-currency schedule and emits `currency_evidence` with per-input FX provenance. Stateful
responses also carry `reporting_currency` and `currency_evidence`, including beginning/ending
market values, source cash-flow components, bounded `source_cashflow_quality` inclusion/exclusion
counts, and source transaction/event lifecycle identity when supplied upstream. Cash-flow dates are
validated against the resolved measurement window before calculation; out-of-window input is
rejected with `MWR_CASH_FLOW_OUT_OF_WINDOW`. Dietz annualization honors explicit
`periods_per_year` first and then the selected day-count convention, including `BUS/252`.
Single-currency stateful responses emit `not_required_single_currency_inputs` when source and
reporting currencies match. Cross-currency stateful responses keep the explicit
`upstream_preconverted_missing_per_input_fx_metadata` posture.
Stateful upstream FX-aware MWR is still contract-gated by
[docs/technical/mwr-fx-contract-design.md](../docs/technical/mwr-fx-contract-design.md), and
downstream consumers must not infer missing FX rates or conversion policy when those fields are
absent.

`POST /performance/contribution` supports both stateless caller-owned inputs and stateful lotus-core
portfolio/position timeseries sourcing. In stateful mode it is the source-owned contribution
methodology surface for downstream product experiences; clients should consume emitted total,
local, and FX contribution results rather than reconstructing contribution downstream. RFC-047 also
emits `smoothing_evidence` and `source_economics_evidence`; Gateway preserves those fields and
Workbench displays exact contribution evidence statuses in Performance Drivers. See
[Contribution Analytics](Contribution-Analytics) for the implementation-backed product boundary.

`POST /performance/attribution` supports both stateless caller-owned inputs and stateful lotus-core
portfolio/position, benchmark, and source currency sourcing. In stateful mode it is the source-owned
attribution methodology surface for downstream product experiences; clients should consume emitted
allocation, selection, interaction, active-return, and currency-attribution results rather than
reconstructing attribution downstream. Period `status`, `reason_codes`, `residual_materiality`, and
`supportability_evidence` are part of the contract, including invalid linked-return-chain posture
when linked attribution is requested across a period return less than or equal to `-100%`. See
[Attribution Analytics](Attribution-Analytics) and
[docs/technical/attribution-documentation-map.md](../docs/technical/attribution-documentation-map.md)
for the implementation-backed product boundary and documentation routing.

`POST /performance/composites/twr` calculates asset-weighted composite TWR from persisted
member-return facts. It is intentionally not an ad hoc request-time member-return upload surface and
does not fan out into hidden member portfolio TWR calculations. `POST /performance/composites/inspect`
uses the same persisted facts to generate supportability findings and classified artifacts for
operations, audit, and client-evidence preparation. See [Composite Performance](Composite-Performance)
and [docs/technical/composite-performance-documentation-map.md](../docs/technical/composite-performance-documentation-map.md)
for the implementation-backed boundary.

`GET /integration/capabilities` advertises `composite_twr` as a separate persisted-member-facts
surface. It does not change the portfolio-level `twr` surface and does not advertise composite
contribution, composite attribution, composite MWR, benchmark active return, or special composite
structures.

## Operator and platform surfaces

Runtime and supportability routes:

- `GET /`
- `GET /version`
- `GET /health`
- `GET /health/live`
- `GET /health/ready`
- `GET /metrics`
- `GET /integration/runtime-status`
- `GET /integration/runtime-work-items`
- `GET /integration/runtime-recoveries`
- `GET /integration/recovery-drills`
- `POST /integration/recovery-drills/run`
- `GET /integration/runtime-retention-cleanups`
- `POST /integration/runtime-retention-cleanups/run`

`GET /version` returns support-safe build metadata for correlating the running service to its Git
commit, OCI image labels, SBOM, vulnerability and provenance evidence — the first call when
confirming which build is actually serving traffic. `GET /` returns the service entry message and
the same build identity, and points callers to `/docs`.

The service serves **37 routes** in the generated OpenAPI document. `/docs`,
`/docs/oauth2-redirect`, `/openapi.json` and `/redoc` are served but deliberately excluded from the
schema, so they appear in neither the document nor this page's counts.

## Where to go next

- TWR product and methodology navigation:
  [Time-Weighted Return](Time-Weighted-Return),
  [docs/technical/twr-documentation-map.md](../docs/technical/twr-documentation-map.md)
- Attribution product and methodology navigation:
  [Attribution Analytics](Attribution-Analytics),
  [docs/technical/attribution-documentation-map.md](../docs/technical/attribution-documentation-map.md)
- Composite product and methodology navigation:
  [Composite Performance](Composite-Performance),
  [docs/technical/composite-performance-documentation-map.md](../docs/technical/composite-performance-documentation-map.md)
- contract and payload detail:
  [docs/guides/api_reference.md](../docs/guides/api_reference.md)
- full examples and config inventory:
  [docs/guides/complete_service_reference.md](../docs/guides/complete_service_reference.md)
- demo API certification:
  `make demo-api-certification`,
  [docs/guides/demo_readiness.md](../docs/guides/demo_readiness.md)
- Lotus MWR production controls and review findings:
  [docs/guides/mwr-lotus-production-controls.md](../docs/guides/mwr-lotus-production-controls.md),
  [docs/technical/mwr-industry-review-findings.md](../docs/technical/mwr-industry-review-findings.md),
  [docs/technical/mwr-fx-contract-design.md](../docs/technical/mwr-fx-contract-design.md)
- runtime behavior and readiness:
  [Operations Runbook](Operations-Runbook)
- upstream contract boundary:
  [Integrations](Integrations)
