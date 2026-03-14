 
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

  * **`input_fingerprint`**: A unique SHA256 hash of the canonical representation of your request payload. This hash is invariant to the order of items in lists (e.g., `daily_data`).
  * **`calculation_hash`**: A hash that combines the `input_fingerprint` with the `engine_version`. If the underlying calculation logic changes in a new version, this hash will change, guaranteeing a link between a specific request, a specific engine version, and a specific result.

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

Materialized lineage includes a `manifest.json` artifact that carries the calculation type,
completion timestamp, status, and artifact inventory. The lineage read path validates that
manifest against the durable metadata record before returning lineage as complete, so a stale
or partially corrupted manifest degrades cleanly instead of silently drifting from the DB-backed
audit record.

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
  "artifacts": {
    "request_payload.json": "[http://127.0.0.1:8000/performance/lineage/a4b7.../artifacts/request.json](http://127.0.0.1:8000/performance/lineage/a4b7.../artifacts/request.json)",
    "response_payload.json": "[http://127.0.0.1:8000/performance/lineage/a4b7.../artifacts/response.json](http://127.0.0.1:8000/performance/lineage/a4b7.../artifacts/response.json)",
    "twr_calculation_details.csv": "[http://127.0.0.1:8000/performance/lineage/a4b7.../artifacts/twr_calculation_details.csv](http://127.0.0.1:8000/performance/lineage/a4b7.../artifacts/twr_calculation_details.csv)"
  }
}
```

The `twr_calculation_details.csv` file contains the full DataFrame used by the engine, including every intermediate column (daily signs, cumulative returns, control flags, etc.), giving you a complete picture of the calculation.
