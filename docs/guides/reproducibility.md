 
# Reproducibility & Data Lineage

To ensure all calculations are transparent, auditable, and perfectly reproducible, the analytics engine includes a powerful data lineage and hashing framework. This allows you to verify that a given request will always produce the same result and provides a mechanism to inspect all intermediate calculation steps.

---
## Calculation Hash

Every API response from a primary calculation endpoint (TWR, MWR, etc.) includes a `calculation_hash` in the `meta` block.

```json
"meta": {
  "calculation_id": "a4b7e289-7e28-4b7e-8e28-7e284b7e8e28",
  "calculation_hash": "sha256:5a2c...",
  "input_fingerprint": "sha256:b3e1...",
  "engine_version": "0.5.0"
}
````

  * **`input_fingerprint`**: A unique SHA256 hash of the canonical representation of your request payload. Object keys are sorted before hashing, but arrays remain order-sensitive because fields such as `valuation_points`, cash flows, benchmark observations, period requests, and lineage rows can carry source sequence, business ordering, or evidence ordering semantics. Reordering an array changes the fingerprint unless a specific API mapper documents and applies schema-aware business-key sorting before the hash is built.
  * **`calculation_hash`**: A hash that combines the `input_fingerprint` with the `engine_version`. If the underlying calculation logic changes in a new version, this hash will change, guaranteeing a link between a specific request, a specific engine version, and a specific result.

### Canonical payload ordering

The current canonicalization contract sorts object keys and preserves array order. This makes
hashing deterministic without guessing which JSON arrays are mathematical sets and which are
ordered economic evidence. Callers that expect stable hash identity should submit arrays in the
business order required by the endpoint, for example chronological valuation or cash-flow order
where the request schema expects a time series.

Do not add global list sorting to `core/repro.py`. Order-insensitive behavior must be introduced
only as a field-specific, schema-aware request-mapping rule with tests that name the stable business
key and prove that the calculation output and evidence contract remain unchanged.

### Calculation engine version governance

Calculation hashes use the governed calculation engine version token, not the deployable build
version. In other words, the calculation engine version is not the deployable build version. The
current source is `Settings.CALCULATION_ENGINE_VERSION`, which defaults to
`lotus-performance-calculation-engine.v1` and is exposed through the same helper for TWR, MWR,
contribution, attribution, benchmark, workspace-summary, TWR inspection, and returns-series hash
paths. The token is intentionally separate from `APP_VERSION`, Git SHA, OCI image labels, image
digest, CI run id, and `/version` build metadata.

Change `CALCULATION_ENGINE_VERSION` when methodology, calculation logic, canonicalization,
compatibility semantics, or governed reproducibility behavior changes in a way that should create a
new calculation identity for the same economic input. Do not change it merely because the service is
rebuilt, retagged, promoted across environments, or receives a non-methodology runtime patch.

The lightweight gate `make calculation-engine-version-gate` runs in `make lint` and fails if
production calculation code uses `APP_VERSION` for hash identity or reintroduces legacy per-family
literal tokens such as `returns-series-v1`.

-----

## Data Lineage & Drill-Down

The engine automatically captures a detailed record of every calculation, allowing you to "drill down" into the intermediate data for auditing or debugging.

### Asynchronous Capture

To avoid coupling API latency to artifact materialization, lineage capture is handled through
durable metadata plus a dedicated lineage worker.

The API request path persists lineage payload metadata first. Artifact materialization then
runs asynchronously in the lineage worker. This means there may be a short delay before
lineage artifacts for a new `calculation_id` become available, but the work is not dependent
on in-process background tasks.

Execution polling treats this evidence production as part of the lifecycle contract. For workflows
that start a mandatory lineage or artifact materialization stage, `/performance/executions/{calculation_id}`
remains `running` while that stage is `in_progress`, becomes `complete` only after the worker marks
evidence materialization complete, and becomes `failed` if the worker exhausts the materialization
retry budget.

Materialized lineage includes a `manifest.json` artifact that carries the calculation type,
completion timestamp, status, artifact inventory, and per-artifact classification metadata. The
lineage read path validates that manifest against the durable metadata record before returning
lineage as complete, so a stale or partially corrupted manifest degrades cleanly instead of silently
drifting from the DB-backed audit record.

The same integrity check applies to artifact downloads. The service will not serve a declared
artifact if the lineage manifest is missing, unreadable, invalid, or inconsistent with durable
metadata, and it will surface a distinct degraded response if the artifact is declared but no
longer present on disk.

The lineage status route also verifies that every artifact declared as part of a complete
calculation is physically present before it returns download URLs. That prevents the control
plane from advertising “complete” lineage when the persisted artifact set has already drifted
or partially disappeared. Raw `request.json` and `response.json` artifacts are operator-only
full-fidelity payload evidence; customer-facing lineage evidence must be an explicitly transformed
artifact with `customer_consumable` metadata.

### Retrieving Lineage Artifacts

You can retrieve the download URLs for all captured artifacts using a `GET` request to the lineage endpoint.

  * **Endpoint**: `GET /performance/lineage/{calculation_id}`
  * **Response**: The API returns a JSON object containing durable lineage status plus controlled download URLs for each available artifact. Artifact downloads are served through the service-owned route `GET /performance/lineage/{calculation_id}/artifacts/{artifact_name}`.

**Example Response for a TWR Calculation:**

```json
{
  "calculation_id": "a4b7e289-7e28-4b7e-8e28-7e284b7e8e28",
  "calculation_type": "TWR",
  "timestamp_utc": "2025-09-08T12:45:00Z",
  "status": "complete",
  "artifacts": {
    "request.json": {
      "url": "http://performance.dev.lotus/performance/lineage/a4b7e289-7e28-4b7e-8e28-7e284b7e8e28/artifacts/request.json",
      "access_classification": "operator_only",
      "intended_audience": "operations",
      "sensitivity": "raw_sensitive_payload",
      "minimization_posture": "raw_payload_full_fidelity",
      "retention_category": "lineage_raw_payload",
      "redaction_required_before_external_sharing": true
    },
    "response.json": {
      "url": "http://performance.dev.lotus/performance/lineage/a4b7e289-7e28-4b7e-8e28-7e284b7e8e28/artifacts/response.json",
      "access_classification": "operator_only",
      "intended_audience": "operations",
      "sensitivity": "raw_sensitive_payload",
      "minimization_posture": "raw_payload_full_fidelity",
      "retention_category": "lineage_raw_payload",
      "redaction_required_before_external_sharing": true
    },
    "daily_results.csv": {
      "url": "http://performance.dev.lotus/performance/lineage/a4b7e289-7e28-4b7e-8e28-7e284b7e8e28/artifacts/daily_results.csv",
      "access_classification": "operator_only",
      "intended_audience": "operations",
      "sensitivity": "derived_evidence",
      "minimization_posture": "derived_detail_minimized",
      "retention_category": "lineage_detail_evidence",
      "redaction_required_before_external_sharing": true
    }
  },
  "error_message": null
}
```

The `daily_results.csv` file contains the daily ladder used by the engine, including return-linking
fields and control columns that support calculation replay.
