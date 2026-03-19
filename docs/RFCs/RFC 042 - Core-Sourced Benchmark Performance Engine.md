# RFC 042 - Core-Sourced Benchmark Performance Engine

**Status:** In Progress  
**Owner:** lotus-performance  
**Reviewers:** lotus-core, lotus-performance, lotus-platform  
**Related:** RFC-023, RFC-018, RFC-020, RFC-039, RFC-040, RFC-041

## 1. Executive Summary

This RFC defines a benchmark performance engine in `lotus-performance`.

The engine is responsible for calculating benchmark daily performance from benchmark component market data sourced from `lotus-core`. `lotus-performance` will not depend on `lotus-core` to provide precomputed benchmark performance as the default or primary contract. Instead, `lotus-core` will remain the system of record for benchmark reference data, benchmark-to-portfolio linkage, index/component metadata, benchmark compositions, effective-dated weights, benchmark currency, and index prices or market series inputs required for calculation.

`lotus-performance` will:
- source benchmark composition and component market data from `lotus-core`
- calculate daily component returns in benchmark currency
- calculate daily component contributions using effective benchmark weights
- sum component contributions into daily benchmark returns
- geometrically link daily benchmark returns into benchmark return for any requested period
- expose the benchmark result through the TWR path when `include_benchmark=true`
- expose the benchmark result through a dedicated benchmark analytics endpoint
- reuse the same calculated benchmark series for attribution and other active analytics
- allow explicit API configuration to consume upstream vendor benchmark return series when a caller deliberately requests that mode
- calculate arithmetic relative performance and cumulative relative performance when TWR is requested with benchmark output

This engine must remain stateless and must follow the same separation of concerns already established for stateful portfolio analytics:
- `lotus-core` owns source data and reference data
- `lotus-performance` owns analytics calculation
- orchestration and sourcing stay outside engine math

## 2. Problem Statement

`lotus-performance` already supports:
- stateful portfolio return sourcing
- stateful benchmark assignment sourcing
- benchmark return-series retrieval
- benchmark market-series retrieval for attribution

What it does not yet own cleanly is benchmark performance calculation as a first-class analytics engine.

Current gaps:
1. `returns-series` can source benchmark return series from `lotus-core`, but benchmark calculation is not a first-class owned engine in `lotus-performance`.
2. attribution currently builds benchmark group inputs from sourced benchmark market series, but that logic is attribution-specific and not a reusable benchmark performance engine.
3. TWR benchmark inclusion is currently driven by an optional nested `benchmark` object, not by a simple top-level inclusion flag aligned to existing Lotus vocabulary.
4. TWR does not yet expose relative performance or cumulative relative performance when benchmark output is requested.
5. older RFC-023 assumes caller-supplied benchmark series and a `benchmark_spec` contract, which does not match the current desired ecosystem architecture.

## 3. Goals

1. Build a benchmark performance engine in `lotus-performance`.
2. Keep the engine stateless and calculation-focused.
3. Source all required benchmark data from `lotus-core`.
4. Calculate benchmark daily returns from component-level source data.
5. Geometrically link benchmark daily returns into period returns using the same return ownership principles as portfolio TWR.
6. Expose benchmark return alongside portfolio return through the TWR API when requested.
7. Reuse the same benchmark engine outputs for attribution and later active analytics.
8. Preserve clear microservice separation:
   - sourcing/orchestration layer
   - normalization layer
   - benchmark math engine
9. Keep naming and API style aligned with Lotus vocabulary and the existing stateful/stateless request model.
10. Default benchmark execution to self-calculated returns in `lotus-performance`, not upstream vendor return ingestion.
11. Support benchmark inclusion in TWR through a top-level boolean flag using existing Lotus vocabulary.
12. Allow callers to override the normal portfolio-to-benchmark assignment by supplying a benchmark ID, while still sourcing benchmark definition and market data from `lotus-core`.
13. Emit arithmetic relative performance and cumulative relative performance whenever benchmark output is included in TWR.

## 4. Non-Goals

1. This RFC does not make `lotus-performance` the system of record for benchmark definitions.
2. This RFC does not implement benchmark construction or optimization tooling.
3. This RFC does not move benchmark master-data ownership out of `lotus-core`.
4. This RFC does not fully solve benchmark-local plus FX attribution decomposition if upstream contracts for that remain incomplete.
5. This RFC does not introduce a free-form caller-defined `benchmark_spec` as the primary stateful contract.

## 5. Desired Architecture

### 5.1 Ownership split

`lotus-core` owns:
- benchmark assignment to portfolio
- benchmark identifiers and benchmark metadata
- effective-dated benchmark compositions
- benchmark component universe
- benchmark currency
- index metadata
- component price or market-series inputs
- any required corporate-action-adjusted index source data

`lotus-performance` owns:
- benchmark daily return calculation
- benchmark daily contribution calculation
- benchmark period linking
- FX normalization into benchmark currency when component series are not already delivered in benchmark currency
- active analytics consumption of the resulting benchmark series
- diagnostics, lineage, execution, and reproducibility around the benchmark calculation path

### 5.2 Separation of responsibilities

The architecture should mirror the portfolio stateful pattern already in the repo:

1. `core_integration_service.py`
   - HTTP contract to `lotus-core`
2. `stateful_input_service.py`
   - chunked retrieval, paging, durable upstream snapshots, resilience
3. benchmark normalization layer
   - parse benchmark composition and market inputs into canonical internal inputs
4. `engine/benchmarks.py`
   - pure benchmark math
5. endpoint/mode services
   - decide stateless vs stateful mode
   - build resolved stateless engine requests
   - enforce default self-calculated benchmark policy unless an explicit return-source override is requested
   - keep TWR/attribution callers clean

The benchmark engine must not contain HTTP, persistence, execution-registry, or upstream-contract logic.

## 6. Benchmark Calculation Methodology

### 6.1 Inputs

For each benchmark component and each date in the requested range, the engine needs:
- component identifier
- benchmark currency
- effective component weight for the day or effective segment
- component price level or equivalent index market value series
- component currency
- FX inputs if the component series is not already in benchmark currency

### 6.2 Daily component return

For each component `i` on day `t`, daily return is:

`r_i,t = (P_i,t / P_i,t-1) - 1`

where `P_i,t` is the component index level expressed in the benchmark currency.

If source prices are not already in benchmark currency, they must be converted first using the applicable FX rate policy before return calculation.

### 6.3 Daily component contribution

For each component `i` on day `t`, daily benchmark contribution is:

`c_i,t = w_i,t-1 * r_i,t`

where `w_i,t-1` is the effective beginning-of-day weight for the component.

### 6.4 Daily benchmark return

Daily benchmark return is:

`R_bm,t = Σ c_i,t`

### 6.5 Period benchmark return

Benchmark period return is the geometric link of daily benchmark returns:

`R_bm,period = Π (1 + R_bm,t) - 1`

This should use the same period-linking ownership and date semantics already governed for TWR.

### 6.6 Weight semantics

Benchmark compositions may be:
- static over the requested period
- effective-dated, where weights change on specific dates

This RFC assumes effective-dated weight schedules sourced from `lotus-core`. Weight application is beginning-of-day effective for the day’s return contribution.

This RFC does not assume `lotus-performance` must infer rebalances from drifting weights unless that becomes an explicit upstream contract.

## 7. API Direction

### 7.1 TWR

`POST /performance/twr` should support benchmark return output when benchmark is requested in either:
- stateless mode with caller-supplied benchmark inputs
- stateful mode with benchmark assignment and benchmark data sourced from `lotus-core`

The response should include benchmark return as a parallel computed result, not as an attribution-specific afterthought.

#### 7.1.1 Request shape

The TWR surface should use the existing Lotus vocabulary term `include_benchmark` as the top-level switch.

Why this is the right term:
- it already exists in `lotus-performance` vocabulary and public contracts for `returns-series`
- it reads cleanly as a capability toggle rather than a mode selector
- it keeps TWR aligned with established Lotus naming instead of inventing a near-duplicate such as `with_benchmark` or `benchmark_requested`

Recommended request direction:
- add `include_benchmark: bool = false` to the TWR request
- keep the nested `benchmark` object as optional configuration, not as the inclusion switch itself
- require `benchmark` to be absent when `include_benchmark=false`
- allow `benchmark` to be omitted when `include_benchmark=true` and `input_mode=stateful`, in which case benchmark assignment should be sourced from `lotus-core`
- allow `benchmark.benchmark_id` to be supplied when `include_benchmark=true` to override the normal portfolio-to-benchmark assignment while still sourcing the benchmark definition and market data from `lotus-core`

This gives TWR the desired flexibility:
1. simple benchmark-on request: `include_benchmark=true`
2. normal stateful benchmark path: assignment sourced from `lotus-core`
3. explicit override path: caller supplies `benchmark_id`
4. full stateless path: caller supplies benchmark inputs directly

#### 7.1.2 Benchmark resolution precedence

When `include_benchmark=true`, benchmark selection should follow this precedence:

1. explicit `benchmark.benchmark_id` provided by caller
2. stateful benchmark assignment sourced from `lotus-core`
3. validation error if neither is available

This keeps the caller override explicit while preserving the default portfolio-to-benchmark linkage from `lotus-core`.

#### 7.1.3 Response shape

When `include_benchmark=true`, TWR should return:
- portfolio TWR
- benchmark TWR
- relative performance
- cumulative relative performance

The benchmark block should remain a first-class sibling result, and each resolved period result should also include a dedicated relative-performance block.

Recommended response direction:
- keep the existing benchmark result block for benchmark performance details
- add `relative_performance` under each period result

Recommended relative-performance fields:
- `arithmetic_relative_return`
- `cumulative_arithmetic_relative_return`

Relative performance should be defined as:

`arithmetic_relative_return = portfolio_return - benchmark_return`

Cumulative relative performance should be defined as:

`cumulative_arithmetic_relative_return = cumulative_portfolio_return - cumulative_benchmark_return`

This is intentionally arithmetic relative performance, not geometrically linked active return.

#### 7.1.4 Current implementation status

Current branch reality is close, but not complete:
- implemented:
  - optional nested benchmark request on TWR
  - stateful assignment lookup from `lotus-core` when `benchmark_id` is omitted
  - explicit `benchmark_id` override support
  - shared benchmark engine reuse
- still to add:
  - top-level `include_benchmark` flag
  - validation coupling between `include_benchmark` and the nested `benchmark` configuration object
  - arithmetic relative performance in TWR response
  - cumulative relative performance in TWR response

### 7.2 Attribution

Attribution should consume the benchmark engine output or a closely related normalized benchmark series path, rather than embedding benchmark calculation logic inside attribution-only sourcing code.

### 7.3 Dedicated benchmark endpoint

In addition to TWR integration, `lotus-performance` should expose the benchmark engine directly as a first-class analytics surface.

Recommendation:
- use the same Lotus dual-mode contract style as TWR/MWR/Contribution/Attribution
- keep naming and payload vocabulary aligned with the rest of the service
- expose both stateful and stateless modes
- default to `return_source="calculated"`
- support an explicit override such as `return_source="vendor_series"` only when the caller intentionally opts into it

### 7.4 Helper surface

We still need an internal shared benchmark service first, even with a public benchmark endpoint.

Recommendation:
- Phase 1: internal engine and shared service
- Phase 2: public benchmark analytics endpoint
- Phase 3: TWR and attribution convergence on the same benchmark engine

## 8. lotus-core Contract Expectations

This RFC depends on `lotus-core` exposing clean reusable source contracts, including:

1. benchmark assignment
   - `portfolio_id + as_of/window -> benchmark_id`
2. benchmark definition
   - benchmark metadata
   - benchmark currency
3. benchmark composition
   - effective-dated component list and weights
4. component market series
   - price/index-level series for each benchmark component
   - enough metadata to know component currency and calculation convention
5. reference metadata
   - component/index identifiers and normalization fields

The contracts should support broader Lotus reuse, not just `lotus-performance`.

### 8.1 Current `lotus-core` reality

Current `lotus-core` benchmark-facing contracts already provide a strong base:
- effective portfolio benchmark assignment
- effective benchmark definition
- benchmark catalog
- raw index price series
- raw index return series
- raw benchmark return series
- benchmark market series envelopes for attribution-oriented workflows
- FX rate retrieval

However, there were two important gaps relative to this RFC:

1. window-aware composition expansion
   - this has now been addressed in `lotus-core` through a composition-window contract returning overlapping effective-dated composition segments
   - `lotus-performance` now consumes that contract directly for calculated stateful benchmark execution across rebalance windows

2. component-to-benchmark-currency normalization
   - current benchmark market-series responses can include `fx_rate`, but that FX enrichment is target-currency context, not a guaranteed component-price-normalized-to-benchmark-currency contract
   - component rows still carry raw `index_price`, raw `index_return`, and optional `series_currency` through the underlying index series contracts
   - benchmark math therefore still needs explicit FX normalization ownership unless `lotus-core` adds a stronger normalized component-series contract

3. benchmark-return usage mode clarity
   - `lotus-core` does expose raw vendor benchmark return series
   - those are useful as reference, validation, and optionally caller-selected fallback inputs
   - they should not be treated as the default benchmark calculation path for `lotus-performance`

This TWR enhancement does not add a new mandatory `lotus-core` contract beyond the benchmark requirements already captured in this RFC:
- benchmark assignment already covers the default stateful mapping path
- benchmark definition and market data already cover the explicit `benchmark_id` override path
- relative-performance calculation remains fully inside `lotus-performance`

### 8.2 Recommended `lotus-core` enhancements

The current APIs are good enough to start, but the following upstream improvements would materially improve scalability and contract clarity:

1. benchmark composition window contract
   - implemented in `lotus-core`
   - returns effective-dated composition segments overlapping a requested date range
   - this is the correct upstream shape because it stays compact while still being deterministic

2. optional normalized component series contract
   - either:
     - extend benchmark market series to include component series normalized into benchmark currency
   - or:
     - add a companion contract that returns component FX-normalized prices/returns with explicit normalization policy metadata
   - without this, `lotus-performance` should own FX normalization

3. benchmark market-series paging/chunking
   - if benchmark universes get large, the benchmark component-series contract should support deterministic paging similar to analytics timeseries endpoints
   - this matters for broad ecosystem reuse, not only `lotus-performance`

## 9. Review of Existing RFC-023

RFC-023 is no longer sufficient as the governing design for this work.

Why:
1. It assumes caller-supplied benchmark data as the primary design.
2. It centers on a free-form `benchmark_spec`, which is weaker than the current Lotus architecture where benchmark ownership belongs in `lotus-core`.
3. It blends benchmark-definition ownership and benchmark-calculation ownership too loosely.

Recommendation:
- do not implement RFC-023 as written
- keep it as historical context
- supersede its benchmark-engine direction with this RFC

## 10. Decisions and Remaining Questions

The following design decisions are now set for this RFC:

1. Source contract shape
   - baseline assumption: `lotus-core` should provide effective-dated composition segments, not daily-expanded weights as the primary contract
   - daily expansion can remain an implementation detail in `lotus-performance` if needed

2. Currency policy
   - `lotus-performance` should own FX normalization into benchmark currency unless and until `lotus-core` provides a stronger normalized component-series contract
   - current `lotus-core` APIs do not appear to fully satisfy this normalization requirement today

3. Weight timing
   - weights are beginning-of-day effective

4. Public API scope
   - support both:
     - TWR integration
     - dedicated benchmark analytics endpoint

5. Stateless contract
   - support stateless mode in the same Lotus dual-mode style as the other analytics surfaces

6. Default benchmark source policy
   - default benchmark return source is self-calculated in `lotus-performance`
   - upstream raw benchmark return series may be supported only through explicit API configuration, not implicit default behavior

7. TWR benchmark inclusion contract
   - TWR should use top-level `include_benchmark` as the canonical inclusion flag
   - the nested `benchmark` object should remain configuration-only
   - explicit caller-provided `benchmark_id` should override stateful assignment lookup when present

8. Relative performance semantics
   - TWR relative performance is arithmetic
   - cumulative relative performance is the arithmetic difference of cumulative portfolio and benchmark returns
   - this is not a geometric active-return linking contract

Remaining questions before implementation:

1. Stateless payload shape
   - should the primary stateless benchmark contract take:
     - component prices
     - component returns
     - or a union that supports both with one canonical normalization path?
   - recommendation: support component prices and component returns, normalize both into one internal engine input model

2. Missing-data behavior
   - if a required component price or FX rate is missing on a day, should the engine:
     - fail hard
     - skip the day
     - or defer to an explicit robustness policy?
   - recommendation: fail hard by default for the first implementation

3. Explicit vendor return mode shape
   - if vendor `benchmark_return` is allowed, what is the exact public configuration field and vocabulary?
   - recommendation: support it only as an explicit non-default `return_source` mode, with clear lineage showing the source path used

4. TWR response placement
   - should `relative_performance` live only inside each `results_by_period[*]`, or also in the top-level benchmark block?
   - recommendation: keep it inside each period result, because relative performance is period-resolved output, not benchmark metadata

## 11. Recommended Implementation Phases

### Phase 1: Internal benchmark engine

Create:
- `engine/benchmarks.py`
- benchmark input/output models
- unit methodology tests

Output:
- daily component returns
- daily component contributions
- daily benchmark returns
- linked benchmark period return

### Phase 2: Stateful benchmark sourcing

Create:
- shared stateful benchmark input normalizer
- chunked benchmark component market retrieval through `stateful_input_service.py`
- FX normalization path in `lotus-performance`
- durable upstream snapshots and lineage

### Phase 3: Dedicated benchmark endpoint

Add a first-class benchmark endpoint:
- stateless
- stateful
- default self-calculated benchmark returns
- explicit optional vendor-series mode only if requested

### Phase 4: TWR integration

Add benchmark result support to TWR:
- stateless
- stateful
- top-level `include_benchmark`
- explicit `benchmark_id` override
- arithmetic relative performance
- cumulative relative performance

### Phase 5: Attribution convergence

Refactor attribution benchmark preparation to consume the shared benchmark engine inputs/outputs instead of bespoke attribution-only shaping where feasible.

## 12. Testing Strategy

We should require:

1. unit tests
   - component return calculation
   - contribution calculation
   - geometric linking
   - effective-dated weight changes
   - missing-data and currency-policy handling

2. integration tests
   - stateful benchmark sourcing from mocked `lotus-core`
   - calculated stateful benchmark execution across multi-segment rebalance windows
   - TWR with benchmark requested
   - TWR with `include_benchmark=true` and implicit assignment lookup
   - TWR with `include_benchmark=true` and explicit `benchmark_id` override
   - TWR relative and cumulative relative output correctness
   - attribution consuming benchmark engine output

3. end-to-end tests
   - seeded `lotus-core` portfolio with linked benchmark
   - `lotus-performance` computes both portfolio and benchmark results correctly

4. characterization/performance tests
   - long-window benchmark sourcing
   - large benchmark-component universe
   - async promotion where resolved sourced workload is large

## 13. Acceptance Criteria

This RFC is ready for implementation when approved with answers to the open questions above.

Implementation is complete when:
1. `lotus-performance` owns a benchmark performance engine with pure calculation logic.
2. Stateful benchmark sourcing from `lotus-core` is implemented through the shared sourcing architecture.
3. TWR can emit benchmark return when requested through `include_benchmark=true`.
4. TWR emits arithmetic relative performance and cumulative relative performance when benchmark output is included.
5. Attribution reuses the benchmark engine path or its normalized outputs instead of duplicating benchmark math.
6. The behavior is covered with meaningful unit, integration, and end-to-end tests.
7. Docs and API contracts are updated to reflect the benchmark engine as a first-class capability.
