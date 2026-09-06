# Architecture

`lotus-performance` is a single business service with a split runtime:

- API orchestrator
- compute executor worker
- lineage worker
- durable metadata database

This design follows the implemented RFC-041 model: keep one domain service, but separate
request orchestration, heavy compute, and lineage materialization operationally.

## Layers

### API layer (`app/api/endpoints/`)

- owns public HTTP contracts
- validates requests with Pydantic models in `app/models/`
- creates durable execution records before async/offloaded flows return
- performs synchronous calculations for small requests
- returns `202` plus `calculation_id` for executor-offloaded workloads

### Application services (`app/services/`)

- `execution_registry.py`: durable execution lifecycle and stage tracking
- `compute_job_store.py`: durable compute queue, leasing, retry state, and recovery state
- `async_result_store.py`: durable async success/failure result storage
- `stateful_input_service.py`: lotus-core retrieval, paging, retry, dedupe, and upstream snapshot capture
- `lineage_metadata_store.py` / `lineage_service.py`: durable lineage metadata and artifact materialization

### Engine layer (`engine/`)

- pure analytics logic for TWR, MWR, contribution, attribution, breakdown, and policy handling
- independent of FastAPI and worker runtime concerns

### Core utilities (`core/`)

- shared envelope, periods, annualization, reproducibility hashing, and error types

## Runtime topology

### 1. API orchestrator

- FastAPI application in [main.py](../../main.py)
- owns request validation, sync/async execution decisioning, execution registry writes, and readiness endpoints

### 2. Compute executor

- worker process in [compute_executor_worker.py](../../app/workers/compute_executor_worker.py)
- leases pending jobs from durable storage
- executes returns-series, contribution, and attribution workloads
- writes durable async results and terminal execution state

### 3. Lineage worker

- worker process in [lineage_worker.py](../../app/workers/lineage_worker.py)
- materializes lineage artifacts from durable payload metadata after request/compute completion

### 4. Durable metadata database

- PostgreSQL in deployment and docker-compose
- stores execution state, execution stages, compute jobs, async results, and lineage metadata

## Request flow

### Synchronous flow

1. API validates the request.
2. API creates or updates the durable execution record.
3. API executes the calculation inline.
4. API persists lineage payload metadata for asynchronous materialization.
5. API returns the final response.

### Executor-offloaded flow

1. API validates the request.
2. API creates a durable execution record.
3. API enqueues a durable compute job and returns `202 Accepted`.
4. Compute executor leases the job, runs the calculation, and stores the async result.
5. Lineage worker materializes lineage artifacts from durable metadata.
6. Clients poll `/performance/executions/{calculation_id}` or the result endpoint for completion.

## Operational contracts

- `/health/ready` is only `200` when the service is not draining and the durable metadata store is reachable
- `/performance/executions/{calculation_id}` is the canonical execution-state polling surface
- async result endpoints are backed by durable async result storage, not process-local memory

## Design constraints

- no fake lineage or process-local success state
- no executor work without durable execution metadata
- no lineage materialization dependency on in-process background tasks
- no silent recovery of stale worker leases; stale work must be requeued or marked failed durably
