# Performance Characterization

This document records the repo-owned capacity and performance characterization contract for
`lotus-performance`.

Async submission-to-terminal SLOs, worker sizing assumptions, scale triggers, and SLO burn mapping
are governed separately in `docs/standards/async-slo-capacity-contract.md`. This file owns the
repeatable characterization budgets that support that SLO contract.

## Scope

This characterization currently governs the vectorized engine hot path behind
`engine.compute.run_calculations(...)` plus the durable queue-stat aggregation paths used by
the runtime control plane and Prometheus collector, plus the public async execution-polling
read path, plus the stateful portfolio-retrieval orchestration path, plus calculated stateful
benchmark normalization, plus PostgreSQL query-plan verification for the durable hot-path reads.

For RFC-0082 retrieval-performance posture and the current transport decision, see
[RFC-0082-retrieval-performance-hardening.md](RFC-0082-retrieval-performance-hardening.md).

## Governed workload

- Workload type: single-portfolio daily TWR calculation
- Dataset size: `75,000` unique daily valuation rows
- Input pattern: repeating realistic valuation templates with unique `perf_date` values
- Precision mode: default `float64`

## Why not 500k daily rows

The older benchmark attempted to approximate `500k` rows by repeating three dates. That did
not create a true 500k-row engine dataframe, so it was not valid capacity evidence.

A true 500k unique-daily-row workload is also not representable in this engine path because
timestamp-backed daily dates hit pandas/numpy bounds well before that size. The governed
workload therefore uses the largest practical daily-row scale that still exercises the real
vectorized path with unique dates.

## Runtime budget

- Metric: median wall-clock runtime across 5 measured runs after one warm-up run
- Budget: `<= 0.50s`
- Test owner: [test_engine_performance.py](../../tests/benchmarks/test_engine_performance.py)

This is a characterization contract, not a theoretical peak claim. If the engine changes
materially, we should refresh the budget using measured evidence and record that change in the
review ledger.

### Retained engine measurements

The owning assertion retains all five ordered `samples_seconds`, the recomputed exact
`median_seconds`, `row_count=75000`, `budget_seconds=0.50`, one warm-up and five measured calls.
Each timed call includes `engine_df.copy(deep=True)` and `run_calculations`; request/dataframe
preparation and evidence serialization remain outside timing. Evidence is appended to the pytest
node's `user_properties` after the last measured call and before the unchanged budget assertion.
This direct mechanism supports xunit2 without `record_property` warnings or warning suppression.
The original assertion still fails when its median exceeds the budget, with its five samples
retained in JUnit even on that failure.

The existing summary keeps `schema_version=1`, filenames and subprocess `return_code`, adding
`engine_timing_evidence`, `runtime_context`, `junit_validation_error` and
`artifact_validation_exit`. The engine evidence is versioned independently. For example, a valid
measurement value contains:

```json
{
  "schema_version": 1,
  "samples_seconds": [0.4, 0.3, 0.5, 0.2, 0.45],
  "median_seconds": 0.4,
  "row_count": 75000,
  "budget_seconds": 0.5,
  "warmup_runs": 1,
  "measured_runs": 5,
  "units": "seconds",
  "timed_boundary": "engine_df.copy(deep=True) + run_calculations",
  "within_budget": true,
  "workload": {
    "input_payload_sha256": "illustrative hash; actual run records canonical SHA256",
    "engine_config": {"precision_mode": "FLOAT64", "rounding_precision": 4}
  }
}
```

This abbreviated illustrative workload is not a measured result. Actual evidence carries
portfolio/date scope, canonical input-payload/config hashes and admitted engine configuration,
including precision mode and rounding. The summary wraps it with `status=recorded` and
`reason=null`. A full run requires exactly one non-skipped owning case and one valid property;
missing, duplicate, malformed, nonfinite, wrong-count or contract-mismatched evidence is
`status=invalid`, `value=null`, with a reason and artifact-validation exit `4`.
An over-budget measurement cannot describe a passed test. A nonzero pytest exit takes precedence
over artifact validation; the summary retains both statuses. Engine evidence is not applicable
in PostgreSQL-only mode, which records
`status=not_applicable`, `value=null`, with an explicit reason. Archived artifacts without these
fields are **not recorded**; do not invent samples or zero latency for them.

The benchmark plugin's separate statistics and JUnit whole-test durations are not the assertion's
five samples or median. Preserve those distinctions when comparing runs.

### Runtime context and qualification limits

`runtime_context` is collected in the characterization runner process before pytest, outside
engine timing. It records interpreter executable/version, platform/architecture, installed
library metadata and Git checkout SHA. CPU count, available affinity and host physical/available
memory are observations with provenance, not process resource entitlements. Readable mounted
cgroup-root CPU/memory/cpuset files are explicitly not verified effective process limits.
Only named CI/image/thread declarations are retained; no environment dump is performed.
Installed distribution versions are not a claim about libraries loaded by the timed engine.

Unavailable values use `value=null` and `unavailable_reason`, never invented zero capacity.
For example, an absent image declaration is:

```json
{"value": null, "provenance": "environment declaration APP_IMAGE_DIGEST", "unavailable_reason": "Not recorded or not declared"}
```

CPU governor/load contention and deployment resource entitlement remain explicitly unmeasured.
An image field supplied through the environment is a declaration, not independently observed
deployment identity. A hosted CI run does not execute inside or qualify the deployable image.

Package compatibility remains Python `>=3.11,<3.14`; the workflow and container currently target
Python 3.11. Neither statement silently excludes Windows or Python 3.13, nor guarantees this
latency on every compatible interpreter/resource combination. Performance issue #617 preserves
the original Windows median `0.5414720999833662s` against `0.500s`: its five samples and
contemporaneous version/resource telemetry were not retained. Later diagnostic metadata is not
that missing historical telemetry. The subsequent exact-main CI pass is separate evidence;
identical original/current engine and benchmark trees do not establish an environment cause.

Before any prospective diagnosis, agree on source, admitted workload/config, interpreter,
libraries, observed and declared resources, timing protocol and acceptance scope. Use one bounded
owning measurement per approved envelope, retaining failures and all five values. Do not rerun
the full PostgreSQL suite to seek a lucky pass, relax the budget, remove the caller copy, reduce
rows or downgrade precision. Remaining OS/resource/interpreter differences are unmatched;
causal claims require a separately reviewed comparison. Resource or supported-limit policy
changes require explicit governed acceptance. Richer artifacts alone do not close #617 or
certify deployment readiness.

### Qualified reference profiles - 10 October 2026

The two missing source/resource bindings in [issue #617 qualification evidence](https://github.com/sgajbi/lotus-performance/issues/617#issuecomment-6097213411)
are qualified for source `b4e905e43e2ea7cc28b56d45d5fefa3ce20cc057`, tree
`4e731901901ed2c5445ba0885b067b58de41d83c`. Both use loaded NumPy/pandas `2.3.2`,
the same admitted FLOAT64 input/configuration, 75,000 unique daily rows, one warm-up,
five measured calls and the unchanged caller-copy-plus-calculation boundary and 0.500-second budget.

| Reference | Actual interpreter and enforced resources | Median seconds |
| --- | --- | --- |
| Linux runtime image | Python 3.11.17; process-effective cgroup quota `400000 100000`, memory `4294967296`, swap `0`; UID/GID10001, network none, read-only root | 0.33487504499498755 |
| Windows | Python 3.13.3; Windows 11 build26200/i9-11900KF; real Job membership, process/job affinity `0xF`, process/job memory limits `4294967296` | 0.42923679994419217 |

Ordered samples in seconds, retained without rounding:

```json
{
  "linux": [0.33487504499498755, 0.3113839700818062, 0.3542105440283194, 0.3240083260461688, 0.3411974039627239],
  "windows": [0.47468290000688285, 0.4553645000560209, 0.42923679994419217, 0.41219469998031855, 0.42801520007196814]
}
```

The Linux profile ran inside locally built deployable image
`sha256:1930e7ce557ccb5385bdc8df359c3214a40f0dbadaf75acc6aa5bc00fdfeb99d`, from
the unchanged canonical Dockerfile and frozen source. This is an actual image identity, not a
published registry digest. Its observed affinity spans 16 host CPUs; the enforced resource is
the four-CPU quota, not a four-CPU cpuset. Loaded numerical libraries resolve under `/usr/local`;
no source/library overlay is present. The source check after the helper and both native exits pass.
Windows admission assigns the suspended child to the real Job before resume; the child rechecks
limits, interpreter/DLL and loaded libraries before the owning pytest node. Native child/launcher
exits are zero, with owned Job/process quiescence and handle cleanup. External pre/post checks
rehash 9,883 environment and 1,404 source files plus interpreter/DLL and adapter seals; this is
external pre/post freeze, not an inside-child full-binary hash guard.

Both measurements bind canonical input SHA256
`df37b292eface97c4ff733f93c0abfe809105966d822a40f0335ef33df935897` and config SHA256
`72e1d1462bd0f753f4e1f4b3f3a09e0808a2209ac801b6c81b4e441a51dd2a62`.
The retained qualification JSON SHA256 is
`2a2a736554eaad3341c2508241f63a5578caa1d620ebddbb268a20e90bf73d77`; its 127-file
evidence archive SHA256 is `e3a0e46a5f0d9818dfec42a04168e2e836fd6fa630389eb75f6d7920487f7497`.
It preserves all samples, identities, native results and the spent pre-engine controller failure.
The deterministic operational repair did not retry a measured budget failure or change numerics.

The [exact-source hosted characterization](https://github.com/sgajbi/lotus-performance/actions/runs/38037935203)
passed 365 full and 48 real PostgreSQL cases without skips/errors/failures; its accepted financial
and FLOAT64/DECIMAL_STRICT correctness evidence is reused. Hosted CI, these local reference
profiles and a bank's production resource entitlement remain distinct. No full campaign was
repeated to obtain these measurements. The original Windows miss retains its uncertainty;
these later passes do not establish its cause or guarantee every compatible host/interpreter.
Python `>=3.11,<3.14`, including Windows/3.13, remains supported; no compatibility limit changed.

## Durable queue-stat budgets

These characterize the control-plane query path behind:

- `/integration/runtime-status`
- `/metrics`

### Compute queue stats

- Workload: `5,000` durable compute jobs
- Metric: median wall-clock runtime across 10 reads
- Budget: `<= 15ms`
- Test owner: [test_runtime_store_performance.py](../../tests/benchmarks/test_runtime_store_performance.py)

### Lineage queue stats

- Workload: `1,000` durable lineage payloads
- Metric: median wall-clock runtime across 10 reads
- Budget: `<= 10ms`
- Test owner: [test_runtime_store_performance.py](../../tests/benchmarks/test_runtime_store_performance.py)

## Execution polling budget

- Workload: one async execution with:
  - `5` lifecycle stages
  - `100` upstream snapshots
  - durable compute-job metadata
  - durable async-result metadata
- Metric: median wall-clock runtime across 20 reads
- Budget: `<= 20ms`
- Test owner: [test_execution_polling_performance.py](../../tests/benchmarks/test_execution_polling_performance.py)

## Stateful returns-series orchestration budget

- Workload: one stateful returns-series request across `2024-01-01` to `2033-12-31` with:
  - portfolio return series
  - calculated benchmark return series
  - risk-free return series
  - daily frequency
  - composition-window sourcing, component price loading, and FX normalization for benchmark calculation
  - canonical normalization and response shaping
- Metric: median wall-clock runtime across 5 reads after warm-up
- Budget: `<= 7000ms`
- Test owner: [test_returns_series_orchestration_performance.py](../../tests/benchmarks/test_returns_series_orchestration_performance.py)

## Stateful retrieval budget

- Workload: stateful portfolio timeseries retrieval across `2024-01-01` to `2033-12-31`
- Retrieval characteristics:
  - `90`-day portfolio chunks
  - paginated upstream responses per chunk
  - durable upstream snapshot recording enabled
  - canonical deduped merge of returned observations
- Metric: median wall-clock runtime across 5 reads after warm-up
- Budget: `<= 250ms`
- Test owner: [test_stateful_input_performance.py](../../tests/benchmarks/test_stateful_input_performance.py)

## Stateful reference retrieval budgets

### Benchmark return series

- Workload: stateful benchmark return-series retrieval across `2024-01-01` to `2033-12-31`
- Retrieval characteristics:
  - `365`-day reference chunks
  - durable upstream snapshot recording enabled
  - canonical deduped merge of returned points
- Metric: median wall-clock runtime across 5 reads after warm-up
- Budget: `<= 25ms`
- Test owner: [test_stateful_input_performance.py](../../tests/benchmarks/test_stateful_input_performance.py)

### Risk-free series

- Workload: stateful risk-free series retrieval across `2024-01-01` to `2033-12-31`
- Retrieval characteristics:
  - `365`-day reference chunks
  - durable upstream snapshot recording enabled
  - canonical deduped merge of returned points
- Metric: median wall-clock runtime across 5 reads after warm-up
- Budget: `<= 25ms`
- Test owner: [test_stateful_input_performance.py](../../tests/benchmarks/test_stateful_input_performance.py)

## Stateful calculated benchmark normalization budget

- Workload: calculated stateful benchmark normalization across `2024-01-01` to `2033-12-31`
- Retrieval characteristics:
  - effective-dated composition-window sourcing
  - `365`-day component price-series chunks
  - `365`-day FX-rate chunks for non-benchmark-currency components
  - beginning-of-day weight application across rebalance segments
  - durable upstream snapshot recording enabled
- Benchmark shape:
  - `4` benchmark components
  - `8` effective-dated composition segments
  - `3` FX pairs normalized into benchmark currency
- Metric: median wall-clock runtime across 5 reads after warm-up
- Budget: `<= 2800ms`
- Test owner: [test_stateful_input_performance.py](../../tests/benchmarks/test_stateful_input_performance.py)

## Stateful benchmark orchestration budget

- Workload: full stateful benchmark orchestration across `2024-01-01` to `2033-12-31`
- Orchestration characteristics:
  - calculated benchmark mode
  - shared benchmark request resolution
  - effective-dated composition-window sourcing
  - component price loading and FX normalization
  - benchmark response shaping with daily timeseries enabled
  - durable execution identity updates and lineage handoff
- Benchmark shape:
  - `4` benchmark components
  - `8` effective-dated composition segments
  - `3` FX pairs normalized into benchmark currency
- Metric: median wall-clock runtime across 5 runs after warm-up
- Budget: `<= 42000ms`
- Test owner: [test_benchmark_orchestration_performance.py](../../tests/benchmarks/test_benchmark_orchestration_performance.py)

## Stateful benchmark-inclusive TWR orchestration budget

- Workload: full stateful benchmark-inclusive TWR orchestration across `2024-01-01` to `2033-12-31`
- Orchestration characteristics:
  - stateful portfolio valuation sourcing
  - stateful benchmark assignment lookup
  - calculated benchmark sourcing and normalization
  - TWR engine execution with benchmark inclusion
  - arithmetic relative-performance output
  - durable execution identity updates and lineage handoff
- Request shape:
  - `include_benchmark=true`
  - implicit benchmark assignment from lotus-core
  - `SI` request with monthly breakdown output
- Metric: median wall-clock runtime across 5 runs after warm-up
- Budget: `<= 8500ms`
- Test owner: [test_twr_orchestration_performance.py](../../tests/benchmarks/test_twr_orchestration_performance.py)

## PostgreSQL plan verification

These checks are not generic SQL compilation tests. They run `EXPLAIN (FORMAT JSON)` against a
live PostgreSQL durable metadata store after explicit `ANALYZE`, so the planner contract is
based on realistic table statistics rather than empty-table defaults.

### Compute queue stats

- Workload: `5,000` durable compute jobs
- Plan contract:
  - root aggregate plan over `analytics_compute_job`
  - no explicit `Sort`
  - no planner regression into multi-query application-side aggregation
- Test owner: [test_postgres_query_plans.py](../../tests/benchmarks/test_postgres_query_plans.py)

### Lineage queue stats

- Workload: `1,000` durable lineage payloads with joined lineage records
- Plan contract:
  - root aggregate plan over the `lineage_payloads` / `lineage_records` join
  - no explicit `Sort`
  - join/aggregate remains in SQL rather than application-side row walks
- Test owner: [test_postgres_query_plans.py](../../tests/benchmarks/test_postgres_query_plans.py)

### Execution snapshot polling

- Workload: `25` executions with `100` upstream snapshots each
- Plan contract:
  - ordered snapshot polling uses the composite `ix_upstream_snapshot_calculation_created_at` index
  - no fallback to sequential scan on `analytics_upstream_snapshot`
- Notes:
  - PostgreSQL may still choose a bitmap-heap-plus-sort plan at this cardinality after `ANALYZE`
    because the query returns all snapshots for one calculation and the sort is cheap; the governed
    contract is index participation plus no sequential scan, not a brittle “never sort” rule.
- Test owner: [test_postgres_query_plans.py](../../tests/benchmarks/test_postgres_query_plans.py)

## Running the characterization suite

- Full repo-owned characterization: `make performance-characterization`
- Live PostgreSQL plan verification: `make performance-characterization-postgres`

Both commands write CI-reviewable artifacts under `output/performance-characterization/`:

- `performance-characterization.junit.xml` and `performance-characterization.log`
- `performance-characterization.summary.json`
- `performance-characterization-postgres.junit.xml` and `performance-characterization-postgres.log`
- `performance-characterization-postgres.summary.json`

The GitHub workflow `.github/workflows/performance-characterization.yml` runs on pull requests to
`main`, pushes to `main`, weekly schedule, and manual dispatch. It provisions a live PostgreSQL
service, runs `make performance-characterization`, then reruns the PostgreSQL plan/concurrency
subset with `--require-non-skipped`, and uploads the generated artifacts as
`performance-characterization-evidence`. The workflow is evidence-producing and not listed as a
required PR merge check yet; benchmark budget failures still fail the workflow because there is no
`continue-on-error` posture.

The local PostgreSQL command starts `docker compose up -d performance-lineage-db` before executing
the subset. If PostgreSQL is unavailable, the runner writes a summary artifact and fails closed
instead of treating an all-skipped PostgreSQL suite as valid characterization evidence.

## PostgreSQL concurrency proof

These are live multi-worker claim contracts against PostgreSQL, not SQLite compilation proxies.

### Compute queue claims

- Workload: `20` pending compute jobs, `2` workers, `10` claims each
- Contract:
  - claims are disjoint across workers
  - all available jobs are claimed exactly once
  - a third worker sees no additional pending claims
- Test owner: [test_postgres_concurrency_contracts.py](../../tests/benchmarks/test_postgres_concurrency_contracts.py)

### Lineage payload claims

- Workload: `20` pending lineage payloads, `2` workers, `10` claims each
- Contract:
  - claims are disjoint across workers
  - all available payloads are claimed exactly once
  - a third worker sees no additional pending claims
- Test owner: [test_postgres_concurrency_contracts.py](../../tests/benchmarks/test_postgres_concurrency_contracts.py)
