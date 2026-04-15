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
- current reconciliation checks cover mixed position epochs, duplicate position snapshot rows, invalid epoch labels, invalid selected position end values, and portfolio-versus-position tie-out gaps
- current source-economics checks cover fee and external cash-flow classification loss, conflicting or malformed explicit fee or bod/eod source totals, fee and external normalization mismatches, duplicate raw source signals, positive fee sign anomalies, fee or external explicit source-total mismatches, external timing-bucket contradictions, invalid detailed cash-flow amounts, invalid timing labels, missing `cash_flow_type` labels, and non-canonical `cash_flow_type` labels
- the full support-facing finding inventory lives in `docs/guides/twr_inspection_checks.md`

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

- calculate money-weighted return
- supports `stateless` and `stateful` input modes

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
  "annualized_return": 3.27,
  "input_mode": "stateless",
  "notes": []
}
```

### `POST /performance/workspace-summary`

Purpose:

- return one coherent multi-horizon workspace response
- can include:
  - `portfolio_twr.net`
  - `portfolio_twr.gross`
  - benchmark summary
  - active summary
  - money-weighted return
  - optional contribution summary
  - optional attribution summary

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
  "segmentation": {
    "group_by": ["sector", "country"]
  },
  "contribution": {
    "metric_basis": "NET",
    "top_positions": 5
  },
  "attribution": {
    "metric_basis": "NET"
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
        "annualized_return": 3.27
      },
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

### `GET /performance/workspace-summary/results/{calculation_id}`

Purpose:

- retrieve the final durable workspace-summary result

Sample response:

```json
{
  "calculation_id": "0d000003-1111-4222-8333-abcdefabcdef",
  "status": "complete",
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
          "rows": [
            {
              "label": "technology",
              "portfolio_weight_avg": 60.5,
              "benchmark_weight_avg": 58.0,
              "portfolio_return": 3.2,
              "benchmark_return": 2.8,
              "allocation": 0.1,
              "selection": 0.2,
              "interaction": 0.0,
              "total_effect": 0.3
            }
          ]
        }
      ]
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

Sample response:

```json
{
  "calculation_id": "0d000003-1111-4222-8333-abcdefabcdef",
  "analytics_type": "WORKSPACE_SUMMARY",
  "status": "complete",
  "stages": [
    { "name": "execution", "status": "complete" },
    { "name": "lineage", "status": "queued" }
  ],
  "compute_job": {
    "status": "complete"
  },
  "async_result": {
    "status": "complete",
    "result_path": "/performance/workspace-summary/results/0d000003-1111-4222-8333-abcdefabcdef"
  }
}
```

### `GET /performance/lineage/{calculation_id}`

Purpose:

- inspect lineage status and artifact inventory for a calculation

Sample response:

```json
{
  "calculation_id": "0d000003-1111-4222-8333-abcdefabcdef",
  "status": "complete",
  "manifest_path": "lineage_data/0d000003-1111-4222-8333-abcdefabcdef/manifest.json",
  "artifacts": [
    {
      "name": "workspace_summary_portfolio_daily_results_net.csv",
      "download_path": "/performance/lineage/0d000003-1111-4222-8333-abcdefabcdef/artifacts/workspace_summary_portfolio_daily_results_net.csv"
    }
  ]
}
```

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

### `POST /integration/returns/series`

Purpose:

- return canonical portfolio, benchmark, risk-free, and active return series

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
    ]
  },
  "cumulative_active_returns": [
    { "date": "2026-03-30", "return_value": 0.2 },
    { "date": "2026-03-31", "return_value": 0.7 }
  ]
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

### `GET /integration/runtime-status`

Purpose:

- provide a bounded runtime health snapshot for compute, lineage, recovery, and retention lanes

Sample response:

```json
{
  "durable_store_available": true,
  "lineage_storage_available": true,
  "compute": {
    "availability": "available",
    "pending_count": 0,
    "running_count": 0
  },
  "lineage": {
    "availability": "available",
    "pending_count": 0
  },
  "inspection_anchors": {
    "work_items_path": "/integration/runtime-work-items",
    "recoveries_path": "/integration/runtime-recoveries"
  }
}
```

### `GET /integration/runtime-work-items`

Purpose:

- inspect active, failed, or reclaimable compute and lineage work items

Sample request:

```text
GET /integration/runtime-work-items?queue=both&status=active&limit=25
```

Sample response:

```json
{
  "queue": "both",
  "status_filter": "active",
  "compute": {
    "total_count": 1,
    "returned_count": 1,
    "items": [
      {
        "calculation_id": "0d000003-1111-4222-8333-abcdefabcdef",
        "analytics_type": "WORKSPACE_SUMMARY",
        "status": "running",
        "execution_path": "/performance/executions/0d000003-1111-4222-8333-abcdefabcdef",
        "result_path": "/performance/workspace-summary/results/0d000003-1111-4222-8333-abcdefabcdef"
      }
    ]
  }
}
```

### `GET /integration/runtime-recoveries`

Purpose:

- inspect recent compute and lineage recovery events

Sample request:

```text
GET /integration/runtime-recoveries?queue=both&limit=10
```

Sample response:

```json
{
  "queue": "both",
  "compute": {
    "returned_count": 1,
    "items": [
      {
        "calculation_id": "0d000003-1111-4222-8333-abcdefabcdef",
        "analytics_type": "WORKSPACE_SUMMARY",
        "recovery_kind": "lease_reclaimed",
        "recovered_at": "2026-03-29T02:05:00Z"
      }
    ]
  }
}
```

### `GET /integration/recovery-drills`

Purpose:

- inspect retained recovery-drill evidence and history

Sample response:

```json
{
  "latest": {
    "status": "passed",
    "backup_identifier": "backup-2026-03-29",
    "generated_at": "2026-03-29T01:30:00Z"
  },
  "items": [
    {
      "status": "passed",
      "operator_id": "ops-user",
      "backup_identifier": "backup-2026-03-29"
    }
  ]
}
```

### `POST /integration/recovery-drills/run`

Purpose:

- execute a governed recovery drill

Sample request:

```json
{
  "backup_identifier": "backup-2026-03-29"
}
```

Sample response:

```json
{
  "status": "passed",
  "backup_identifier": "backup-2026-03-29",
  "operator_id": "ops-user",
  "artifact_path": "artifacts/durable-recovery-drill/latest.json"
}
```

### `GET /integration/runtime-retention-cleanups`

Purpose:

- inspect retained runtime-retention cleanup evidence and history

Sample response:

```json
{
  "latest": {
    "cleanup_mode": "dry_run",
    "status": "ok",
    "generated_at": "2026-03-29T01:45:00Z"
  },
  "items": [
    {
      "cleanup_mode": "dry_run",
      "trigger_mode": "manual",
      "status": "ok",
      "retention_days": 30
    }
  ]
}
```

### `POST /integration/runtime-retention-cleanups/run`

Purpose:

- execute a governed retention cleanup dry run or apply action

Sample request:

```json
{
  "apply": false,
  "retention_days": 30
}
```

Sample response:

```json
{
  "cleanup_mode": "dry_run",
  "status": "ok",
  "operator_id": "ops-user",
  "retention_days": 30,
  "artifact_path": "artifacts/runtime-retention-cleanup/latest.json"
}
```

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
  "reason": "lineage_storage_write_probe_failed"
}
```

### `GET /metrics`

Purpose:

- expose Prometheus metrics

Sample response excerpt:

```text
# HELP lotus_performance_compute_queue_degradation_breach Queue degradation breach gauge
# TYPE lotus_performance_compute_queue_degradation_breach gauge
lotus_performance_compute_queue_degradation_breach{reason="pending_age_exceeded"} 0
```

## Execution Pattern

Async-capable endpoints use one shared pattern:

1. submit the request
2. receive a final result or `202 Accepted`
3. poll `GET /performance/executions/{calculation_id}`
4. retrieve the endpoint-specific result path

Current endpoint-specific async result routes:

- `/performance/twr/results/{calculation_id}`
- `/performance/benchmark/results/{calculation_id}`
- `/performance/workspace-summary/results/{calculation_id}`
- `/performance/contribution/results/{calculation_id}`
- `/performance/attribution/results/{calculation_id}`
- `/integration/returns/series/results/{calculation_id}`

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

### Lineage storage and worker

| Variable | Default | Purpose |
| --- | --- | --- |
| `LINEAGE_STORAGE_PATH` | `lineage_data` | artifact storage root |
| `LINEAGE_STORAGE_HEALTHCHECK_WRITE_PROBE_ENABLED` | `true` | enable readiness write/delete probe |
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
