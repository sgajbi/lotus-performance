# Integration Capabilities Endpoint Certification

This note records the certification state for `GET /integration/capabilities`.

## Purpose And Ownership

`GET /integration/capabilities` is the lotus-performance-owned discovery contract for downstream
Lotus services. It advertises supported analytics surfaces, feature flags, workflow readiness,
stateful/stateless execution posture, async polling paths, endpoint-specific result paths, and
surface-level restrictions.

Use this endpoint when gateway, Workbench orchestration, platform capability aggregation, or another
Lotus service needs to know what lotus-performance supports. Do not infer capability state from UI
hardcoding or from the existence of a route alone.

This endpoint is integration-facing. It does not calculate performance and does not read lotus-core.
It publishes lotus-performance policy and contract posture.

## Request Contract

Canonical query controls:

| Query parameter | Meaning |
| --- | --- |
| `consumer_system` | Downstream consumer system requesting the capability view. |
| `tenant_id` | Tenant or policy scope. |
| `feature_limit` | Maximum feature rows returned, bounded to `1..500`. |
| `workflow_limit` | Maximum workflow rows returned, bounded to `1..200`. |

Supported `consumer_system` values include `lotus-gateway`, `lotus-performance`, `lotus-risk`,
`lotus-manage`, `lotus-workbench`, `lotus-report`, `lotus-advise`, `UI`, and `UNKNOWN`.

## Output Contract

The response returns:

| Field | Meaning |
| --- | --- |
| `contract_version` | Version of the capabilities response contract. |
| `source_service` | Emitting service, currently `lotus-performance`. |
| `consumer_system` | Resolved consumer query value. |
| `tenant_id` | Resolved tenant query value. |
| `generated_at` | UTC generation timestamp. |
| `as_of_date` | Business date used for capability context. |
| `policy_version` | `PA_POLICY_VERSION` or the service default. |
| `supported_input_modes` | Service-level stateful/stateless mode availability. |
| `analytics_surfaces[]` | Endpoint-level surface metadata. |
| `features[]` | Feature capability flags. |
| `workflows[]` | Higher-level workflow readiness flags. |

Every `analytics_surfaces[]` row includes:

- `key`
- `path`
- `enabled`
- `supported_input_modes`
- `supports_async`
- `poll_path_template`
- `result_path_template`
- `stateful_restrictions`
- `contract_notes`
- `options`

Certified surface keys:

- `twr`
- `twr_inspection`
- `mwr`
- `benchmark`
- `workspace_summary`
- `contribution`
- `attribution`
- `composite_twr`
- `mandate_performance_health_context`
- `returns_series`
- `benchmark_exposure_context`

`performance.observability.calculation_supportability` is the shared feature key for the
implemented TWR, MWR, contribution, attribution, and returns-series supportability metric posture.
It remains enabled when any of those calculation or integration surfaces is enabled; disabling only
TWR must not hide supportability posture for MWR, contribution, attribution, or returns-series.

## Behavior And Feature Controls

Environment controls:

| Variable | Effect |
| --- | --- |
| `PA_CAP_TWR_ENABLED` | Enables TWR and TWR inspection feature/surface posture. |
| `PA_CAP_MWR_ENABLED` | Enables MWR posture. |
| `PA_CAP_CONTRIBUTION_ENABLED` | Enables contribution posture. |
| `PA_CAP_ATTRIBUTION_ENABLED` | Enables attribution posture. |
| `PA_CAP_BENCHMARK_ENABLED` | Enables benchmark and benchmark exposure context posture. |
| `PA_CAP_WORKSPACE_SUMMARY_ENABLED` | Enables workspace-summary posture. |
| `PA_CAP_COMPOSITE_TWR_ENABLED` | Enables persisted-fact composite TWR posture. |
| `PLATFORM_INPUT_MODE_STATEFUL_ENABLED` | Adds or removes stateful mode from applicable surfaces. |
| `PLATFORM_INPUT_MODE_STATELESS_ENABLED` | Adds or removes stateless mode from applicable surfaces. |
| `PA_POLICY_VERSION` | Sets the response `policy_version`. |

The endpoint returns empty `supported_input_modes` for `twr_inspection` because inspection subjects are
not selected through the normal analytics input-mode envelope.

`benchmark_exposure_context` advertises only `stateful` because it is a performance-owned integration
view over lotus-core benchmark lineage.

`composite_twr` advertises `persisted_member_facts` because it calculates only from materialized
composite member-return facts. It does not change the portfolio-level `twr` surface and does not
advertise ad hoc member uploads, hidden request-time member TWR fan-out, composite contribution,
composite attribution, composite MWR, benchmark active return, or special composite structures.

`mandate_performance_health_context` advertises only `stateless` because it publishes bounded,
lotus-performance-owned active-return health posture for lotus-manage DPM supportability. It does
not create mandate actions, rebalance waves, client communications, orders, OMS, or execution
instructions.

## Upstream Integration

There is no runtime upstream call in this endpoint. Capability state is assembled from
lotus-performance configuration and owned contract knowledge.

The endpoint must stay aligned with the real upstream posture of individual analytics surfaces. For
stateful analytics-input surfaces, the advertised endpoints rely on lotus-core query-control-plane
contracts through `CORE_CONTROL_PLANE_BASE_URL`, not query-service read-plane routes.

## Downstream Consumers

Known direct downstream consumer:

| Consumer | Current behavior | Certification outcome |
| --- | --- | --- |
| `lotus-gateway` | `LotusAnalyticsClient.get_capabilities` calls `/integration/capabilities` with canonical `consumer_system` and `tenant_id` query parameters. | Source/test-level downstream evidence is current: `lotus-gateway` commit `11d12d5` closed `lotus-gateway#109`; local Gateway source shows `src/app/clients/lotus_analytics_client.py` builds `consumer_system` and `tenant_id`, and `tests/unit/test_upstream_clients.py` covers non-default `lotus-workbench` / `tenant-a` propagation. No fresh live cross-repo runtime proof was run in this slice. |

Other Lotus apps expose their own `/integration/capabilities` endpoints or reference the pattern in
docs, but no direct call from `lotus-risk`, `lotus-workbench`, `lotus-report`, `lotus-advise`, or
`lotus-manage` to this lotus-performance endpoint was found during this slice.

No duplicate lotus-performance endpoint was found. This endpoint remains strategic for service-owned
capability discovery.

## GitHub Issue Posture

Open issue searches were run for lotus-performance and lotus-gateway using capabilities and
analytics-surface terms.

Results:

- no open lotus-performance issue was found for this endpoint;
- downstream issue `lotus-gateway#109` is closed. The Gateway fix landed in commit `11d12d5` and
  the current Gateway client sends canonical `consumer_system` and `tenant_id` query parameters.
  Retain this note as source/test-level downstream evidence, not as a live cross-repo runtime proof.

## Swagger Readiness

Swagger now documents:

- endpoint purpose;
- canonical query controls and bounds;
- supported consumer-system values;
- every response-model field with descriptions and examples;
- endpoint-level surface metadata fields;
- capability example payload through `docs/examples/integration_capabilities_response.json`.

## Test Pyramid Assessment

| Layer | Coverage | Assessment |
| --- | --- | --- |
| Model/schema | Pydantic response models define feature, workflow, surface, option, and top-level capability fields with examples. | Strong for Swagger consumers. |
| Integration route tests | Default contract, env overrides, canonical query controls, limit guardrails, every advertised surface, headers, and feature/workflow slices. | Strong for endpoint behavior. |
| Docs/OpenAPI | Public docs regression covers the example payload and this certification document; OpenAPI quality and vocabulary gates cover schema metadata. | Strong after this pass. |
| Downstream | Gateway direct client and unit-test evidence were reviewed after `lotus-gateway#109` closed. | Adequate source/test-level proof: current Gateway code sends canonical `consumer_system` and `tenant_id`; no new live cross-repo runtime proof was run in this slice. |
| Live proof | A local TestClient proof showed canonical snake_case query controls apply non-default consumer/tenant values. | Adequate for this config-only endpoint. |

## Validation Commands

Focused validation for this certification slice:

```bash
python -m pytest tests/unit/models/test_integration_capabilities_models.py tests/integration/test_integration_capabilities_api.py tests/unit/docs/test_public_docs_contract.py -q
python scripts/openapi_quality_gate.py
python scripts/api_vocabulary_inventory.py --validate-only
python -m ruff check app/api/endpoints/integration_capabilities.py tests/integration/test_integration_capabilities_api.py tests/unit/docs/test_public_docs_contract.py tests/unit/models/test_integration_capabilities_models.py
python -m ruff format --check app/api/endpoints/integration_capabilities.py tests/integration/test_integration_capabilities_api.py tests/unit/docs/test_public_docs_contract.py tests/unit/models/test_integration_capabilities_models.py
python -m mypy --config-file mypy.ini app/api/endpoints/integration_capabilities.py
```
