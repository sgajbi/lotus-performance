# Integrations

## Downstream consumers

Primary downstream consumers include:

- `lotus-gateway`
- selected `lotus-risk` stateful workflows
- operator and support tooling that consumes execution, runtime, and lineage surfaces

## Upstream dependencies

`lotus-performance` consumes `lotus-core` for governed source data and analytics-input contracts.
It does not outsource performance conclusions to `lotus-core`.

Current transport posture:

- control-plane base URL:
  `CORE_CONTROL_PLANE_BASE_URL`
- compatibility fallback:
  `CORE_QUERY_BASE_URL`
- no current gRPC contract

Governed base-URL examples:

1. `http://core-control.dev.lotus`
2. `http://127.0.0.1:8202`
3. `http://host.docker.internal:8202`
4. `http://lotus-core-control:8002`

## Contract grouping

- analytics surfaces:
  TWR, MWR, benchmark, workspace summary, contribution, attribution
- integration surfaces:
  returns-series, benchmark exposure context, capabilities
- operator surfaces:
  execution polling, lineage, runtime status, work items, recoveries, drills, retention

## Stateful MWR source flow

Stateful MWR is a source-owned performance methodology path. `lotus-performance` retrieves
portfolio analytics timeseries from `lotus-core`, normalizes the investor capital-flow schedule,
and emits MWR plus supportability metadata for downstream consumers.
Gateway and Workbench should consume the emitted MWR response as source-owned performance truth;
they must not reconstruct cash flows from TWR, benchmark, or workspace summary payloads.
Gateway should preserve calculation-quality fields (`status`, `reason_codes`, `warnings`,
`fallback_reason`, `is_approximation`, and `holding_period_return`) because they explain whether the
client-facing number is annualized XIRR, a labeled Dietz fallback, or not calculable.
The implementation-backed Lotus production control guide is maintained at
[docs/guides/mwr-lotus-production-controls.md](../docs/guides/mwr-lotus-production-controls.md).

```mermaid
flowchart LR
    A[lotus-core portfolio timeseries] --> B[lotus-performance stateful MWR normalization]
    B --> C[begin_mv / end_mv / cashflows_used / start_date]
    C --> D[XIRR root scan or Dietz engine path]
    D --> E[MWR response + status + fallback metadata + calculation_supportability]
    E --> F[lotus-gateway performance contract preserves metadata]
    F --> G[Workbench investor capital-timing lens]
```

## Stateful contribution source flow

Stateful contribution is a source-normalized performance methodology path. `lotus-performance`
retrieves portfolio and position timeseries from `lotus-core`, normalizes source rows into the
contribution engine request shape, and emits total, local, and FX contribution with bounded
supportability metadata. Gateway, Workbench, risk, and reporting consumers should consume the
emitted contribution response; they must not reconstruct position contribution from TWR, MWR,
attribution, or raw source rows.

```mermaid
flowchart LR
    A[lotus-core portfolio timeseries] --> C[lotus-performance stateful contribution normalization]
    B[lotus-core position timeseries] --> C
    C --> D[portfolio_data / positions_data / dimensions / source currency metadata]
    D --> E[Contribution engine: total / local / FX]
    E --> F[Contribution response + calculation_supportability]
    F --> G[Gateway, Workbench, risk, and reporting consumers]
```

## Stateful attribution source flow

Stateful attribution is a source-normalized performance methodology path. `lotus-performance`
retrieves portfolio and position timeseries from `lotus-core`, resolves benchmark assignment or an
explicit benchmark override, sources benchmark component inputs through the shared benchmark engine
path, and normalizes source currency evidence for the multi-currency branch. Gateway, Workbench,
risk, and reporting consumers should consume the emitted attribution response; they must not
reconstruct allocation, selection, interaction, active return, or currency attribution from
contribution, TWR, MWR, benchmark, or raw source rows.

```mermaid
flowchart LR
    A[lotus-core portfolio timeseries] --> D[lotus-performance stateful attribution normalization]
    B[lotus-core position timeseries] --> D
    C[lotus-core benchmark assignment / component inputs / FX evidence] --> D
    D --> E[portfolio groups / benchmark groups / source currency metadata]
    E --> F[Attribution engine: allocation / selection / interaction / active return / currency effects]
    F --> G[Attribution response + calculation_supportability + benchmark_context]
    G --> H[Gateway, Workbench, risk, and reporting consumers]
```

## References

- [docs/technical/RFC-0082-upstream-contract-family-map.md](../docs/technical/RFC-0082-upstream-contract-family-map.md)
- [docs/guides/api_reference.md](../docs/guides/api_reference.md)
