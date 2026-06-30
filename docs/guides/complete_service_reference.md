# Complete Service Reference

This document is the single consolidated reference for `lotus-performance`.

Use it when you want one place that covers:

- all public APIs
- major service features
- runtime and analytics configuration
- sample requests and sample responses

Canonical machine-readable contract:

- Swagger UI: `/docs`
- OpenAPI JSON: `/openapi.json`

Companion documents:

- human endpoint map: [api_reference.md](api_reference.md)
- workspace summary deep guide: [workspace_summary.md](workspace_summary.md)
- TWR inspection check inventory: [twr_inspection_checks.md](twr_inspection_checks.md)
- methodology index: [../technical/methodology_index.md](../technical/methodology_index.md)

## Service Features

`lotus-performance` currently owns these major capabilities:

- time-weighted return analytics
- money-weighted return analytics
- benchmark performance analytics
- contribution analytics
- attribution analytics
- composite performance analytics from persisted member-return facts
- interaction-efficient multi-horizon workspace summary
- canonical returns-series integration
- async execution offload for heavier workloads
- execution polling and durable result retrieval
- TWR inspection and supportability triage
- lineage status and artifact retrieval
- integration capability discovery
- runtime status, work-item inspection, and recovery inspection
- governed recovery-drill and runtime-retention control-plane actions
- health and Prometheus metrics surfaces

## Runtime Topology

Default deployment topology:

1. `performance-analytics`
2. `performance-compute-executor`
3. `performance-lineage-worker`
4. `performance-lineage-db`

## API Inventory

### Performance APIs

| Endpoint | Purpose | Sync / Async |
| --- | --- | --- |
| `POST /performance/twr` | calculate portfolio TWR | both |
| `GET /performance/twr/results/{calculation_id}` | retrieve async TWR result | async retrieval |
| `POST /performance/mwr` | calculate portfolio MWR | sync |
| `POST /performance/workspace-summary` | calculate interaction-efficient workspace summary | both |
| `GET /performance/workspace-summary/results/{calculation_id}` | retrieve async workspace-summary result | async retrieval |
| `POST /performance/benchmark` | calculate benchmark performance | both |
| `GET /performance/benchmark/results/{calculation_id}` | retrieve async benchmark result | async retrieval |
| `POST /performance/contribution` | calculate contribution | both |
| `GET /performance/contribution/results/{calculation_id}` | retrieve async contribution result | async retrieval |
| `POST /performance/attribution` | calculate attribution | both |
| `GET /performance/attribution/results/{calculation_id}` | retrieve async attribution result | async retrieval |
| `POST /performance/composites/twr` | calculate composite TWR from persisted member-return facts | sync |
| `POST /performance/composites/inspect` | inspect composite persisted facts and classified evidence artifacts | sync |
| `POST /performance/inspections/twr` | submit durable TWR supportability inspection | async |
| `GET /performance/inspections/{inspection_id}` | retrieve durable TWR inspection status or result | async retrieval |
| `GET /performance/inspections/{inspection_id}/artifacts/{artifact_name}` | download one TWR inspection artifact | async retrieval |
| `GET /performance/executions/{calculation_id}` | poll durable execution state | sync |
| `GET /performance/lineage/{calculation_id}` | inspect lineage status and artifact inventory | sync |
| `GET /performance/lineage/{calculation_id}/artifacts/{artifact_name}` | download one lineage artifact | sync |

### Integration APIs

| Endpoint | Purpose |
| --- | --- |
| `GET /integration/capabilities` | advertise supported analytics surfaces and options |
| `POST /integration/returns/series` | canonical returns-series surface |
| `GET /integration/returns/series/results/{calculation_id}` | retrieve async returns-series result |
| `POST /integration/benchmarks/exposure-context` | benchmark exposure history for downstream active-risk attribution |
| `GET /integration/runtime-status` | bounded runtime health snapshot |
| `GET /integration/runtime-work-items` | queue/work-item inspection |
| `GET /integration/runtime-recoveries` | recovery-event inspection |
| `GET /integration/recovery-drills` | retained recovery-drill history |
| `POST /integration/recovery-drills/run` | execute governed recovery drill |
| `GET /integration/runtime-retention-cleanups` | retained retention-cleanup history |
| `POST /integration/runtime-retention-cleanups/run` | execute governed retention cleanup |

### Health and Observability APIs

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | basic service health |
| `GET /health/live` | liveness |
| `GET /health/ready` | readiness including durable-store and lineage-storage checks |
| `GET /metrics` | Prometheus metrics |
| `GET /` | service entry |

## Public API Reference

The samples below are intentionally short and representative. For field-level schema detail, use
`/docs`. For longer JSON examples, use `docs/examples/*.json`.

### `POST /performance/twr`

Purpose:

- calculate time-weighted return for a portfolio
- supports `stateless` and `stateful` input modes
- can optionally include benchmark performance

Sample request:

```json
{
  "input_mode": "stateless",
  "portfolio_id": "PORT_001",
  "performance_start_date": "2026-01-01",
  "report_end_date": "2026-03-31",
  "metric_basis": "NET",
  "analyses": [
    { "period": "YTD", "frequencies": ["daily", "monthly"] }
  ],
  "include_benchmark": true,
  "stateless_input": {
    "valuation_points": [
      { "perf_date": "2026-01-02", "begin_mv": 1000000.0, "end_mv": 1008500.0 },
      { "perf_date": "2026-03-31", "begin_mv": 1039500.0, "eod_cf": -5000.0, "mgmt_fees": -350.0, "end_mv": 1054100.0 }
    ]
  },
  "benchmark": {
    "benchmark_id": "BMK_GLOBAL_60_40",
    "input_mode": "stateless",
    "return_source": "vendor_series",
    "stateless_input": {
      "benchmark_currency": "USD",
      "benchmark_return_points": [
        { "perf_date": "2026-01-02", "benchmark_return": 0.0065 },
        { "perf_date": "2026-03-31", "benchmark_return": 0.009 }
      ]
    }
  }
}
```

Sample response:

```json
{
  "calculation_id": "6af3a15f-8b95-4b4f-9c4c-6bb9f4d86a91",
  "portfolio_id": "PORT_001",
  "input_mode": "stateless",
  "benchmark_context": {
    "benchmark_id": "BMK_GLOBAL_60_40",
    "benchmark_currency": "USD",
    "input_mode": "stateless",
    "return_source": "vendor_series"
  },
  "results_by_period": {
    "YTD": {
      "portfolio_return": { "base": 3.41, "local": 3.18, "fx": 0.23 },
      "benchmark": {
        "benchmark_id": "BMK_GLOBAL_60_40",
        "summary": { "period_return": { "base": 2.98 }, "cumulative_return": { "base": 2.98 } }
      },
      "relative_performance": { "base": 0.43 }
    }
  }
}
```

Async result route:

- `GET /performance/twr/results/{calculation_id}`

### `POST /performance/inspections/twr`

Purpose:

- submit a durable TWR supportability inspection
- keep supportability and source-quality triage separate from the core TWR calculation path
- inspect either an existing TWR calculation or a proposed TWR request

Sample request:

```json
{
  "inspection_id": "2b2f1c24-b241-420d-a3ad-54c6d254fa56",
  "subject_type": "twr_calculation",
  "subject_calculation_id": "6af3a15f-8b95-4b4f-9c4c-6bb9f4d86a91",
  "inspection_profile": "support_triage"
}
```

Supported request controls:

- `subject_type`: `twr_calculation` or `twr_request`
- `inspection_profile`: `support_triage`, `canonical_validation`, or `deep_reconciliation`

Async result route:

- `GET /performance/inspections/{inspection_id}`

Artifact route:

- `GET /performance/inspections/{inspection_id}/artifacts/{artifact_name}`
- base artifact set always includes `inspection_summary.json` and `findings.json`
- `source_quality_summary.json` is also emitted when source-quality checks run
- `reconciliation_summary.json` is also emitted when stateful reconciliation runs
- `source_economics_summary.json` is also emitted when raw stateful portfolio source-economics checks run
- current reconciliation checks cover mixed position epochs, duplicate position snapshot rows, invalid epoch labels, invalid selected position end values, portfolio-versus-position tie-out gaps, and unexplained position begin-value carry-forward breaks
- current source-economics checks cover fee and external cash-flow classification loss, conflicting or malformed explicit fee or bod/eod source totals, fee and external normalization mismatches, duplicate raw source signals, positive fee sign anomalies, fee or external explicit source-total mismatches, external timing-bucket contradictions, invalid detailed cash-flow amounts, invalid timing labels, missing `cash_flow_type` labels, non-canonical `cash_flow_type` labels, governed alias labels, and unsupported labels whose TWR economics are not yet governed
- stateful portfolio and position valuation normalization use the same source cash-flow taxonomy as the inspector, so canonical `fee` cash flows, including operational expenses identified by `source_classification="EXPENSE"`, are normalized into `mgmt_fees`; stale `cash_flow_type="expense"` labels are treated as unsupported analytics input
- the full support-facing finding inventory lives in `docs/guides/twr_inspection_checks.md`
- endpoint certification evidence lives in `docs/technical/twr-inspection-endpoint-certification.md`

### `GET /performance/twr/results/{calculation_id}`

Purpose:

- retrieve the final durable TWR result after async offload

Sample response:

```json
{
  "calculation_id": "6af3a15f-8b95-4b4f-9c4c-6bb9f4d86a91",
  "status": "complete",
  "result_path": "/performance/twr/results/6af3a15f-8b95-4b4f-9c4c-6bb9f4d86a91"
}
```

### `POST /performance/mwr`

Purpose:

- calculate money-weighted return for the investor capital-timing lens
- supports `stateless` and `stateful` input modes
- stateful mode uses lotus-core query-control-plane portfolio timeseries and normalizes explicit
  external cash flows plus cross-observation capital carry-forward adjustments into the MWR cash-flow
  schedule
- operational fees remain performance drag and are not treated as investor deposits or withdrawals

Sample request:

```json
{
  "input_mode": "stateless",
  "portfolio_id": "PORT_001",
  "as_of": "2026-03-31",
  "mwr_method": "XIRR",
  "stateless_input": {
    "begin_mv": 1000000.0,
    "end_mv": 1054100.0,
    "cash_flows": [
      { "amount": 25000.0, "date": "2026-02-27" },
      { "amount": -5000.0, "date": "2026-03-31" }
    ]
  }
}
```

Sample response:

```json
{
  "calculation_id": "efec0a7e-4f8d-4f33-af89-57f1f71f4d4b",
  "portfolio_id": "PORT_001",
  "method": "XIRR",
  "money_weighted_return": 3.27,
  "mwr_annualized": 3.27,
  "status": "CALCULATED",
  "reason_codes": [],
  "warnings": [],
  "holding_period_return": 0.82,
  "is_annualized_primary": true,
  "is_approximation": false,
  "input_mode": "stateless",
  "convergence": {
    "converged": true,
    "algorithm": "log_rate_bracket_scan_bisection",
    "root_count_detected": 1,
    "day_count_basis": "ACT/365"
  },
  "cashflows_used": [
    { "amount": 25000.0, "date": "2026-02-27" },
    { "amount": -5000.0, "date": "2026-03-31" }
  ],
  "reporting_currency": "USD",
  "currency_evidence": null,
  "notes": []
}
```

Stateful MWR responses populate `currency_evidence` with `market_values_used[]`,
`cashflow_evidence[]`, and `currency_mode="SINGLE_REPORTING_CURRENCY"`. Single-currency stateful
inputs emit `conversion_evidence_status="not_required_single_currency_inputs"` when source and
reporting currencies match. Cross-currency stateful inputs keep
`conversion_evidence_status="upstream_preconverted_missing_per_input_fx_metadata"`, which means
lotus-performance preserves the reporting-currency context and source components received from
lotus-core but does not yet expose full per-input FX rate provenance. Stateless callers may supply
complete `source_preconverted_fx_evidence`; when present and valid, the response emits
`currency_mode="SOURCE_PRECONVERTED_WITH_FX_EVIDENCE"` and
`conversion_evidence_status="complete_source_preconverted_fx_metadata"` while the engine still
computes on the supplied reporting-currency schedule.

### `POST /performance/workspace-summary`

Purpose:

- return one coherent multi-horizon workspace response
- can include:
  - `portfolio_twr.net`
  - `portfolio_twr.gross`
  - benchmark summary
  - active summary
  - money-weighted return
- use dedicated contribution and attribution endpoints for drill-down rows and effects

Sample request:

```json
{
  "input_mode": "stateful",
  "portfolio_id": "WORKSPACE_SUMMARY_STATEFUL_01",
  "report_end_date": "2026-03-31",
  "periods": [
    { "period": "1M", "frequencies": ["daily", "monthly"] },
    { "period": "YTD", "frequencies": ["monthly"] },
    { "period": "SI", "frequencies": ["monthly", "yearly"] }
  ],
  "stateful_input": {},
  "include_benchmark": true,
  "benchmark": {
    "input_mode": "stateful",
    "stateful_input": {}
  },
  "report_ccy": "USD",
  "currency_mode": "BASE_ONLY"
}
```

Sample response:

```json
{
  "calculation_id": "0d000003-1111-4222-8333-abcdefabcdef",
  "portfolio_id": "WORKSPACE_SUMMARY_STATEFUL_01",
  "results_by_period": {
    "YTD": {
      "portfolio_twr": {
        "net": {
          "summary": {
            "economics": {
              "begin_market_value": 1000000.0,
              "end_market_value": 1054100.0,
              "beginning_cash_flow": 25000.0,
              "ending_cash_flow": -5000.0,
              "fees": -350.0,
              "net_cash_flow": 20000.0,
              "flow_adjusted_end_market_value": 1034100.0
            },
            "period_return": { "base": 3.41, "local": 3.18, "fx": 0.23 },
            "cumulative_return": { "base": 3.41, "local": 3.18, "fx": 0.23 },
            "annualized_return": { "base": 3.41, "local": 3.18, "fx": 0.23 }
          },
          "breakdowns": {
            "monthly": [
              {
                "period": "2026-03",
                "period_start": "2026-03-01",
                "period_end": "2026-03-31",
                "economics": {
                  "begin_market_value": 1039500.0,
                  "end_market_value": 1054100.0,
                  "beginning_cash_flow": 0.0,
                  "ending_cash_flow": -5000.0,
                  "fees": -350.0,
                  "net_cash_flow": -5000.0,
                  "flow_adjusted_end_market_value": 1059100.0
                },
                "period_return": { "base": 1.4, "local": 1.25, "fx": 0.15 },
                "cumulative_return": { "base": 1.4, "local": 1.25, "fx": 0.15 },
                "annualized_return": { "base": 1.4, "local": 1.25, "fx": 0.15 }
              }
            ]
          }
        }
      },
      "benchmark": {
        "benchmark_id": "BMK_GLOBAL_60_40",
        "summary": {
          "period_return": { "base": 2.98 },
          "cumulative_return": { "base": 2.98 },
          "annualized_return": { "base": 2.98 }
        }
      },
      "active": {
        "net": {
          "period_return": { "base": 0.43 },
          "cumulative_return": { "base": 0.43 },
          "annualized_return": { "base": 0.43 }
        }
      },
      "money_weighted_return": {
        "method": "XIRR",
        "period_return": 3.27,
        "cumulative_return": 3.27,
        "annualized_return": 3.27,
        "start_date": "2026-01-02",
        "end_date": "2026-03-31"
      }
    }
  },
  "audit": {
    "counts": {
      "portfolio_chunk_count": 3,
      "benchmark_chunk_count": 2
    }
  }
}
```

Async result route:

- `GET /performance/workspace-summary/results/{calculation_id}`

Canonical example files:

- `docs/examples/workspace_summary_request.json`
- `docs/examples/workspace_summary_stateful_detail_request.json`
- `docs/examples/workspace_summary_accepted_response.json`
- `docs/technical/workspace-summary-endpoint-certification.md`

### `GET /performance/workspace-summary/results/{calculation_id}`

Purpose:

- retrieve the final durable workspace-summary result

Sample response:

```json
{
  "calculation_id": "0d000003-1111-4222-8333-abcdefabcdef",
  "poll_path": "/performance/executions/0d000003-1111-4222-8333-abcdefabcdef",
  "result_path": "/performance/workspace-summary/results/0d000003-1111-4222-8333-abcdefabcdef"
}
```

### `POST /performance/benchmark`

Purpose:

- calculate benchmark performance
- supports `stateless` and `stateful`
- supports `calculated` and `vendor_series` return sources

Sample request:

```json
{
  "input_mode": "stateless",
  "benchmark_id": "BMK_GLOBAL_60_40",
  "benchmark_start_date": "2026-01-02",
  "report_end_date": "2026-03-31",
  "analyses": [
    { "period": "YTD", "frequencies": ["daily", "monthly"] }
  ],
  "return_source": "calculated",
  "stateless_input": {
    "benchmark_currency": "USD",
    "component_price_points": [
      { "component_id": "EQ", "perf_date": "2026-01-02", "price": 100.0, "weight_bop": 0.6 },
      { "component_id": "FI", "perf_date": "2026-01-02", "price": 100.0, "weight_bop": 0.4 }
    ]
  }
}
```

Sample response:

```json
{
  "calculation_id": "31be58a0-0748-48f2-9657-e8b11d62fe6f",
  "benchmark_id": "BMK_GLOBAL_60_40",
  "input_mode": "stateless",
  "return_source": "calculated",
  "results_by_period": {
    "YTD": {
      "summary": {
        "period_return": { "base": 2.98 },
        "cumulative_return": { "base": 2.98 },
        "annualized_return": { "base": 2.98 }
      }
    }
  }
}
```

Async result route:

- `GET /performance/benchmark/results/{calculation_id}`

Example request files:

- `docs/examples/benchmark_request.json`
- `docs/examples/benchmark_request_price_points.json`
- `docs/examples/benchmark_vendor_series_request.json`

### `GET /performance/benchmark/results/{calculation_id}`

Sample response:

```json
{
  "calculation_id": "31be58a0-0748-48f2-9657-e8b11d62fe6f",
  "status": "complete",
  "result_path": "/performance/benchmark/results/31be58a0-0748-48f2-9657-e8b11d62fe6f"
}
```

### `POST /performance/contribution`

Purpose:

- calculate contribution by hierarchy and by position
- supports `stateless` and `stateful`

Sample request:

```json
{
  "input_mode": "stateless",
  "portfolio_id": "PORT_001",
  "report_start_date": "2026-01-01",
  "report_end_date": "2026-03-31",
  "analyses": [
    { "period": "EXPLICIT", "frequencies": ["daily"] }
  ],
  "hierarchy": ["sector"],
  "stateless_input": {
    "portfolio_data": {
      "metric_basis": "NET",
      "valuation_points": [
        { "perf_date": "2026-01-02", "begin_mv": 1000.0, "end_mv": 1010.0 }
      ]
    },
    "positions_data": [
      {
        "position_id": "AAPL_US",
        "meta": { "sector": "technology" },
        "valuation_points": [
          { "perf_date": "2026-01-02", "begin_mv": 600.0, "end_mv": 612.0 }
        ]
      }
    ]
  }
}
```

Sample response:

```json
{
  "calculation_id": "6446f646-a695-4e34-879b-f310e68a070d",
  "portfolio_id": "PORT_001",
  "input_mode": "stateless",
  "results_by_period": {
    "EXPLICIT": {
      "summary": {
        "portfolio_return": 2.5
      },
      "levels": [
        {
          "name": "sector",
          "rows": [
            {
              "label": "technology",
              "contribution": 2.5,
              "weight_avg": 60.5
            }
          ]
        }
      ],
      "position_contributions": [
        {
          "position_id": "AAPL_US",
          "total_contribution": 2.5,
          "average_weight": 60.5
        }
      ]
    }
  }
}
```

Async result route:

- `GET /performance/contribution/results/{calculation_id}`

Example request files:

- `docs/examples/contribution_request.json`
- `docs/examples/contribution_request_multiccy.json`

### `GET /performance/contribution/results/{calculation_id}`

Sample response:

```json
{
  "calculation_id": "6446f646-a695-4e34-879b-f310e68a070d",
  "status": "complete",
  "result_path": "/performance/contribution/results/6446f646-a695-4e34-879b-f310e68a070d"
}
```

### `POST /performance/attribution`

Purpose:

- calculate attribution versus benchmark
- supports `stateless` and `stateful`

Sample request:

```json
{
  "input_mode": "stateless",
  "portfolio_id": "PORT_001",
  "report_start_date": "2026-01-01",
  "report_end_date": "2026-03-31",
  "analyses": [
    { "period": "EXPLICIT", "frequencies": ["daily"] }
  ],
  "mode": "by_instrument",
  "group_by": ["sector"],
  "stateless_input": {
    "portfolio_data": {
      "metric_basis": "NET",
      "valuation_points": [
        { "perf_date": "2026-01-02", "begin_mv": 1000.0, "end_mv": 1010.0 }
      ]
    },
    "instruments_data": [],
    "benchmark_groups_data": [
      {
        "key": { "sector": "technology" },
        "observations": [
          { "date": "2026-01-02", "weight_bop": 1.0, "return_base": 0.01 }
        ]
      }
    ]
  }
}
```

Sample response:

```json
{
  "calculation_id": "209da27d-f3f4-4e64-97c5-a2eb1d4fe4f3",
  "portfolio_id": "PORT_001",
  "input_mode": "stateless",
  "benchmark_context": {
    "benchmark_id": "BMK_GLOBAL_60_40",
    "return_source": "calculated"
  },
  "results_by_period": {
    "EXPLICIT": {
      "levels": [
        {
          "dimension": "sector",
          "groups": [
            {
              "key": { "sector": "technology" },
              "portfolio_weight_avg": 60.5,
              "benchmark_weight_avg": 58.0,
              "portfolio_return": 3.2,
              "benchmark_return": 2.8,
              "allocation": 0.1,
              "selection": 0.2,
              "interaction": 0.0,
              "total_effect": 0.3
            }
          ],
          "totals": {
            "allocation": 0.1,
            "selection": 0.2,
            "interaction": 0.0,
            "total_effect": 0.3
          },
          "allocation_total_pct": 0.1,
          "selection_total_pct": 0.2,
          "interaction_total_pct": 0.0,
          "total_effect_pct": 0.3
        }
      ],
      "reconciliation": {
        "total_active_return": 0.3,
        "sum_of_effects": 0.3,
        "residual": 0.0
      }
    }
  }
}
```

Async result route:

- `GET /performance/attribution/results/{calculation_id}`

Example request files:

- `docs/examples/attribution_request.json`
- `docs/examples/attribution_request_multiccy.json`

### `GET /performance/attribution/results/{calculation_id}`

Sample response:

```json
{
  "calculation_id": "209da27d-f3f4-4e64-97c5-a2eb1d4fe4f3",
  "status": "complete",
  "result_path": "/performance/attribution/results/209da27d-f3f4-4e64-97c5-a2eb1d4fe4f3"
}
```

### `GET /performance/executions/{calculation_id}`

Purpose:

- poll the durable execution lifecycle for any async-capable workflow
- use the endpoint-specific `result_path` after `status` becomes `complete`
- inspect stage progress, upstream snapshots, retry state, and terminal failure metadata

Sample response:

```json
{
  "calculation_id": "0d000003-1111-4222-8333-abcdefabcdef",
  "analytics_type": "WORKSPACE_SUMMARY",
  "portfolio_id": "PB_SG_GLOBAL_BAL_001",
  "execution_mode": "async",
  "status": "complete",
  "requested_window": {
    "start_date": "2026-01-01",
    "end_date": "2026-04-10",
    "input_count": 100
  },
  "input_fingerprint": "sha256:input-fingerprint",
  "calculation_hash": "sha256:calculation-output",
  "error_message": null,
  "created_at_utc": "2026-04-10T12:00:00Z",
  "started_at_utc": "2026-04-10T12:00:01Z",
  "completed_at_utc": "2026-04-10T12:00:08Z",
  "stages": [
    {
      "stage_name": "execution",
      "status": "complete",
      "started_at_utc": "2026-04-10T12:00:01Z",
      "completed_at_utc": "2026-04-10T12:00:08Z",
      "details": { "input_count": 100 },
      "error_message": null
    }
  ],
  "upstream_snapshots": [
    {
      "snapshot_id": "portfolio_timeseries:PB_SG_GLOBAL_BAL_001:2026-04-10",
      "upstream_endpoint": "portfolio_timeseries",
      "source_identifier": "PB_SG_GLOBAL_BAL_001",
      "as_of_date": "2026-04-10",
      "request_fingerprint": "sha256:request-fingerprint",
      "response_fingerprint": "sha256:response-fingerprint",
      "retrieval_status": "200",
      "paging_metadata": { "chunk_count": 1, "page_count": 1 },
      "created_at_utc": "2026-04-10T12:00:00Z"
    }
  ],
  "compute_job": {
    "job_status": "complete",
    "attempt_count": 1,
    "max_attempts": 3,
    "worker_id": "performance-compute-executor-1",
    "error_message": null,
    "error_type": null,
    "leased_at_utc": "2026-04-10T12:00:03Z",
    "lease_expires_at_utc": "2026-04-10T12:05:03Z",
    "last_error_at_utc": null,
    "created_at_utc": "2026-04-10T12:00:00Z",
    "started_at_utc": "2026-04-10T12:00:03Z",
    "completed_at_utc": "2026-04-10T12:00:08Z"
  },
  "async_result": {
    "result_status": "complete",
    "error_message": null,
    "error_type": null,
    "created_at_utc": "2026-04-10T12:00:06Z",
    "updated_at_utc": "2026-04-10T12:00:08Z"
  }
}
```

Certification evidence:

- `docs/technical/execution-polling-endpoint-certification.md`

### `GET /performance/lineage/{calculation_id}`

Purpose:

- inspect lineage status and artifact inventory for a calculation

Sample response:

```json
{
  "calculation_id": "0d000003-1111-4222-8333-abcdefabcdef",
  "calculation_type": "WORKSPACE_SUMMARY",
  "timestamp_utc": "2026-04-10T12:00:00Z",
  "status": "complete",
  "artifacts": {
    "workspace_summary_portfolio_daily_results_net.csv": {
      "url": "http://performance.dev.lotus/performance/lineage/0d000003-1111-4222-8333-abcdefabcdef/artifacts/workspace_summary_portfolio_daily_results_net.csv"
    }
  },
  "error_message": null
}
```

Certification evidence:

- `docs/technical/lineage-endpoint-certification.md`

### `GET /performance/lineage/{calculation_id}/artifacts/{artifact_name}`

Purpose:

- download one declared lineage artifact

Sample request:

```text
GET /performance/lineage/0d000003-1111-4222-8333-abcdefabcdef/artifacts/workspace_summary_portfolio_daily_results_net.csv
```

Sample response:

```text
HTTP/1.1 200 OK
Content-Type: text/csv
Content-Disposition: attachment; filename="workspace_summary_portfolio_daily_results_net.csv"
```

### `GET /integration/capabilities`

Purpose:

- advertise supported surfaces, async patterns, stateful fences, and option maps

Sample response:

```json
{
  "contract_version": "v1",
  "source_service": "lotus-performance",
  "supported_input_modes": ["stateful", "stateless"],
  "analytics_surfaces": [
    {
      "key": "workspace_summary",
      "path": "/performance/workspace-summary",
      "supports_async": true,
      "poll_path_template": "/performance/executions/{calculation_id}",
      "result_path_template": "/performance/workspace-summary/results/{calculation_id}",
      "stateful_restrictions": [],
      "options": [
        {
          "key": "benchmark_mode",
          "values": ["user_input_stateless", "linked_stateful"]
        }
      ]
    }
  ]
}
```

Canonical example file:

- `docs/examples/integration_capabilities_response.json`
- certification evidence: `docs/technical/integration-capabilities-endpoint-certification.md`

### `POST /integration/returns/series`

Purpose:

- return canonical portfolio, benchmark, risk-free, and active return series
- use this endpoint when a downstream analytics service needs aligned return observations; do not
  reconstruct this feed from TWR, MWR, or benchmark endpoint responses
- all return values are decimal ratios, not percentages
- `calendar_policy=BUSINESS` filters daily output to weekdays before coverage diagnostics

Sample request:

```json
{
  "input_mode": "stateless",
  "portfolio_id": "PORT_001",
  "as_of_date": "2026-03-31",
  "window": {
    "mode": "EXPLICIT",
    "from_date": "2026-01-01",
    "to_date": "2026-03-31"
  },
  "frequency": "DAILY",
  "metric_basis": "NET",
  "series_selection": {
    "include_portfolio": true,
    "include_benchmark": true,
    "include_risk_free": false
  },
  "data_policy": {
    "missing_data_policy": "ALLOW_PARTIAL",
    "fill_method": "NONE",
    "calendar_policy": "BUSINESS"
  },
  "stateless_input": {
    "portfolio_returns": [
      { "date": "2026-03-30", "return_value": 0.01 },
      { "date": "2026-03-31", "return_value": 0.02 }
    ],
    "benchmark_returns": [
      { "date": "2026-03-30", "return_value": 0.008 },
      { "date": "2026-03-31", "return_value": 0.015 }
    ]
  }
}
```

Sample response:

```json
{
  "calculation_id": "f25cbd85-b7e5-4aaf-b994-ff59cb143ef5",
  "portfolio_id": "PORT_001",
  "series": {
    "portfolio_returns": [
      { "date": "2026-03-30", "return_value": 0.01 },
      { "date": "2026-03-31", "return_value": 0.02 }
    ],
    "benchmark_returns": [
      { "date": "2026-03-30", "return_value": 0.008 },
      { "date": "2026-03-31", "return_value": 0.015 }
    ],
    "active_returns": [
      { "date": "2026-03-30", "return_value": 0.002 },
      { "date": "2026-03-31", "return_value": 0.005 }
    ],
    "cumulative_active_returns": [
      { "date": "2026-03-30", "return_value": 0.002 },
      { "date": "2026-03-31", "return_value": 0.00603 }
    ]
  }
}
```

Async result route:

- `GET /integration/returns/series/results/{calculation_id}`

### `GET /integration/returns/series/results/{calculation_id}`

Sample response:

```json
{
  "calculation_id": "f25cbd85-b7e5-4aaf-b994-ff59cb143ef5",
  "status": "complete",
  "result_path": "/integration/returns/series/results/f25cbd85-b7e5-4aaf-b994-ff59cb143ef5"
}
```

### `POST /integration/benchmarks/exposure-context`

Purpose:

- return benchmark exposure history aligned with lotus-performance benchmark return context
- serve `lotus-risk` stateful active-risk attribution without making risk orchestrate benchmark
  assignment, market-series, and index-catalog contracts directly
- keep lotus-core as the benchmark composition and classification system of record

Contract notes:

- v1 supports `frequency=DAILY` only
- supported grouping dimensions are `POSITION`, `SECTOR`, `ASSET_CLASS`, and `ISSUER`
- `ISSUER` grouping uses `classification_labels.issuer_id` and `issuer_name` from lotus-core index catalog records
- row weights are decimal fractions, not percentages
- pagination uses `page.page_size` and `page.next_page_token`
- certification evidence lives in
  `docs/technical/benchmark-exposure-context-endpoint-certification.md`

Sample request:

```json
{
  "portfolio_id": "PB_SG_GLOBAL_BAL_001",
  "benchmark_id": "BMK_PB_GLOBAL_BALANCED_60_40",
  "as_of_date": "2026-04-10",
  "window": {
    "start_date": "2026-01-01",
    "end_date": "2026-04-10"
  },
  "frequency": "DAILY",
  "reporting_currency": "USD",
  "grouping_dimensions": ["POSITION", "SECTOR", "ASSET_CLASS"],
  "page": {
    "page_size": 1000,
    "page_token": null
  }
}
```

Sample response excerpt:

```json
{
  "source_service": "lotus-performance",
  "contract_version": "v1",
  "portfolio_id": "PB_SG_GLOBAL_BAL_001",
  "benchmark_id": "BMK_PB_GLOBAL_BALANCED_60_40",
  "frequency": "DAILY",
  "rows": [
    {
      "valuation_date": "2026-04-10",
      "component_id": "IDX_GLOBAL_EQUITY",
      "grouping_dimension": "POSITION",
      "group_key": "IDX_GLOBAL_EQUITY",
      "group_label": "IDX_GLOBAL_EQUITY",
      "weight": "0.600000"
    }
  ],
  "page": {
    "next_page_token": null
  },
  "metadata": {
    "source_system": "lotus-core",
    "served_by": "lotus-performance",
    "contract_version": "v1"
  }
}
```

### `GET /integration/runtime-status`

Purpose:

- provide a bounded runtime health snapshot for compute, lineage, recovery, and retention lanes

Sample response:

```json
{
  "contract_version": "v1",
  "source_service": "lotus-performance",
  "generated_at": "2026-04-10T12:00:00Z",
  "runtime_status": "ready",
  "runtime_degradation_reasons": [],
  "runtime_degradation_details": [],
  "draining": false,
  "durable_metadata_store": {
    "status": "ready",
    "reason": null,
    "remediation_hint": null
  },
  "compute_queue": {
    "status": "available",
    "pending_jobs": 0,
    "running_jobs": 0,
    "retry_backlog_jobs": 0,
    "terminal_failure_jobs": 0,
    "inspection_anchors": {
      "oldest_pending_calculation_id": null,
      "latest_terminal_failure_calculation_id": null
    },
    "recent_recoveries": []
  },
  "lineage_queue": {
    "status": "available",
    "pending_payloads": 0,
    "retry_backlog_payloads": 0,
    "terminal_failure_payloads": 0,
    "storage_free_ratio": 0.72,
    "inspection_anchors": {
      "oldest_pending_calculation_id": null,
      "latest_terminal_failure_calculation_id": null
    },
    "recent_recoveries": []
  },
  "recovery_drill": {
    "status": "available",
    "latest_status": "passed",
    "active_run_count": 0
  },
  "runtime_retention": {
    "status": "available",
    "latest_status": "applied",
    "active_run_count": 0,
    "current_prunable_execution_count": 0,
    "current_prunable_lineage_artifact_count": 0
  }
}
```

Certification evidence:

- `docs/technical/runtime-status-endpoint-certification.md`

### `GET /integration/runtime-work-items`

Purpose:

- inspect the concrete compute and lineage work items behind runtime queue pressure

Sample request:

```text
GET /integration/runtime-work-items?queue=both&status=reclaimable&limit=25&min_age_seconds=60
```

Sample response:

```json
{
  "contract_version": "v1",
  "source_service": "lotus-performance",
  "generated_at": "2026-03-29T02:05:00Z",
  "queue_filter": "both",
  "status_filter": "reclaimable",
  "limit": 25,
  "offset": 0,
  "min_age_seconds": 60.0,
  "durable_metadata_store": {
    "status": "ready"
  },
  "compute_queue": {
    "status": "available",
    "total_count": 1,
    "returned_count": 1
  },
  "lineage_queue": {
    "status": "available",
    "total_count": 1,
    "returned_count": 1
  },
  "compute_items": [
    {
      "calculation_id": "0d000003-1111-4222-8333-abcdefabcdef",
      "execution_path": "/performance/executions/0d000003-1111-4222-8333-abcdefabcdef",
      "lineage_path": "/performance/lineage/0d000003-1111-4222-8333-abcdefabcdef",
      "result_path": "/performance/workspace-summary/results/0d000003-1111-4222-8333-abcdefabcdef",
      "analytics_type": "WORKSPACE_SUMMARY",
      "status": "running",
      "active_since_utc": "2026-03-29T02:00:00Z",
      "age_seconds": 300.0,
      "attempt_count": 1,
      "max_attempts": 3
    }
  ],
  "lineage_items": [
    {
      "calculation_id": "0d000004-1111-4222-8333-abcdefabcdef",
      "execution_path": "/performance/executions/0d000004-1111-4222-8333-abcdefabcdef",
      "lineage_path": "/performance/lineage/0d000004-1111-4222-8333-abcdefabcdef",
      "result_path": "/performance/twr/results/0d000004-1111-4222-8333-abcdefabcdef",
      "calculation_type": "TWR",
      "status": "pending",
      "active_since_utc": "2026-03-29T02:01:00Z",
      "age_seconds": 240.0,
      "attempt_count": 0
    }
  ]
}
```

Certification evidence:

- `docs/technical/runtime-work-items-endpoint-certification.md`

### `GET /integration/runtime-recoveries`

Purpose:

- inspect durable compute and lineage recovery events after runtime recovery activity

Sample request:

```text
GET /integration/runtime-recoveries?queue=both&limit=10&recovered_after=2026-03-29T02:00:00Z
```

Sample response:

```json
{
  "contract_version": "v1",
  "source_service": "lotus-performance",
  "generated_at": "2026-03-29T02:05:30Z",
  "queue_filter": "both",
  "limit": 10,
  "offset": 0,
  "recovered_after": "2026-03-29T02:00:00Z",
  "durable_metadata_store": {
    "status": "ready"
  },
  "compute_queue": {
    "status": "available",
    "total_count": 1,
    "returned_count": 1,
    "next_cursor_recovered_before": "2026-03-29T02:05:00Z",
    "next_cursor_calculation_id_before": "0d000003-1111-4222-8333-abcdefabcdef"
  },
  "lineage_queue": {
    "status": "available",
    "total_count": 1,
    "returned_count": 1
  },
  "compute_recoveries": [
    {
      "calculation_id": "0d000003-1111-4222-8333-abcdefabcdef",
      "execution_path": "/performance/executions/0d000003-1111-4222-8333-abcdefabcdef",
      "lineage_path": "/performance/lineage/0d000003-1111-4222-8333-abcdefabcdef",
      "result_path": "/performance/workspace-summary/results/0d000003-1111-4222-8333-abcdefabcdef",
      "analytics_type": "WORKSPACE_SUMMARY",
      "recovery_kind": "lease_reclaimed",
      "recovered_at_utc": "2026-03-29T02:05:00Z",
      "attempt_count": 1
    }
  ],
  "lineage_recoveries": [
    {
      "calculation_id": "0d000004-1111-4222-8333-abcdefabcdef",
      "execution_path": "/performance/executions/0d000004-1111-4222-8333-abcdefabcdef",
      "lineage_path": "/performance/lineage/0d000004-1111-4222-8333-abcdefabcdef",
      "result_path": "/performance/twr/results/0d000004-1111-4222-8333-abcdefabcdef",
      "calculation_type": "TWR",
      "recovery_kind": "retryable_materialization_failure",
      "recovered_at_utc": "2026-03-29T02:04:00Z",
      "attempt_count": 1
    }
  ]
}
```

Certification evidence:

- `docs/technical/runtime-recoveries-endpoint-certification.md`

### `GET /integration/recovery-drills`

Purpose:

- inspect retained durable recovery-drill evidence, filters, paging, and assurance status

Sample response:

```json
{
  "contract_version": "v1",
  "source_service": "lotus-performance",
  "status": "available",
  "artifact_directory": "artifacts/recovery-drills",
  "latest_file_name": "recovery-drill-20260329T013000Z.json",
  "retained_file_names": [
    "recovery-drill-20260329T013000Z.json"
  ],
  "retention_limit": 30,
  "retention_max_age_days": 90,
  "total_entries": 1,
  "matched_entries": 1,
  "returned_entries": 1,
  "applied_filters": {
    "status": "passed"
  },
  "entries": [
    {
      "evidence_file_name": "recovery-drill-20260329T013000Z.json",
      "generated_at_utc": "2026-03-29T01:30:00Z",
      "status": "passed",
      "operator_id": "ops-user",
      "tenant_id": "tenant-private-bank",
      "correlation_id": "runtime-alert-123",
      "backup_identifier": "backup-2026-03-29"
    }
  ]
}
```

Certification evidence:

- `docs/technical/recovery-drills-endpoint-certification.md`

### `POST /integration/recovery-drills/run`

Purpose:

- execute a governed durable recovery drill and retain compute, lineage, schema, and artifact proof

Sample request:

```json
{
  "backup_identifier": "backup-2026-03-29"
}
```

Sample response:

```json
{
  "contract_version": "v1",
  "source_service": "lotus-performance",
  "drill_name": "durable_metadata_recovery",
  "generated_at_utc": "2026-03-29T01:30:00Z",
  "evidence_file_name": "recovery-drill-20260329T013000Z.json",
  "operator_id": "ops-user",
  "tenant_id": "tenant-private-bank",
  "correlation_id": "runtime-alert-123",
  "backup_identifier": "backup-2026-03-29",
  "status": "passed",
  "database_path": "artifacts/recovery-drills/recovery-drill.sqlite",
  "restored_schema_mode": "upgraded",
  "owned_tables_present": [
    "compute_jobs",
    "lineage_payloads"
  ],
  "compute_job_processed_count": 1,
  "compute_async_result_status": "completed",
  "compute_execution_status": "completed",
  "processed_payload_count": 1,
  "materialized_artifact_path": "artifacts/recovery-drills/lineage.json",
  "materialized_artifact_exists": true
}
```

Certification evidence:

- `docs/technical/recovery-drills-endpoint-certification.md`

### `GET /integration/runtime-retention-cleanups`

Purpose:

- inspect retained runtime-retention cleanup evidence, filters, paging, and prunable counts

Sample response:

```json
{
  "contract_version": "v1",
  "source_service": "lotus-performance",
  "status": "available",
  "artifact_directory": "artifacts/runtime-retention",
  "latest_file_name": "runtime-retention-20260329T014500Z.json",
  "retained_file_names": [
    "runtime-retention-20260329T014500Z.json"
  ],
  "retention_limit": 30,
  "retention_max_age_days": 90,
  "total_entries": 1,
  "matched_entries": 1,
  "returned_entries": 1,
  "applied_filters": {
    "cleanup_mode": "dry_run"
  },
  "entries": [
    {
      "evidence_file_name": "runtime-retention-20260329T014500Z.json",
      "generated_at_utc": "2026-03-29T01:45:00Z",
      "operator_id": "ops-user",
      "tenant_id": "tenant-private-bank",
      "correlation_id": "runtime-alert-456",
      "cleanup_mode": "dry_run",
      "trigger_mode": "manual",
      "job_id": "ops-ticket-123",
      "status": "ok",
      "retention_days": 30,
      "prunable_execution_count": 3,
      "prunable_compute_job_count": 2,
      "prunable_async_result_count": 2,
      "prunable_lineage_record_count": 1,
      "prunable_lineage_artifact_count": 1
    }
  ]
}
```

Certification evidence:

- `docs/technical/runtime-retention-endpoint-certification.md`

### `POST /integration/runtime-retention-cleanups/run`

Purpose:

- execute a governed retention cleanup dry run or apply action

Sample request:

```json
{
  "apply": false,
  "retention_days": 30,
  "job_id": "ops-ticket-123"
}
```

Sample response:

```json
{
  "contract_version": "v1",
  "source_service": "lotus-performance",
  "cleanup_name": "runtime_retention_cleanup",
  "generated_at_utc": "2026-03-29T01:45:00Z",
  "evidence_file_name": "runtime-retention-20260329T014500Z.json",
  "operator_id": "ops-user",
  "tenant_id": "tenant-private-bank",
  "correlation_id": "runtime-alert-456",
  "trigger_mode": "manual",
  "job_id": "ops-ticket-123",
  "cleanup_mode": "dry_run",
  "status": "ok",
  "retention_days": 30,
  "cutoff_utc": "2026-02-28T01:45:00Z",
  "prunable_execution_count": 3,
  "prunable_compute_job_count": 2,
  "prunable_async_result_count": 2,
  "prunable_lineage_record_count": 1,
  "prunable_lineage_artifact_count": 1
}
```

Certification evidence:

- `docs/technical/runtime-retention-endpoint-certification.md`

### `GET /`

Sample response:

```json
{
  "message": "Welcome to the Portfolio Performance Analytics API. Access /docs for API documentation."
}
```

Certification evidence:

- `docs/technical/platform-surfaces-endpoint-certification.md`

### `GET /health`

Sample response:

```json
{
  "status": "ok"
}
```

### `GET /health/live`

Sample response:

```json
{
  "status": "alive"
}
```

### `GET /health/ready`

Sample response:

```json
{
  "status": "ready"
}
```

Possible failure shape:

```json
{
  "status": "unavailable",
  "reason": "durable_metadata_readiness_timeout",
  "remediation_hint": "The durable metadata readiness probe exceeded its configured time budget; inspect database latency, connectivity, and catalog responsiveness before accepting traffic."
}
```

Readiness semantics:

- durable metadata and lineage-storage probes run outside the async request loop
- `DURABLE_READINESS_TIMEOUT_SECONDS` bounds each durable dependency probe
- durable metadata catalog discovery failures return `durable_metadata_schema_discovery_failed`
- successful catalog discovery with missing required tables returns `durable_metadata_schema_incomplete`
- timeout reason codes are `durable_metadata_readiness_timeout` and `lineage_storage_readiness_timeout`

### `GET /metrics`

Purpose:

- expose Prometheus metrics

Sample response excerpt:

```text
# HELP lotus_performance_compute_queue_degradation_breach Queue degradation breach gauge
# TYPE lotus_performance_compute_queue_degradation_breach gauge
lotus_performance_compute_queue_degradation_breach{reason="pending_age_exceeded"} 0
```

Certification evidence:

- `docs/technical/platform-surfaces-endpoint-certification.md`

## Execution Pattern

Async-capable endpoints use one shared pattern:

1. submit the request
2. receive a final result or `202 Accepted`
3. poll `GET /performance/executions/{calculation_id}`
4. retrieve the endpoint-specific result path

The OpenAPI contract declares the `202 Accepted` accepted-envelope schema for every async-capable
submission route and every endpoint-specific result route. Endpoint-specific result routes also
publish governed `404` unknown-calculation and `409` failed-calculation error responses so SDK,
Gateway, Workbench, and API catalog consumers can model all runtime branches.
Endpoint-specific result routes are type-scoped: a calculation id created for another
`analytics_type` returns that endpoint's governed `404` response and logs reason
`async_result_analytics_type_mismatch` with the expected and actual analytics type, without logging
request or response payload contents.

Current endpoint-specific async result routes:

- `/performance/twr/results/{calculation_id}`
- `/performance/benchmark/results/{calculation_id}`
- `/performance/workspace-summary/results/{calculation_id}`
- `/performance/contribution/results/{calculation_id}`
- `/performance/attribution/results/{calculation_id}`
- `/integration/returns/series/results/{calculation_id}`

Completed async results are validated against the endpoint response model before being returned.
If durable state contains a completed result whose JSON object no longer satisfies that response
contract, the route returns `409 Conflict` with detail
`Async result payload failed response contract validation.`. The warning diagnostic records the
`calculation_id`, result source (`async_result_store` or `compute_job_store`), response model, reason
`async_result_response_schema_invalid`, and validation-error count without logging payload contents.

## Configuration Reference

All service configuration comes from `app.core.config.Settings`.

### Service identity and logging

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_NAME` | `Portfolio Performance Analytics API` | service display name |
| `APP_VERSION` | `0.1.0` | service version string |
| `APP_DESCRIPTION` | `API for calculating portfolio performance metrics.` | service description |
| `LOG_LEVEL` | `INFO` | application log level |
| `decimal_precision` | `28` | global Decimal precision applied at settings initialization |

### Enterprise request controls

| Variable | Default | Purpose |
| --- | --- | --- |
| `ENTERPRISE_MAX_WRITE_PAYLOAD_BYTES` | `10485760` | maximum accepted write request body size in bytes; trusted `Content-Length` values are rejected before downstream processing, and missing or malformed length headers are enforced by counting streamed ASGI body bytes |

Operational boundary:

- set ingress or API gateway request-size limits at or below `ENTERPRISE_MAX_WRITE_PAYLOAD_BYTES` for earlier rejection
- keep the application guard enabled as the final service-owned control for direct, malformed, or proxy-bypassing write requests

### Lineage storage and worker

| Variable | Default | Purpose |
| --- | --- | --- |
| `LINEAGE_STORAGE_PATH` | `lineage_data` | artifact storage root |
| `LINEAGE_STORAGE_HEALTHCHECK_WRITE_PROBE_ENABLED` | `true` | enable readiness write/delete probe |
| `DURABLE_READINESS_TIMEOUT_SECONDS` | `2.0` | per-probe time budget for durable metadata and lineage-storage readiness checks |
| `LINEAGE_METADATA_DATABASE_URL` | `sqlite:///./lineage_metadata.db` | durable lineage metadata database |
| `LINEAGE_WORKER_POLL_SECONDS` | `1.0` | lineage worker poll interval |
| `LINEAGE_WORKER_BATCH_SIZE` | `20` | lineage worker batch size |
| `LINEAGE_WORKER_MAX_ATTEMPTS` | `3` | lineage worker retry budget |
| `LINEAGE_WORKER_LEASE_SECONDS` | `60` | lineage worker lease time |
| `LINEAGE_WORKER_ID` | `lineage-worker-1` | lineage worker identity |

### Lotus-core integration and stateful retrieval

| Variable | Default | Purpose |
| --- | --- | --- |
| `CORE_CONTROL_PLANE_BASE_URL` | `http://core-control.dev.lotus` | lotus-core query-control-plane base URL for stateful analytics-input contracts |
| `CORE_QUERY_BASE_URL` | unset | deprecated compatibility fallback when `CORE_CONTROL_PLANE_BASE_URL` is unset |
| `CORE_TIMEOUT_SECONDS` | `10.0` | upstream request timeout |
| `CORE_MAX_RETRIES` | `2` | upstream retry count |
| `CORE_RETRY_BACKOFF_SECONDS` | `0.2` | upstream retry backoff |
| `STATEFUL_INPUT_PORTFOLIO_CHUNK_DAYS` | `90` | portfolio retrieval chunk size |
| `STATEFUL_INPUT_REFERENCE_CHUNK_DAYS` | `365` | reference retrieval chunk size |
| `STATEFUL_INPUT_MAX_CONCURRENT_CHUNKS` | `4` | concurrent chunk retrieval bound |
| `STATEFUL_INPUT_MAX_PAGES_PER_CHUNK` | `25` | maximum lotus-core portfolio/position pages accepted per stateful retrieval chunk before returning `stateful_upstream_page_limit_exceeded` |

Stateful portfolio and position retrieval also rejects repeated lotus-core `next_page_token` values
with `stateful_upstream_repeated_page_token`. Both pagination failures return controlled upstream
failure payloads with bounded chunk and page-count metadata, preserving normal multi-page traversal
when tokens advance and terminate correctly.

### Compute executor

| Variable | Default | Purpose |
| --- | --- | --- |
| `COMPUTE_EXECUTOR_POLL_SECONDS` | `1.0` | executor poll interval |
| `COMPUTE_EXECUTOR_BATCH_SIZE` | `10` | executor batch size |
| `COMPUTE_EXECUTOR_MAX_ATTEMPTS` | `3` | executor retry budget |
| `COMPUTE_EXECUTOR_LEASE_SECONDS` | `60` | executor lease time |
| `COMPUTE_EXECUTOR_WORKER_ID` | `compute-executor-1` | executor identity |

### Runtime-status storage thresholds

| Variable | Default | Purpose |
| --- | --- | --- |
| `RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES` | `0` | free-byte storage alert threshold |
| `RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO` | `0.0` | free-ratio storage alert threshold |

### Runtime-status compute thresholds

| Variable | Default | Purpose |
| --- | --- | --- |
| `RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS` | `0.0` | pending compute age threshold |
| `RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS` | `0.0` | leased compute age threshold |
| `RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS` | `0.0` | running compute age threshold |
| `RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT` | `0` | retry backlog threshold |
| `RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT` | `0` | lease expiry threshold |
| `RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT` | `0` | terminal failure threshold |

### Runtime-status lineage thresholds

| Variable | Default | Purpose |
| --- | --- | --- |
| `RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS` | `0.0` | pending lineage age threshold |
| `RUNTIME_STATUS_LINEAGE_LEASED_AGE_DEGRADE_SECONDS` | `0.0` | leased lineage age threshold |
| `RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT` | `0` | lineage retry backlog threshold |
| `RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT` | `0` | lineage terminal failure threshold |

### Recovery-drill and retention runtime thresholds

| Variable | Default | Purpose |
| --- | --- | --- |
| `RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS` | `0.0` | max acceptable age for latest drill |
| `RUNTIME_STATUS_RECOVERY_DRILL_ACTIVE_RUN_AGE_DEGRADE_SECONDS` | `0.0` | active drill age threshold |
| `RUNTIME_STATUS_RECOVERY_DRILL_RECLAIM_DEGRADE_COUNT` | `0` | reclaimed drill count threshold |
| `RUNTIME_STATUS_RUNTIME_RETENTION_MAX_AGE_SECONDS` | `0.0` | max acceptable age for latest retention run |
| `RUNTIME_STATUS_RUNTIME_RETENTION_ACTIVE_RUN_AGE_DEGRADE_SECONDS` | `0.0` | active retention age threshold |
| `RUNTIME_STATUS_RUNTIME_RETENTION_RECLAIM_DEGRADE_COUNT` | `0` | reclaimed retention count threshold |
| `RUNTIME_STATUS_RECENT_RECOVERY_LIMIT` | `5` | recent recovery events returned in runtime snapshot |

### Runtime-retention automation

| Variable | Default | Purpose |
| --- | --- | --- |
| `RUNTIME_RETENTION_DAYS` | `30` | retention window |
| `RUNTIME_RETENTION_ARTIFACT_PATH` | `artifacts/runtime-retention-cleanup` | cleanup evidence path |
| `RUNTIME_RETENTION_HISTORY_LIMIT` | `30` | retained cleanup history count |
| `RUNTIME_RETENTION_HISTORY_MAX_AGE_DAYS` | `90` | retained cleanup max age |
| `RUNTIME_RETENTION_AUTOMATION_OPERATOR_ID` | `runtime-retention-automation` | scheduled cleanup operator identity |
| `RUNTIME_RETENTION_AUTOMATION_JOB_ID` | `runtime-retention-scheduled` | scheduled cleanup job identity |
| `RUNTIME_RETENTION_WORKER_POLL_SECONDS` | `3600.0` | retention worker poll interval |
| `RUNTIME_RETENTION_WORKER_APPLY` | `false` | apply instead of dry run in scheduled worker |
| `RUNTIME_RETENTION_MANUAL_RUN_COOLDOWN_SECONDS` | `300.0` | manual cleanup cooldown |
| `RUNTIME_RETENTION_APPLY_PREVIEW_MAX_AGE_SECONDS` | `3600.0` | max preview age before apply |
| `RUNTIME_RETENTION_ACTION_LEASE_STALE_SECONDS` | `3600.0` | stale action lease threshold |

### Analytics offload thresholds

| Variable | Default | Purpose |
| --- | --- | --- |
| `RETURNS_SERIES_EXECUTOR_WINDOW_DAYS` | `180` | returns-series async threshold by window |
| `RETURNS_SERIES_EXECUTOR_INPUT_COUNT` | `250` | returns-series async threshold by input size |
| `TWR_EXECUTOR_WINDOW_DAYS` | `180` | TWR async threshold by window |
| `TWR_EXECUTOR_INPUT_COUNT` | `250` | TWR async threshold by input size |
| `WORKSPACE_SUMMARY_EXECUTOR_WINDOW_DAYS` | `180` | workspace-summary async threshold by window |
| `WORKSPACE_SUMMARY_EXECUTOR_INPUT_COUNT` | `250` | workspace-summary async threshold by input size |
| `BENCHMARK_EXECUTOR_WINDOW_DAYS` | `180` | benchmark async threshold by window |
| `BENCHMARK_EXECUTOR_INPUT_COUNT` | `250` | benchmark async threshold by input size |
| `CONTRIBUTION_EXECUTOR_WINDOW_DAYS` | `180` | contribution async threshold by window |
| `CONTRIBUTION_EXECUTOR_POSITION_COUNT` | `250` | contribution async threshold by position count |
| `ATTRIBUTION_EXECUTOR_WINDOW_DAYS` | `180` | attribution async threshold by window |
| `ATTRIBUTION_EXECUTOR_INPUT_COUNT` | `250` | attribution async threshold by input size |

### Methodology and rollout toggles

| Variable | Default | Purpose |
| --- | --- | --- |
| `CONTRIBUTION_RESET_AWARE_AVERAGE_WEIGHT_MODE` | `OFF` | contribution average-weight rollout mode |

### Recovery-drill retention and control

| Variable | Default | Purpose |
| --- | --- | --- |
| `RECOVERY_DRILL_ARTIFACT_PATH` | `artifacts/durable-recovery-drill` | drill evidence path |
| `RECOVERY_DRILL_RETENTION_LIMIT` | `30` | retained drill history count |
| `RECOVERY_DRILL_RETENTION_MAX_AGE_DAYS` | `90` | retained drill max age |
| `RECOVERY_DRILL_MANUAL_RUN_COOLDOWN_SECONDS` | `300.0` | manual drill cooldown |
| `RECOVERY_DRILL_ACTION_LEASE_STALE_SECONDS` | `3600.0` | stale drill action lease threshold |

## Example Files

Current shipped example request/response artifacts:

- `docs/examples/twr_request.json`
- `docs/examples/twr_request_with_benchmark.json`
- `docs/examples/twr_request_with_benchmark_price_points.json`
- `docs/examples/twr_request_multiccy_hedged.json`
- `docs/examples/mwr_request.json`
- `docs/examples/benchmark_request.json`
- `docs/examples/benchmark_request_price_points.json`
- `docs/examples/benchmark_vendor_series_request.json`
- `docs/examples/contribution_request.json`
- `docs/examples/contribution_request_multiccy.json`
- `docs/examples/attribution_request.json`
- `docs/examples/attribution_request_multiccy.json`
- `docs/examples/workspace_summary_request.json`
- `docs/examples/workspace_summary_stateful_detail_request.json`
- `docs/examples/workspace_summary_accepted_response.json`
- `docs/examples/integration_capabilities_response.json`

Runtime threshold example files:

- `docs/examples/runtime-thresholds.development.env`
- `docs/examples/runtime-thresholds.staging.env`
- `docs/examples/runtime-thresholds.production.env`
- `docs/examples/docker-compose.runtime-thresholds.development.yml`
- `docs/examples/docker-compose.runtime-thresholds.staging.yml`
- `docs/examples/docker-compose.runtime-thresholds.production.yml`

## Practical Usage Notes

- Prefer the Lotus-style dual-mode envelope for new integrations:
  - `input_mode`
  - `stateless_input`
  - `stateful_input`
- Use `calculation_id` as a durable execution handle, not as an optional tracing hint.
- Use `GET /integration/capabilities` as the machine-readable source of truth for endpoint support,
  stateful fences, async result paths, and supported workspace options.
- Use dedicated endpoints for deep analysis:
  - `POST /performance/contribution`
  - `POST /performance/attribution`
- Use `POST /performance/workspace-summary` when one UI action needs a coherent, lighter-weight
  portfolio / benchmark / active / MWR / contribution / attribution story across multiple horizons.
