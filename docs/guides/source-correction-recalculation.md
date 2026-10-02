# Source-Correction Recalculation

## Scope

`lotus-performance` consumes an authorized, versioned correction notice and recalculates affected
retained stateful analytics under a new calculation identity. `lotus-core` owns correction-command
admission and source data; this consumer contract does not prove a live Core producer.

## API

| Method and path | Purpose |
| --- | --- |
| `POST /performance/source-corrections` | Admit or replay a tenant-scoped correction and schedule affected work. |
| `GET /performance/source-corrections/{correction_id}` | Read impact, job state, result references, and output-change evidence. |
| `DELETE /performance/source-corrections/{correction_id}` | Cancel the whole batch only before any worker lease. |
| `GET /performance/executions/{calculation_id}/retained-result` | Retrieve the immutable response retained under one tenant-owned calculation identity. |

Every request requires admitted tenant authority. Identity is `(tenant_id, correction_id)`; an exact
replay is idempotent and a changed payload returns `409`. A newer scope event must name the latest
admitted `source_revision` in `supersedes_source_revision`; this check is serialized per tenant and
source scope. Replay identity covers only the submitted contract, not server-derived coalescing
state. `observed_at_utc` must be UTC.

```json
{
  "correction_id": "core-event-42",
  "source_product": "portfolio_timeseries",
  "source_revision": "restatement-2",
  "supersedes_source_revision": "restatement-1",
  "target_type": "portfolio",
  "target_id": "PORT-42",
  "effective_start_date": "2026-01-02",
  "effective_end_date": "2026-01-02",
  "observed_at_utc": "2026-01-03T10:00:00Z",
  "correction_reason": "Corrected closing valuation.",
  "source_authorization": {
    "issuer": "lotus-core",
    "evidence_id": "core-event-42"
  }
}
```

## Processing Contract

1. Find completed retained stateful calculations whose requested windows overlap the correction.
2. Filter benchmark and FX corrections by explicit retained source identity.
3. Coalesce overlapping pending work without losing the earliest or latest affected date.
4. Re-resolve current source data in the durable compute worker under a deterministic new
   calculation identity.
5. Keep the original response retrievable and expose the corrected path only after completion.

A terminal `no_effect` decision is immutable on replay. Cancelling coalesced pending work publishes
the cancellation to every correction that references the shared calculation identity.

The supported recalculation set is TWR, returns series, benchmark, contribution, attribution, and
workspace summary. Stateless calculations and rows without retained request/response custody are
not silently reconstructed. FX impact requires both corrected-pair currencies in retained input;
requested reporting currency alone is not applied-FX evidence.

## Evidence And Operations

The source-correction status reports original and corrected identities, calculation hashes,
response fingerprints, terminal failure codes, and `output_changed`. The bounded metric
`lotus_performance_source_correction_total` records product, target type, and outcome without
tenant or calculation labels.

Runtime retention protects calculations referenced by a correction so old and corrected results
remain reproducible. PostgreSQL contracts prove tenant-scoped concurrent replay, single-successor
revision admission, conflict refusal, and restart durability. The independent financial regression uses a zero-flow one-day portfolio:
100 to 110 produces 10% TWR; the corrected close 108 produces 8%; both retained responses remain
available under their own calculation identities.

## Limitations

- Core source-correction producer acceptance remains owned by Core issue `#452`.
- This API publishes result references; downstream Risk, Report, and composite consumers require
  their own acceptance before claiming automatic propagation.
- Missing historical source coverage remains explicit and is not promoted to complete
  since-inception evidence.
