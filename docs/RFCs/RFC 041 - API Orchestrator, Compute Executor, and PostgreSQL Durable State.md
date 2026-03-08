# RFC 041 - API Orchestrator, Compute Executor, and PostgreSQL Durable State

- Status: Proposed
- Authors: Codex
- Date: 2026-03-08
- Owner: lotus-performance

## 1. Summary

This RFC defines the target runtime architecture for `lotus-performance`.

The core decision is:

1. Keep `lotus-performance` as one business domain, but not as one undifferentiated runtime.
2. Do not split TWR, MWR, contribution, attribution, and returns-series into separate deployable microservices.
3. Introduce clear deployable service boundaries between:
   - API orchestration
   - stateful input retrieval and normalization
   - heavy compute execution
   - lineage and artifact persistence
4. Replace filesystem-first durability patterns with PostgreSQL-backed durable state for execution metadata, reproducibility records, and lineage/artifact indexing.

This design preserves domain coherence while creating explicit scaling boundaries for operationally heavy workloads and a durable foundation for banking-grade auditability.

## 2. Context

`lotus-performance` is not event-driven. It retrieves required state from `lotus-core` over REST APIs and computes analytics from that retrieved data.

Today, the repository is one deployable service with layered code organization:

- API endpoints
- adapters
- engine
- shared core utilities
- application services

This separation is good for code structure, but the runtime boundary is still too coarse:

- HTTP request handling and heavy analytics execution run in the same service process
- stateful retrieval logic is embedded directly inside endpoint flows
- lineage persistence relies on local filesystem storage
- there is no independently scalable runtime boundary for retrieval-heavy, compute-heavy, and persistence-heavy workloads

That is acceptable for current scale, but it is not the right long-term boundary for:

- large portfolio universes
- long return histories
- high-concurrency interactive traffic
- durable banking-grade audit and reproducibility guarantees

## 3. Problem Statement

The current runtime shape creates five architectural risks:

1. CPU-heavy calculation competes directly with request-serving capacity.
2. Stateful retrieval from `lotus-core` is endpoint-local instead of being a first-class internal capability.
3. Filesystem-backed lineage capture is weak for horizontal scaling and durable operations.
4. Future scaling pressure may tempt premature fragmentation by analytic domain, which would increase duplication and financial consistency risk.
5. Operationally distinct load profiles cannot be scaled or protected independently.

## 4. Goals

The target architecture must:

1. Keep domain ownership clear and aligned to DDD.
2. Support efficient REST-based sourcing from `lotus-core`.
3. Scale retrieval, compute, and persistence independently from synchronous API traffic.
4. Preserve strict correctness, reproducibility, and auditability.
5. Avoid unnecessary microservice fragmentation and over-engineering.
6. Use PostgreSQL as the durable backing store for runtime state that must survive process or node failure.

## 5. Non-Goals

This RFC does not:

1. Introduce event-driven architecture into `lotus-performance`.
2. Move source-of-truth portfolio, benchmark-assignment, or reference-data ownership out of `lotus-core`.
3. Split every analytic family into separately deployed services.
4. Define a final batch scheduling product or cluster technology choice.

## 6. Current State Assessment

### 6.1 What should not be split today

The following capabilities should remain inside the same business service:

- TWR
- MWR
- contribution
- attribution
- returns-series integration
- reproducibility and lineage governance

Reason:

- they share a common financial calculation substrate
- they share common precision, period, diagnostics, and reproducibility rules
- splitting them by deployable service would duplicate financial logic and create drift risk

### 6.2 What is currently too tightly coupled

The following runtime responsibilities are too tightly coupled:

- synchronous HTTP orchestration
- stateful data retrieval and normalization from `lotus-core`
- large in-memory compute execution
- durable lineage and artifact persistence

## 7. Decision

`lotus-performance` will evolve into a multi-service runtime architecture inside one business service boundary.

Required deployable services:

1. `Performance API Orchestrator`
2. `Performance Stateful Input Service`
3. `Performance Compute Executor`
4. `Performance Lineage Service`

PostgreSQL will be introduced as the durable store for execution metadata and lineage indexing.

This is a service split by operational responsibility, not a split by analytics domain.

## 8. Target Service Boundaries

### 8.1 Boundary retained: one business microservice

Externally, `lotus-performance` remains one application in the Lotus platform.

It continues to own:

- performance analytics APIs
- stateful analytics orchestration against `lotus-core`
- performance engine behavior
- reproducibility, diagnostics, and lineage contract semantics

### 8.2 Deployable service: API Orchestrator

The API Orchestrator is responsible for:

- request validation and contract enforcement
- authentication, authorization, and observability hooks
- period resolution and request normalization
- deciding sync vs async execution policy
- orchestration of upstream retrieval from `lotus-core`
- persistence of execution metadata in PostgreSQL
- returning final responses or job handles

The API Orchestrator must remain latency-oriented and avoid long CPU-bound execution wherever possible.

### 8.3 Deployable service: Stateful Input Service

The Stateful Input Service is responsible for:

- retrieval from `lotus-core`
- paging and retry handling
- long-window chunk planning
- parallel upstream request execution
- chunk reconciliation and canonical merge
- canonical normalization of portfolio, benchmark, and risk-free inputs
- caching and retrieval de-duplication where policy allows
- shielding compute services from upstream contract churn

The Stateful Input Service exists because upstream retrieval has a materially different operational profile from both API serving and analytics execution. Under heavy load, this boundary must scale independently and must not be coupled to compute worker saturation.

### 8.4 Deployable service: Compute Executor

The Compute Executor is responsible for:

- CPU-heavy analytics execution
- chunked or partitioned processing for large datasets
- parallel execution for partition-safe workloads
- deterministic aggregation of partition outputs
- persistence of calculation completion state and artifacts metadata

The key architectural rule is that it must scale independently from the API request-serving tier and from the upstream retrieval tier.

### 8.5 Deployable service: Lineage Service

The Lineage Service is responsible for:

- creating durable lineage job metadata in the request path
- writing lineage manifests
- writing artifact metadata
- storing reproducibility records
- serving lineage lookup and artifact discovery requests
- enforcing retention and immutability policy

This service should remain operationally separate because lineage persistence can be storage-heavy and bursty even when API traffic is moderate.

### 8.5.1 Async lineage policy

Lineage persistence should become asynchronous, but not best-effort only.

The required behavior is:

1. Calculation endpoints remain synchronous unless explicitly redesigned as async execution APIs.
2. The API request path creates a durable lineage metadata record in PostgreSQL before the response is returned.
3. Artifact materialization runs asynchronously after the response path.
4. Lineage retrieval is state-driven, with `pending`, `complete`, and `failed` states.
5. Failures in lineage materialization must be visible and recoverable through durable job state, not lost in process-local logs.

This avoids coupling artifact I/O latency to client response time while preserving banking-grade durability and auditability.

## 9. Merge, Split, Remove, Add Decisions

### 9.1 Merge

Conceptually duplicated retrieval responsibilities should be merged into one dedicated `Stateful Input Service`:

- stateful portfolio sourcing
- benchmark sourcing
- risk-free sourcing

These should no longer remain partly embedded in endpoint code.

### 9.2 Split

Split by operational load profile and runtime concern, not by analytic domain.

Required split:

- API orchestration from stateful retrieval
- API orchestration from compute execution
- compute execution from lineage persistence

Optional later split:

- split compute into interactive and batch executor pools if workload classes diverge materially

Explicitly rejected split for now:

- separate TWR service
- separate MWR service
- separate contribution service
- separate attribution service
- separate returns-series service

### 9.3 Remove

Remove local filesystem storage as the primary durable production persistence pattern for lineage and execution state.

Local disk may remain only as:

- a development convenience
- a temporary artifact cache

### 9.4 Add

Add the following first-class services or service-owned subsystems:

1. `api_orchestrator`
2. `stateful_input_service`
3. `compute_executor`
4. `lineage_service`
5. `execution_registry`
6. `artifact_storage_adapter`
7. `work_partitioning` for large portfolio and long-history compute paths

### 9.5 Dedicated sourcing-service decision

The `Stateful Input Service` is explicitly justified as a separate service boundary, not only as an internal module.

Reason:

- sourcing from `lotus-core` has a fundamentally different scaling profile from analytics execution
- it is dominated by network I/O, paging, retries, and upstream contract handling
- it can experience heavy operational load even when compute concurrency is moderate
- isolating it protects both API latency and compute throughput

This service should own all stateful retrieval from `lotus-core` for `lotus-performance`.

## 10. PostgreSQL Storage Decision

PostgreSQL will be the durable backing store for runtime metadata and control state.

### 10.1 PostgreSQL is the system of record for

- execution requests
- execution lifecycle state
- calculation fingerprints and hashes
- lineage materialization job state
- lineage manifests
- artifact metadata
- upstream retrieval metadata
- diagnostics summaries
- idempotency and deduplication keys
- execution timing and capacity metrics needed for operations

### 10.2 PostgreSQL is not the primary store for

- source portfolio accounting truth
- benchmark master ownership
- risk-free master ownership

Those remain owned by `lotus-core`.

### 10.3 Artifact storage model

The recommended production pattern is:

1. PostgreSQL stores the artifact manifest and metadata.
2. Large artifact payloads are stored in object storage or a durable file store.
3. PostgreSQL stores references, hashes, media types, retention metadata, and immutability flags.

If object storage is not yet introduced, PostgreSQL can temporarily store small JSON artifacts directly, but large CSV payloads should not be persisted indefinitely in-row.

## 11. Proposed PostgreSQL Data Domains

The following logical tables or aggregates are expected.

### 11.1 `analytics_execution`

Purpose:

- one row per execution request

Contains:

- execution id
- calculation id
- analytics type
- sync or async mode
- requested window
- portfolio id
- status
- created/started/completed timestamps
- retry count
- idempotency key
- input fingerprint
- calculation hash

### 11.2 `analytics_execution_stage`

Purpose:

- track internal lifecycle stages

Contains:

- retrieval started/completed
- normalization started/completed
- execution started/completed
- persistence started/completed
- failure stage and reason

### 11.3 `analytics_lineage_manifest`

Purpose:

- durable lineage registry

Contains:

- execution id
- lineage status (`pending`, `complete`, `failed`)
- artifact manifest
- request/response references
- code version
- configuration snapshot
- retention class
- materialization error summary

### 11.4 `analytics_artifact`

Purpose:

- artifact index and integrity tracking

Contains:

- artifact id
- execution id
- artifact type
- storage location
- checksum
- size
- serialization format
- created timestamp

### 11.5 `analytics_upstream_snapshot`

Purpose:

- track what was retrieved from `lotus-core`

Contains:

- upstream endpoint
- source identifiers
- as-of date
- request fingerprint
- response fingerprint
- paging metadata
- retrieval status

## 12. Target Internal Modules

The following internal modules should exist conceptually even if initial implementation stays in one repo/runtime:

### 12.1 `api_orchestrator`

Owns:

- external contracts
- sync/async policy
- request lifecycle

### 12.2 `stateful_input_service`

Owns:

- retrieval from `lotus-core`
- retry policy
- paging
- chunk planning for large historical windows
- parallel upstream retrieval orchestration
- overlap handling and canonical merge
- normalization into canonical engine-ready structures
- benchmark and risk-free retrieval coordination

### 12.2.1 Long-window retrieval strategy

For large historical requests, the `Stateful Input Service` must be allowed to break the requested window into smaller retrieval chunks before calling `lotus-core`.

Example chunking dimensions:

- date-window chunks
- portfolio observation pages
- benchmark series pages
- risk-free series pages

The service may fetch those chunks in parallel subject to:

- upstream concurrency policy
- tenant fairness policy
- rate-limit policy
- end-to-end timeout budget

### 12.2.2 Canonical merge requirements

Chunked upstream retrieval is only valid if the service reconstructs a single canonical logical input before compute begins.

The canonical merge must enforce:

1. stable ordering by business date
2. deterministic duplicate resolution
3. overlap validation between chunks
4. explicit gap detection
5. canonical normalization of numeric precision and field semantics
6. one final input bundle per portfolio/request/series type

The compute layer must never receive arbitrarily fragmented slices without explicit partitioning rules for the metric being calculated.

### 12.3 `compute_executor`

Owns:

- running TWR, MWR, contribution, attribution, and returns-series derivations
- partition-safe parallel execution
- deterministic recombination

### 12.4 `execution_registry`

Owns:

- PostgreSQL persistence of execution lifecycle
- idempotency
- deduplication
- status querying

### 12.5 `lineage_service`

Owns:

- lineage manifests
- artifact metadata
- reproducibility metadata
- lineage read APIs and retention policy enforcement

## 12.6 Service Interaction Model

The preferred interaction model is:

1. API Orchestrator receives request and classifies workload.
2. For `stateful` mode, API Orchestrator calls Stateful Input Service.
3. Stateful Input Service retrieves and normalizes canonical input bundles.
4. API Orchestrator submits canonical work to Compute Executor.
5. Compute Executor writes execution status and result metadata to PostgreSQL.
6. Lineage Service persists manifests and artifact references.
7. API Orchestrator returns either:
   - synchronous final result, or
   - asynchronous execution handle

This model ensures each service can be scaled according to its own bottleneck:

- API Orchestrator for request concurrency
- Stateful Input Service for upstream I/O pressure
- Compute Executor for CPU and memory pressure
- Lineage Service for storage throughput and retention operations

## 12.7 Upstream chunking and parallel retrieval

The preferred pattern for long stateful windows is:

1. API Orchestrator classifies the request as a long-window stateful workload.
2. Stateful Input Service computes a retrieval plan.
3. The retrieval plan breaks the full window into bounded chunks.
4. Chunks are fetched from `lotus-core` in parallel.
5. Results are merged into a canonical continuous time series.
6. Canonicalized inputs are handed to the Compute Executor.

This is the default optimization path for long-window stateful sourcing.

The primary performance lever should be parallelized retrieval first, before attempting aggressive metric-level compute partitioning.

## 13. Scaling Strategy

### 13.1 Synchronous path

Keep synchronous execution for:

- small and medium interactive workloads
- deterministic low-latency requests

Examples:

- small TWR windows
- MWR
- moderate returns-series requests

### 13.2 Async or executor-offloaded path

Offload to executor for:

- large historical windows
- contribution over many positions
- attribution over large grouped or instrument panels
- multi-portfolio or composite-scale workloads introduced later

### 13.3 Parallel processing principles

Parallelize only where financial determinism is preserved.

Safe candidates:

- independent portfolio execution
- independent period-bucket preprocessing
- position-level contribution preprocessing before deterministic aggregation
- group-level attribution preprocessing before deterministic final aggregation
- upstream retrieval chunking followed by canonical merge before compute

Unsafe or caution-required areas:

- any step where compounding, smoothing, or residual allocation depends on total-order semantics

### 13.4 Safe vs unsafe compute chunking

Retrieval chunking and compute chunking are different decisions.

#### Safe by default

- chunking upstream calls to `lotus-core`
- fetching chunks in parallel
- merging chunks into one canonical ordered input bundle before compute

#### Conditionally safe

- partitioned contribution preprocessing when final reconciliation is deterministic
- partitioned attribution preprocessing when final group-level aggregation preserves exact semantics
- partitioned multi-portfolio batch workloads where each portfolio is independent

#### Not safe by default

- calculating TWR independently by chunk and summing or averaging chunk outputs
- calculating attribution independently by chunk and combining results without explicit linking math
- calculating smoothed contribution independently by chunk without preserving required whole-period context
- any chunking strategy that changes reset behavior, cumulative return ladders, or residual allocation

The architectural rule is:

- chunk retrieval freely
- chunk compute only when the metric has an explicit mathematically valid recombination strategy

## 14. Correctness and Reliability Rules

The architecture must preserve these invariants:

1. The same canonical input must produce the same output regardless of execution placement.
2. Parallel execution must not change rounding, ordering, or reconciliation results.
3. PostgreSQL-backed execution state must support idempotent retries.
4. Lineage and artifact references must remain queryable after process restart or node loss.
5. Upstream retrieval metadata must be sufficient to explain what data was used for each result.
6. Service-to-service boundaries must not permit inconsistent rounding, differing default policies, or divergent normalization semantics.
7. Parallel chunk retrieval must reconstruct the same canonical input that a single full-window retrieval would have produced.
8. Partitioned compute must produce the same result as canonical single-bundle compute for the same input.

## 15. Interaction with lotus-core

`lotus-core` remains the authoritative owner of:

- portfolio analytics time series inputs
- benchmark assignment
- benchmark return series or benchmark source contracts
- risk-free source contracts

`lotus-performance` owns:

- how those inputs are normalized
- how performance analytics are computed
- how execution is scaled and audited

This keeps source-of-truth ownership separate from computational ownership.

## 16. Recommended Rollout

### Phase 1

- introduce PostgreSQL-backed execution and lineage registries
- extract stateful retrieval into a dedicated service-owned module
- move lineage manifest persistence off filesystem-first design
- keep deployment topology single-binary if needed, but with hard internal service seams
- implement retrieval planning, chunked upstream fetch, and canonical merge rules inside the stateful input boundary

### Phase 2

- deploy Stateful Input Service as an independently scalable runtime
- introduce Compute Executor boundary
- route heavy analytics to executor
- preserve synchronous path for small requests
- enable bounded parallel chunk retrieval for long stateful windows

### Phase 3

- deploy Lineage Service as an independently scalable runtime
- add workload classification and admission control
- add partitioned execution strategies for large contribution and attribution jobs
- add artifact storage abstraction backed by durable object storage
- add metric-specific proofs and tests for any compute chunking strategy before production use

## 17. Acceptance Criteria

This RFC is considered implemented when:

1. `lotus-performance` still presents one coherent business API surface.
2. Stateful retrieval, compute execution, and lineage persistence can each scale independently.
3. Heavy analytics execution can scale independently from API request serving.
4. PostgreSQL is the durable store for execution metadata and lineage metadata.
5. Filesystem storage is no longer the primary production durability mechanism.
6. Stateful retrieval from `lotus-core` is centralized in a dedicated service-owned subsystem.
7. Repeated execution of the same canonical request is idempotent and reproducible.
8. Long-window stateful sourcing supports chunked parallel retrieval with deterministic canonical merge.
9. Any enabled compute partitioning strategy is proven equivalent to single-bundle execution for the relevant metric class.

## 18. Final Decision Summary

The architecture should not fragment by analytics domain.

The correct move is:

- keep one `lotus-performance` business service
- split API orchestration, stateful retrieval, compute execution, and lineage persistence into clear services
- centralize stateful retrieval from `lotus-core` in its own independently scalable boundary
- use PostgreSQL for durable operational and lineage state

This gives `lotus-performance` a scalable and banking-grade architecture without unnecessary microservice sprawl.
