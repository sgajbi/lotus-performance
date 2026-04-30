# TWR Endpoint Certification

This note records the current certification state for `POST /performance/twr` before moving to the
next performance endpoint.

## Endpoint Purpose

`POST /performance/twr` is the authoritative lotus-performance contract for portfolio
time-weighted return. Use it when external cash flows must be neutralized and investment return must
be geometrically linked across one or more requested analysis windows.

Use this endpoint for:

- private-banking portfolio performance reporting;
- net and gross portfolio TWR;
- benchmark-aware TWR and active return;
- daily, weekly, monthly, quarterly, and yearly breakdowns;
- stateless caller-supplied valuation points;
- stateful lotus-core-sourced analytics inputs.

Do not use this endpoint for:

- source-quality triage. Use `POST /performance/inspections/twr`;
- canonical return-series sourcing for another analytics engine. Use `POST /integration/returns/series`;
- money-weighted return. Use `POST /performance/mwr`;
- contribution or attribution decomposition. Use the owned contribution and attribution endpoints.

## Supported Request Options

Validated option families:

- `input_mode="stateful"` with `stateful_input={}`;
- `input_mode="stateless"` with either top-level `valuation_points` or
  `stateless_input.valuation_points`;
- `metric_basis="NET"` and `metric_basis="GROSS"`;
- `period` values including `MTD`, `QTD`, `YTD`, `EXPLICIT`, `1Y`, and `ITD`;
- `frequencies` including `daily`, `weekly`, `monthly`, and `quarterly`;
- multi-analysis requests, for example `YTD` plus `MTD` in one request;
- `include_benchmark=true` with stateful benchmark assignment;
- stateless benchmark input with calculated component returns;
- stateless benchmark input with vendor return series;
- async `202 Accepted` result polling through `/performance/twr/results/{calculation_id}`;
- validation failures for missing stateful envelopes, conflicting stateless input styles, missing
  stateless benchmark configuration, empty frequencies, unsupported extra inputs, and missing
  explicit-window start dates.

## Supportability and Observability

`POST /performance/twr` now emits source-owned supportability posture on successful synchronous
responses through `calculation_supportability`. The block uses bounded state, reason, and freshness
vocabularies so Gateway and Workbench can distinguish a ready calculation from stale or empty source
posture without parsing prose diagnostics.

The Prometheus metric is:

`lotus_performance_calculation_supportability_total{operation,supportability_state,reason,freshness_bucket}`

Implemented operation scope now includes `operation="twr"`, `operation="mwr"`,
`operation="contribution"`, and `operation="attribution"` for completed synchronous calculations
and completed async result payloads. Workspace summary, benchmark, and returns-series
supportability remain separate implementation work and must not be inferred from this endpoint
proof.

## Downstream Consumers

Current downstream consumers are:

| Consumer | How it uses TWR | Evidence |
| --- | --- | --- |
| `lotus-gateway` Workbench overview/foundation routes | Calls `LotusAnalyticsClient.get_stateful_twr` and `get_twr_analytics`, which POST to `/performance/twr` and poll async results. | `lotus-gateway/src/app/clients/lotus_analytics_client.py`; `lotus-gateway/tests/unit/test_upstream_clients.py` |
| `lotus-gateway` performance workspace routes | Builds UI-facing performance summary, details, horizon-comparison, and attribution-trend contracts from lotus-performance TWR and workspace-summary calls. | `lotus-gateway/src/app/services/performance_workspace_service.py`; `lotus-gateway/src/app/routers/workbench.py` |
| `lotus-gateway` platform capabilities | Uses `performance.analytics.twr` to decide whether performance workspace navigation is available. | `lotus-gateway/src/app/services/platform_capabilities_service.py` |
| `lotus-risk` stateful risk analytics | Does not call `/performance/twr` directly. It consumes `POST /integration/returns/series`, which is the correct performance-owned return-series contract for risk engines. | `lotus-risk/src/app/integrations/lotus_performance_client.py`; `lotus-risk/docs/domain-apis/RFC-0082-upstream-contract-family-map.md` |

Gateway runtime probes through `http://gateway.dev.lotus` returned `200` for:

- `/api/v1/workbench/PB_SG_GLOBAL_BAL_001/performance/summary`;
- `/api/v1/workbench/PB_SG_GLOBAL_BAL_001/performance/details`;
- `/api/v1/workbench/PB_SG_GLOBAL_BAL_001/risk/summary`;
- `/api/v1/workbench/PB_SG_GLOBAL_BAL_001/risk/drawdown`.

The host ports `8000` and `8001` are not gateway in the current local stack; gateway is exposed
through the `gateway.dev.lotus` ingress alias.

## Upstream Integration

Stateful TWR sources portfolio analytics inputs from lotus-core query-control-plane through
`CORE_CONTROL_PLANE_BASE_URL`, not the lotus-core query-service read plane.

Required lotus-core contracts:

- `POST /integration/portfolios/{portfolio_id}/analytics/reference`;
- `POST /integration/portfolios/{portfolio_id}/analytics/portfolio-timeseries`;
- `POST /integration/portfolios/{portfolio_id}/analytics/position-timeseries` for inspector,
  contribution, attribution, and reconciliation use cases.

The upstream integration is correct for the control-plane contract and carries useful lineage and
async execution metadata. The performance engine continues to return results for the input it
receives; source diagnostics stay in the separate TWR inspector.

Performance improvement opportunities:

- keep using async execution for long-window stateful workloads;
- avoid exposing unsupported long history as a clean UI period without an inspection gate;
- consider caching/reusing source windows only after retrieval-shape evidence shows repeated
  same-window demand from gateway or risk.

## Domain Certification Result

For canonical portfolio `PB_SG_GLOBAL_BAL_001` as of `2026-04-10`, the following windows are
domain-safe for UI integration based on current evidence:

| Window | Result |
| --- | --- |
| `YTD`, NET | `1.2152137301822075%`, daily/monthly breakdowns, max daily absolute move about `0.030546%` |
| `YTD`, GROSS | `1.2359023665067692%`, gross exceeds net as expected from fee drag |
| `MTD` | `0.10506363961935161%` |
| `QTD` | `0.10506363961935161%` |
| `EXPLICIT 2026-03-01..2026-04-10` | `0.3874271363699222%` |
| `YTD` with benchmark | portfolio `1.2152137301822075%`, benchmark `5.095680231948784%`, active `-3.880466501766577%` |

The same endpoint mechanically supports `1Y` and `ITD`, but long-window results are not front-office
safe for this canonical portfolio yet. Current source history produces nonpositive capital-base days
and extreme daily moves in older 2025 data. The TWR inspector correctly reports `not_supportable`
for that long-window calculation, including:

- `NONPOSITIVE_DAILY_CAPITAL_BASE_DETECTED`;
- `EXTREME_DAILY_MOVE_DETECTED`;
- `PORTFOLIO_BREAKDOWN_LINK_MISMATCH`;
- `WEEKEND_OBSERVATIONS_PRESENT`.

Until the historical source economics are fixed or the UI gates long-window periods through the
inspector, enable `YTD`, `MTD`, `QTD`, and clean explicit windows for `PB_SG_GLOBAL_BAL_001`; hide or
guard `1Y`, `ITD`, `3Y`, and `5Y`.

Certification caveat: long-window results are not front-office safe for this canonical portfolio
without an inspector gate.

## Swagger Readiness

Swagger now documents:

- endpoint purpose and when to use TWR;
- `202 Accepted` async response for `POST /performance/twr`;
- result polling behavior for `GET /performance/twr/results/{calculation_id}`;
- TWR inspection purpose and async result behavior;
- field-level descriptions and examples for all schemas reachable from the TWR operations.

OpenAPI audit artifacts:

- `artifacts/twr-api-certification-2026-04-10/twr-openapi-certification-after-doc-fix.json`;
- `artifacts/twr-api-certification-2026-04-10/twr-openapi-paths-after-doc-fix.json`.

Live validation artifacts:

- `artifacts/twr-api-option-matrix-2026-04-10/summary.json`;
- `artifacts/twr-api-option-matrix-2026-04-10/summary-extra-period-validation.json`;
- `artifacts/gateway-risk-integration-2026-04-10/gateway-ingress-summary.json`.

## Test Pyramid Assessment

The TWR endpoint has production-grade coverage across the test pyramid:

Response attribute-level certification is covered in
`docs/technical/twr-mwr-response-attribute-certification.md` and
`tests/integration/test_response_attribute_certification.py`. That pass checks emitted TWR response
fields, nested period/breakdown attributes, metadata, diagnostics, audit counts, optional-field
omission, and independently recomputed daily/cumulative return math.

| Layer | Coverage | Assessment |
| --- | --- | --- |
| Model and validation tests | Request mode validation, stateless-vs-stateful exclusivity, benchmark inclusion rules, empty frequencies, explicit-window validation, and extra-field rejection. | Strong. These tests protect client-facing contract semantics before engine execution. |
| Engine and service tests | TWR linking, reset behavior, multi-currency behavior, benchmark-aware output, valuation normalization, source-quality inspection, source-economics inspection, and reconciliation checks. | Strong. These tests cover financial behavior and the inspector’s supportability findings. |
| Integration tests | `/performance/twr`, async result retrieval, execution lineage, stateful source resolution, benchmark-aware TWR, returns-series tie-out, contribution tie-out, and inspector execution. | Strong. These tests protect route-level behavior and cross-surface consistency inside lotus-performance. |
| Documentation and OpenAPI tests | Public docs contract, OpenAPI enrichment, OpenAPI quality gate, API vocabulary inventory, and TWR-specific async Swagger regression. | Strong after this pass. Swagger now advertises the runtime 202 path and result polling semantics. |
| Cross-repo consumer tests | `lotus-gateway` upstream client and performance workspace tests; `lotus-risk` performance-client and stateful risk adapter tests. | Strong for known consumers. Gateway calls `/performance/twr`; risk correctly consumes `/integration/returns/series` instead of duplicating TWR. |
| Live canonical probes | Stateful canonical TWR, TWR option matrix, inspector probe, gateway Workbench performance routes, and gateway risk routes for `PB_SG_GLOBAL_BAL_001`. | Adequate for endpoint certification, with a governed caveat on long-window historical source quality. |

Current residual test gap:

- long-window UI gating should be verified at the downstream product surface if Workbench exposes `1Y`,
  `ITD`, `3Y`, or `5Y` for `PB_SG_GLOBAL_BAL_001`. The performance endpoint and inspector already
  expose the needed signals; the downstream UI must not present unsupported long-window results as
  clean front-office performance.

Downstream issue `lotus-gateway#108` tracks this product-surface gap for Workbench horizon
comparison. Until that issue is resolved, TWR remains certified at the lotus-performance endpoint
boundary with the governed caveat that long-window front-office presentation must be inspector-gated.

## Validation Commands

Focused checks run during this certification pass:

```bash
python -m pytest tests/unit/app/test_twr_openapi_contract.py tests/unit/app/test_openapi_enrichment.py tests/unit/docs/test_public_docs_contract.py -q
python -m ruff check app/api/endpoints/performance.py app/api/endpoints/inspections.py tests/unit/app/test_twr_openapi_contract.py
python -m ruff format --check app/api/endpoints/performance.py app/api/endpoints/inspections.py tests/unit/app/test_twr_openapi_contract.py
python scripts/openapi_quality_gate.py
python scripts/api_vocabulary_inventory.py --validate-only
```

Additional cross-repo focused checks:

```bash
# lotus-gateway
PYTHONPATH=src python -m pytest tests/unit/test_upstream_clients.py -q

# lotus-risk
PYTHONPATH=src python -m pytest tests/unit/test_lotus_performance_client.py tests/unit/test_risk_mode_adapter_characterization.py tests/unit/test_drawdown_mode_adapter.py tests/unit/test_rolling_mode_adapter.py tests/unit/test_attribution_mode_adapter.py -q
```
