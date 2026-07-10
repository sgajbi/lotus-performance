# Lineage Endpoint Certification

This note records the certification state for:

- `GET /performance/lineage/{calculation_id}`
- `GET /performance/lineage/{calculation_id}/artifacts/{artifact_name}`

## Purpose And Ownership

The lineage endpoints are lotus-performance-owned reproducibility and supportability contracts.
They expose durable calculation evidence after analytics execution and lineage materialization.

Use `GET /performance/lineage/{calculation_id}` when support, operations, or a downstream front-office
evidence surface needs to know whether lineage is pending, complete, or failed and which artifacts
are available for download.

Use `GET /performance/lineage/{calculation_id}/artifacts/{artifact_name}` to download a declared
artifact through a controlled route bound to both calculation id and artifact name.

Do not use the lineage endpoints as calculation result endpoints. Analytics results remain on TWR,
MWR, benchmark, workspace-summary, returns-series, contribution, attribution, and their
endpoint-specific async result routes.

## Request Contract

`GET /performance/lineage/{calculation_id}`:

| Path parameter | Meaning |
| --- | --- |
| `calculation_id` | Durable calculation identifier returned by an analytics endpoint. |

`GET /performance/lineage/{calculation_id}/artifacts/{artifact_name}`:

| Path parameter | Meaning |
| --- | --- |
| `calculation_id` | Durable calculation identifier returned by an analytics endpoint. |
| `artifact_name` | Artifact filename declared by completed lineage metadata. |

The artifact route intentionally accepts filenames, not arbitrary paths. Unsafe path forms are
rejected by lineage artifact filename validation before storage paths are resolved.

## Output Contract

The lineage inventory response model is `app.models.lineage_responses.LineageResponse`.

| Field | Meaning |
| --- | --- |
| `calculation_id` | Durable calculation handle. |
| `calculation_type` | Analytics family that produced the lineage payload. |
| `timestamp_utc` | Durable lineage timestamp or completed manifest timestamp. |
| `status` | Durable materialization status: `pending`, `complete`, or `failed`. |
| `artifacts` | Map keyed by artifact filename. Values contain controlled service-owned download URLs plus classification, intended audience, sensitivity, minimization posture, retention category, and redaction requirement metadata. |
| `error_message` | Failure message when lineage materialization failed. |

The artifact download route returns file content with a `Content-Disposition` filename for successful
downloads. JSON error payloads are returned for missing, undeclared, or degraded artifacts.

## Integrity And Error Behavior

Certified behavior:

- missing lineage record returns `404`;
- pending lineage returns `200` with `status=pending` and empty `artifacts`;
- failed lineage returns `200` with `status=failed`, empty `artifacts`, and `error_message`;
- complete lineage requires `manifest.json` to exist;
- manifest JSON must be readable, structurally valid, and consistent with durable metadata;
- manifest `artifacts` metadata must exactly match `artifact_names` and use known governed
  classifications;
- complete lineage requires every declared artifact to exist on disk before URLs are returned;
- unknown artifact names return `404`;
- artifact downloads require completed lineage status;
- missing, invalid, inconsistent, or incomplete lineage storage returns `503`;
- unexpected retrieval failures return `500` with a bounded error detail.

This is intentionally stricter than a raw file listing. The endpoint must not advertise complete
lineage if durable metadata, manifest content, or on-disk artifacts disagree.

## Artifact Classification And Sharing

Lineage artifact inventory is classification-bearing, not filename-only. Operators must use the
metadata returned by `GET /performance/lineage/{calculation_id}` before sharing any artifact outside
the operations/support boundary.

Current governed classes:

| Artifact family | Access classification | Intended audience | Sensitivity | Minimization posture | Retention category | External sharing |
| --- | --- | --- | --- | --- | --- | --- |
| `request.json`, `response.json` | `operator_only` | `operations` | `raw_sensitive_payload` | `raw_payload_full_fidelity` | `lineage_raw_payload` | Redaction or transformation required before customer sharing. |
| Derived detail artifacts such as `daily_results.csv` | `operator_only` | `operations` | `derived_evidence` | `derived_detail_minimized` | `lineage_detail_evidence` | Redaction or transformation required before customer sharing. |
| Explicit support packs such as `support_brief.md` | `customer_consumable` | `customer` | `customer_safe_summary` | `customer_safe_transformed` | `lineage_support_pack` | May be shared as the customer-facing artifact when deliberately produced. |

No raw lineage file becomes customer-consumable by inference. Customer-facing evidence must be an
explicit transformed artifact with `customer_consumable` metadata.

## Upstream Integration

The lineage endpoints do not call lotus-core or other upstream services at request time. They read
lotus-performance durable lineage metadata and lineage artifact storage.

For stateful calculations, lineage artifacts capture the resolved request and response that
lotus-performance used after sourcing from lotus-core query-control-plane contracts. The lineage
surface therefore provides reproducibility evidence for the performance calculation without making
lotus-core a performance-result authority.

## Downstream Consumers

Known current consumers:

| Consumer | Current behavior | Certification outcome |
| --- | --- | --- |
| `lotus-performance` TWR inspection | Includes related lineage paths for existing-calculation inspections. | Correctly uses lineage as source evidence, not as a calculation result. |
| `lotus-performance` runtime work-item/recovery endpoints | Emit `lineage_path` drilldowns for operator triage. | Correctly points operators to the strategic lineage endpoint. |
| `lotus-workbench` via `lotus-gateway` | Evidence mode exists, but gateway currently marks evidence unavailable. | Downstream issue `lotus-gateway#110` tracks exposing execution and lineage evidence through gateway so Workbench can enable the existing evidence mode. |

No direct `lotus-risk`, `lotus-report`, `lotus-advise`, or `lotus-manage` call to the lineage
endpoint was found during this slice.

No duplicate lotus-performance lineage endpoint was found. The older broad static-file serving model
has already been replaced by this controlled calculation/artifact route.

## GitHub Issue Posture

Open issue searches were run for lotus-performance, lotus-gateway, and lotus-risk using lineage,
artifact, manifest, and evidence terms.

Results:

- no lineage-endpoint-specific lotus-performance issue was found;
- downstream issue `lotus-gateway#110` was opened because gateway/workbench still treat performance
  evidence as unavailable even though lotus-performance owns certified execution and lineage
  evidence contracts;
- lotus-performance issue `#83` remains a broad historical stateful-sourcing architecture issue and
  is not closed by this lineage endpoint certification slice.

## Swagger Readiness

Swagger now documents:

- lineage inventory route purpose;
- artifact download route purpose;
- `calculation_id` and `artifact_name` path parameters;
- 404 and 503 behavior;
- `LineageResponse` and `ArtifactLink` field descriptions and examples;
- artifact route as part of the public reproducibility and supportability contract.

## Test Pyramid Assessment

| Layer | Coverage | Assessment |
| --- | --- | --- |
| Model/schema | `tests/unit/app/test_lineage_openapi_contract.py` verifies lineage route, artifact route, and response schema documentation. | Strong after this pass. |
| Service/unit | `tests/unit/services/test_lineage_service.py` covers materialization, atomic writes, manifest/metadata sync, runtime storage path resolution, and unsafe filename rejection. | Strong for artifact production and safety. |
| Integration route tests | `tests/integration/test_lineage_api.py` covers end-to-end lineage capture/retrieval, stateful resolved request capture, benchmark resolved request capture, pending/failed states, 404, 503, controlled artifact download, unknown artifact rejection, missing manifest, inconsistent manifest, and missing artifact files. | Strong for endpoint behavior. |
| Docs/OpenAPI | Public docs regression covers API reference, complete service reference, reproducibility guide, and this certification document. OpenAPI and vocabulary gates validate schema metadata. | Strong after this pass. |
| Downstream | Gateway evidence gap is filed as `lotus-gateway#110`. | Adequate with tracked follow-up. |

## Validation Commands

Focused validation for this certification slice:

```bash
python -m pytest tests/unit/app/test_lineage_openapi_contract.py tests/integration/test_lineage_api.py tests/unit/services/test_lineage_service.py tests/unit/docs/test_public_docs_contract.py -q
python scripts/openapi_quality_gate.py
python scripts/api_vocabulary_inventory.py --validate-only
python -m ruff check app/api/endpoints/lineage.py app/models/lineage_responses.py tests/unit/app/test_lineage_openapi_contract.py tests/integration/test_lineage_api.py tests/unit/services/test_lineage_service.py tests/unit/docs/test_public_docs_contract.py
python -m ruff format --check app/api/endpoints/lineage.py app/models/lineage_responses.py tests/unit/app/test_lineage_openapi_contract.py tests/integration/test_lineage_api.py tests/unit/services/test_lineage_service.py tests/unit/docs/test_public_docs_contract.py
python -m mypy --config-file mypy.ini app/api/endpoints/lineage.py app/models/lineage_responses.py app/services/lineage_service.py
```
