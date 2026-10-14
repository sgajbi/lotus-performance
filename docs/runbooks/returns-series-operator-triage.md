# Returns-Series Operator Triage

- Service: `lotus-performance`
- Scope: first response for stale, partial, or degraded `POST /integration/returns/series` executions
- Primary surfaces:
  - `POST /integration/returns/series`
  - `GET /integration/returns/series/results/{calculation_id}`
  - `GET /performance/executions/{calculation_id}`
  - `GET /integration/runtime-status`
  - `GET /integration/runtime-work-items?queue=compute`
  - `GET /integration/runtime-recoveries?queue=compute`

Use this runbook when a downstream risk workflow, API client, alert, or support ticket reports stale
returns-series freshness, partial coverage, side-series fill evidence, skipped risk-free source rows,
retained gaps, async result failure, or elevated
`lotus_performance_calculation_supportability_total{operation="returns_series"}` samples.

## Retained Portfolio Source Evidence

For new stateful NET/GROSS calculations, inspect `GET /performance/lineage/{calculation_id}`
separately from the arithmetic result. `source_custody_state` progresses through `capturing`,
`frozen`, `pending_materialization`, and `complete`; `failed` preserves the selected identity.
Null means unavailable, including historical calculations. Arithmetic success does not imply
complete custody. Storage, enqueue, or materialization failure must not be reported as complete
evidence, and exhausting custody retries does not turn a successful arithmetic result into failure.
The originating inline attempt remains the mutation owner after freeze. A different inline attempt
cannot enqueue or fail it; an admitted current compute retry can reuse the frozen identity under
the compute store's existing tenant, attempt and live-lease checks.

After a retryable async result-publication outage, a current fenced async owner resumes the exact
retained completed response before calculator entry. The owning store locks execution, compute and
existing frozen custody in that order and checks the statement-time lease before and after the read.
The original response envelope, root and capture attempt remain unchanged. Inline, absent/unfrozen,
failed, foreign and stale custody cannot authorize this read; active executions use ordinary calculation.
The cached envelope must match the immutable queued response or the selected materialized response
digest inside that transaction. A matching calculation/portfolio id or frozen input root alone cannot
authorize a replaced completed response. Missing response authority refuses publication reuse.
This does not establish native storage durability or live-source acceptance.

The first slice retains the exact successful portfolio-timeseries JSON entity bytes, opaque page
tokens, ordered chunk/page index, separately named legacy parsed fingerprints, and the consumed
normalized inputs. It covers inline, queued, and API-resolved promotion. The fixed archive/index
format streams pages rather than publishing an unbounded page list. Financial decimals encoded as
strings retain their lexemes; normalized JSON preserves the representation the existing engine
consumed. No new financial limits, truncation, currency aliases, or missing-value fills are added.

Traversal and archive verification share the established nonempty top-level token, then nested token,
then terminal-page precedence. Optional page metadata and returned count may be absent; only an absent
count is derived from observations. Supplied malformed metadata/counts, token loops, ordering errors
and incomplete traversal still refuse custody. Captured entity bytes are never rewritten.

Benchmark and risk-free raw-source custody remains unavailable. Their existing arithmetic options
continue to work; a retained normalized side series is not complete upstream source custody. This
slice does not close issue #662 or certify source authority, historical evidence, production capacity,
or a multi-provider coherent snapshot.

Raw artifacts remain operator-only under the existing lineage policy. Reads require a matching
retained execution tenant even when local privileged-read enforcement is disabled. Every read
verifies the selected manifest, artifact hashes, source bundle, and complete page traversal.

Operator-only HTTP inventory links and downloads additionally require `operations.runtime.read`
with the governed actor, tenant, role, correlation and service identity. This floor also applies when
general privileged-read enforcement is disabled. Portfolio entitlement alone cannot expose source/raw
links or bytes; customer-safe evidence follows existing admission. Enabled privileged-read middleware
keeps its existing route-level operator requirement, including for customer-safe lineage routes.
The same effective filename-plus-manifest policy governs links and direct downloads: a stricter
operator-only support brief stays restricted even at a known URL. Raw/source metadata always carries
the code-owned sensitivity, audience, minimization, retention and redaction floors; stricter manifest
labels are preserved. Blank response continuation tokens are absent for top-level/nested precedence,
while malformed supplied token types and invalid requested page tokens remain refused.
Missing execution authority, corruption, and path escape fail closed. The queue can retire after
successful materialization; it is not the permanent evidence owner.

For source-off verification, use the existing database and lineage volume with an authorized
operator identity. Run from the `lotus-performance` repository root. Set the named environment
variables to those existing resources; supply the retained calculation and its admitted tenant.
The command reads authority and source artifacts and runs the existing portfolio normalizer and
return engine. It performs no Core calls, enqueue, migration, or calculation submission.

PowerShell:

```powershell
python scripts/replay_returns_series_source.py --database-url "$env:LINEAGE_METADATA_DATABASE_URL" --storage-path "$env:LINEAGE_STORAGE_PATH" --calculation-id "$CalculationId" --tenant-id "$TenantId"
```

POSIX:

```bash
python scripts/replay_returns_series_source.py --database-url "$LINEAGE_METADATA_DATABASE_URL" --storage-path "$LINEAGE_STORAGE_PATH" --calculation-id "$CALCULATION_ID" --tenant-id "$TENANT_ID"
```

Success verifies raw pages through normalized portfolio return points. It does not independently
certify optional families or the final aligned response. A mismatch exits unsuccessfully. Local
fixture proof is not live-provider, PostgreSQL-concurrency, image, or capacity qualification.

All source files, interrupted staging files, and page spools remain beneath the existing calculation
directory and existing retention policy. Archive creation uses page-sized buffers and retains the
current chunk's opaque token set for loop detection; normalization
and the engine retain their existing workload memory requirements. Spooling and immutable files
consume additional disk. Exhausted storage is a custody failure, not permission to truncate.
The lineage filesystem must support same-directory atomic hard-link publication for immutable
materialization files; failed publication leaves no selected partial manifest. Retention handles
interrupted staging files together with their calculation directory.

Source publication is supported on Linux filesystems/volumes that honor file and directory
`fsync` and same-directory atomic hard links. The storage parent is flushed after calculation
directory creation (also on retry); capture flushes its file entries before selecting the frozen
root. Materialization flushes published entries before selecting the complete manifest, including
when a retry finds an existing matching file. A failed barrier cannot establish that authority.
Native Windows and other unsupported platforms refuse source publication with an explicit custody
failure while preserving arithmetic success. Read-only verification of existing evidence does not
require a publication barrier. Portable test fixtures simulate these barriers; they do not prove
native Linux Docker-volume or power-loss durability. Qualify the deployed filesystem, mount and
storage configuration independently. Preprovision the storage root durably before admitting work;
the lineage directory must be owned by trusted service roles.

An exceptional dual enqueue/failure-state persistence outage can leave frozen custody without a
payload after arithmetic completes. Each ordinary lineage-worker poll uses its existing batch bound
to terminalize only frozen, pending custody without a payload when matching retained execution and
any compute job are terminal. It locks execution, optional compute and lineage in that order and
rechecks identity and payload absence. Active work, missing/foreign authority, queued or leased
payloads, replaced roots and already terminal custody are protected. Database failures roll back and
emit a structured retryable worker warning; a later pass retries after metadata recovery.

The transition records failed custody with the reason "Source materialization was not queued before
arithmetic became terminal." It retains the root, originating attempt, tenant and successful arithmetic;
it does not recover producer evidence or establish complete custody. Its new terminal timestamp starts
the existing retention eligibility check, subject to whole-group cutoffs and holds. Do not manually reset
the originating identity or treat this terminalization as source authority qualification.

## First Response

1. Capture support-safe identifiers: `calculation_id`, endpoint path, response status, `correlation_id`, `request_id`, `trace_id`, and the bounded diagnostics fields. Do not copy portfolio names, client names, request payloads, or raw source rows into tickets.
2. Check `GET /health/ready` and `GET /integration/runtime-status`.
3. Open the `Lotus Performance Operability` Grafana dashboard and check the `Returns-series stale/degraded rate` and `Returns-series supportability volume` panels.
4. For `202 Accepted` or missing async results, poll `GET /performance/executions/{calculation_id}` and `GET /integration/returns/series/results/{calculation_id}`.
5. If compute execution is stuck or failed, inspect `GET /integration/runtime-work-items?queue=compute` and `GET /integration/runtime-recoveries?queue=compute`.
6. If the completed response is stale or degraded, classify the diagnostic posture below before escalating.

## Diagnostic Posture

| Signal | Support meaning | First owner |
| --- | --- | --- |
| `diagnostics.freshness="stale"` | The latest selected source evidence is older than the required observation date. | `lotus-performance` triages; source freshness may escalate to `lotus-core`. |
| `diagnostics.coverage.missing_points > 0` | Returned portfolio points do not cover all required dates under the selected calendar policy. | `lotus-performance` validates policy and source window; `lotus-core` owns missing stateful source facts. |
| `diagnostics.gaps[]` | A selected portfolio, benchmark, or risk-free series retained a gap after policy application. | `lotus-performance` owns gap diagnostics; upstream source owners own missing facts. |
| `diagnostics.fill_evidence[]` | A selected benchmark or risk-free side-series point was synthesized by `FORWARD_FILL` or `ZERO_FILL`, not observed directly in the source series. | `lotus-performance` owns policy application; source owners own the original side-series gap when filled points are unexpected. |
| `diagnostics.risk_free_source_quality.skipped_points > 0` | Stateful risk-free source rows were malformed, unusable, or used unsupported day-count conventions. | `lotus-performance` owns normalization; `lotus-core` owns source payload correction. |
| `diagnostics.calendar_source` | MARKET request used the governed calendar source, version, supported horizon, and holiday count. | `lotus-performance`. |
| `diagnostics.warnings[]` | Non-fatal policy degradation, including max-gap tolerance warnings. | `lotus-performance`. |

MARKET calendar requests use the Lotus reference market trading calendar, not a weekday-only
approximation. The current source is `lotus-reference-market-holidays.v1`, generated for
1970-01-01 through 2099-12-31 with Good Friday, New Year, Christmas, and observed weekday holidays.
If a reported gap falls on a supported market holiday such as Good Friday, verify the request used
`calendar_policy=MARKET` and check `diagnostics.calendar_source` before raising a source-data
defect. Requests outside the certified horizon fail closed with `INVALID_REQUEST`.

## Metrics And Alerts

Completed responses emit:

- `lotus_performance_calculation_supportability_total{operation="returns_series",supportability_state,reason,freshness_bucket}`
- `lotus_analytics_freshness_bucket_total{service="lotus-performance",operation="returns_series",freshness_bucket,supportability_state}`

The deployable `Lotus Performance Operability` dashboard includes returns-series panels for the
stale/degraded rate and supportability volume by the bounded `supportability_state`, `reason`, and
`freshness_bucket` labels. `make quality-observability-readiness-gate` fails when the
returns-series alert exists without matching dashboard coverage.

Bounded mapping:

- current and complete: `supportability_state="ready"`, `reason="calculation_complete"`
- stale freshness: `supportability_state="stale"`, `reason="stale_source_observations"`
- partial coverage, retained gaps, warnings, or skipped risk-free rows: `supportability_state="degraded"`, `reason="calculation_quality_issue"`

Metric labels must not include portfolio, client, tenant, account, benchmark, calculation, trace,
correlation, request, or response payload identifiers.

## Escalation Boundaries

- `lotus-performance`: returns-series API behavior, diagnostics calculation, async result route,
  benchmark calculation path, metric emission, and this runbook.
- `lotus-core`: stateful portfolio analytics timeseries, benchmark assignment or vendor benchmark
  return rows, risk-free source payload shape, and source observation freshness.
- `lotus-risk`: downstream polling budgets, risk calculation interpretation, and risk-panel user
  messaging after a valid returns-series response is received.

Escalate to `lotus-risk` only after `lotus-performance` has either produced a completed
returns-series response or identified a performance-owned execution failure. Escalate to
`lotus-core` only with bounded evidence: source family, required date, latest source date, skipped
row count, and upstream endpoint family. Do not attach raw portfolio/client payloads.

## Closure Evidence

Record these fields in the incident or GitHub issue:

- `calculation_id`
- response status and result route
- `diagnostics.freshness`
- `diagnostics.coverage.requested_points`, `returned_points`, and `missing_points`
- `diagnostics.calendar_source` when `calendar_policy=MARKET`
- count of `diagnostics.gaps`
- count of `diagnostics.fill_evidence` and bounded filled-date samples when present
- `diagnostics.risk_free_source_quality` counts when present
- observed metric labels for `operation="returns_series"`
- owner boundary selected for follow-up
