# Async SLO And Capacity Contract

- Service: `lotus-performance`
- Scope: executor-backed analytics from `202 Accepted` submission to terminal result availability
- Related references:
  - `docs/technical/performance_characterization.md`
  - `docs/standards/runtime-threshold-profiles.md`
  - `docs/runbooks/runtime-alerts.md`
  - `tests/benchmarks/test_returns_series_orchestration_performance.py`
  - `tests/benchmarks/test_benchmark_orchestration_performance.py`
  - `tests/benchmarks/test_twr_orchestration_performance.py`
  - `tests/benchmarks/test_execution_polling_performance.py`

## Purpose

Async analytics are user-visible workflows, not only queue internals. This contract defines the
production-facing completion SLO, capacity assumptions, and scale triggers for executor-backed
analytics while keeping benchmark automation distinct from issue #426. Issue #426 owns CI automation
for characterization evidence; this contract owns the SLO and capacity-management policy.

## SLO Definition

The measured interval is from successful `202 Accepted` response emission until the endpoint-specific
result route returns the terminal result or a terminal failure is visible through execution polling.
When mandatory lineage or inspection artifact materialization exists, `GET /performance/executions/{calculation_id}`
must reach terminal `complete` or `failed` before the workflow is considered terminal for audit-grade
supportability.

Production objective: at least 95 percent of accepted requests complete within the target under the
capacity assumptions below.

| Workflow family | Async surfaces | Production p95 completion objective | Representative characterization evidence |
| --- | --- | ---: | --- |
| Returns series | `POST /integration/returns/series` | `15s` | `test_returns_series_orchestration_performance.py` plus execution polling budget |
| TWR | `POST /performance/twr` | `20s` | `test_twr_orchestration_performance.py` plus execution polling budget |
| Contribution | `POST /performance/contribution` | `30s` | same executor, polling, and stateful-source envelope as TWR/returns-series |
| Attribution | `POST /performance/attribution` | `30s` | same executor, polling, and stateful-source envelope as contribution |
| Workspace summary | `POST /performance/workspace-summary` | `30s` | same executor, polling, and stateful-source envelope as returns-series/TWR |
| Benchmark | `POST /performance/benchmark` | `60s` | `test_benchmark_orchestration_performance.py` plus execution polling budget |

## Capacity Assumptions

The objectives above assume a production-like profile with:

- PostgreSQL durable metadata storage, not local SQLite;
- at least `2` compute executor workers and `1` lineage worker for production traffic;
- worker claim concurrency that preserves the PostgreSQL disjoint-claim contract;
- p95 upstream page latency at or below `300ms` before retries;
- upstream retry budget within configured retry limits and without sustained throttling;
- steady accepted-request arrival rate at or below `6` requests per minute per two compute workers;
- compute worker utilization target at or below `70%` over a rolling 15-minute window;
- lineage storage free capacity above the production threshold profile;
- no active recovery-drill, retention, or database availability degradation.

Worker sizing formula:

```text
required_compute_workers =
  ceil((peak_async_submissions_per_minute * p95_worker_service_seconds) / (60 * 0.70))
```

Use the highest p95 worker service time among the workflow families expected in the deployment. Keep
one additional worker of headroom when benchmark-heavy traffic is expected because benchmark
normalization has the longest governed orchestration budget.

## Runtime Threshold Mapping

Runtime threshold profiles are coarse degradation backstops. The SLO burn policy is stricter than the
production pending-age degradation threshold because a request can breach its SLO before the global
queue is declared degraded.

| Signal | SLO interpretation | Operator action |
| --- | --- | --- |
| Oldest compute pending age above `50%` of the workflow objective for 5 minutes | early burn | inspect `GET /integration/runtime-work-items?queue=compute`, confirm worker count and arrival rate |
| Oldest compute pending age above the workflow objective | SLO breach risk | add workers or throttle submissions; open an incident ticket for sustained breach |
| Oldest compute pending age above `2x` the workflow objective | active SLO burn | scale compute workers and inspect upstream latency/retry pressure |
| Production `RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS=600` breached | hard degradation backstop | page according to `docs/standards/runtime-alert-policy.md`; all async SLOs should be treated as breached |
| Compute terminal failure threshold breached | failed-workflow budget breach | inspect terminal failures before scaling; more workers can amplify bad inputs or upstream failures |
| Lineage pending age above audit objective after compute completion | supportability SLO burn | scale/restart lineage workers only after confirming lineage storage is healthy |

Staging should rehearse the same decisions with the staging profile values. Development thresholds are
diagnostic only and must not be used to justify production capacity.

## Evidence Commands

Run these when changing async execution, workers, stateful retrieval, orchestration, or threshold
policy:

```powershell
make performance-characterization
python -m pytest tests/benchmarks/test_returns_series_orchestration_performance.py tests/benchmarks/test_twr_orchestration_performance.py tests/benchmarks/test_benchmark_orchestration_performance.py tests/benchmarks/test_execution_polling_performance.py -q
python -m pytest tests/unit/docs/test_public_docs_contract.py -q
```

Run PostgreSQL-specific evidence when changing worker claims, durable-store query shape, or production
database assumptions:

```powershell
make performance-characterization-postgres
```

## Scale Triggers

Scale compute workers when any production-like deployment shows one of these sustained conditions:

- p95 accepted-to-terminal completion exceeds the workflow objective for two consecutive 5-minute windows;
- oldest compute pending age exceeds the workflow objective for 5 minutes;
- pending compute jobs exceed `2 * active_compute_worker_count` for 10 minutes;
- worker utilization exceeds `70%` for 15 minutes and terminal failures are not the dominant cause.

Do not scale blindly when terminal failure or retry pressure is the dominant signal. First classify
whether the bottleneck is upstream latency, invalid input, database availability, lineage storage, or
worker capacity.

## Cost Guardrails

- Prefer horizontal worker scale-out before increasing per-worker concurrency.
- Keep production worker increases tied to a measured arrival-rate or p95-service-time change.
- Roll back excess workers after the 95th percentile completion objective is stable for one business
  day and utilization stays below `40%`.
- Benchmark-heavy deployments need explicit capacity review because benchmark orchestration has the
  longest objective and the highest upstream dependency footprint.
