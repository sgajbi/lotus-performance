# API Examples & Recipes

This document provides truthful request examples for the shipped `lotus-performance` public
contract.

Use these as starting points for integrations. The examples below follow the current Lotus-style
mode envelope:

- `input_mode: "stateless" | "stateful"`
- `stateless_input` for direct caller-supplied data
- `stateful_input` for lotus-core-backed sourcing

Older examples using request-level `period_type` or nested `daily_data` are not current.

## 1. Standard Time-Weighted Return (TWR)

Calculates daily and monthly TWR from direct caller-supplied valuation points.

**Endpoint**

```text
POST /performance/twr
```

**Payload**

```json
{
  "input_mode": "stateless",
  "portfolio_id": "TWR_EXAMPLE_01",
  "performance_start_date": "2024-12-31",
  "report_end_date": "2025-01-05",
  "metric_basis": "NET",
  "analyses": [
    {
      "period": "YTD",
      "frequencies": ["daily", "monthly"]
    }
  ],
  "stateless_input": {
    "valuation_points": [
      { "perf_date": "2025-01-01", "begin_mv": 100000.0, "end_mv": 101000.0 },
      { "perf_date": "2025-01-02", "begin_mv": 101000.0, "end_mv": 102010.0 },
      { "perf_date": "2025-01-03", "begin_mv": 102010.0, "end_mv": 100989.9 },
      { "perf_date": "2025-01-04", "begin_mv": 100989.9, "bod_cf": 25000.0, "end_mv": 127249.29 },
      { "perf_date": "2025-01-05", "begin_mv": 127249.29, "end_mv": 125976.7971 }
    ]
  }
}
```

## 2. Stateful TWR from lotus-core

Calculates TWR from portfolio timeseries sourced from lotus-core query-control-plane. In stateful
mode, lotus-performance retrieves the authoritative portfolio open date and normalizes the sourced
timeseries into the same TWR engine inputs used by stateless requests.

**Endpoint**

```text
POST /performance/twr
```

**Payload**

```json
{
  "input_mode": "stateful",
  "portfolio_id": "DEMO_DPM_EUR_001",
  "report_end_date": "2025-01-31",
  "metric_basis": "NET",
  "analyses": [
    {
      "period": "YTD",
      "frequencies": ["daily", "monthly"]
    }
  ],
  "stateful_input": {}
}
```

## 3. TWR with Benchmark and Relative Performance

Calculates portfolio TWR, benchmark TWR, and arithmetic relative performance in one request.

**Endpoint**

```text
POST /performance/twr
```

**Payload**

```json
{
  "input_mode": "stateless",
  "portfolio_id": "TWR_WITH_BENCHMARK_01",
  "performance_start_date": "2024-12-31",
  "report_end_date": "2025-01-02",
  "metric_basis": "NET",
  "include_benchmark": true,
  "analyses": [
    {
      "period": "YTD",
      "frequencies": ["daily"]
    }
  ],
  "stateless_input": {
    "valuation_points": [
      { "perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0 },
      { "perf_date": "2025-01-02", "begin_mv": 1010.0, "end_mv": 1020.1 }
    ]
  },
  "benchmark": {
    "benchmark_id": "BMK_STATELESS_1",
    "input_mode": "stateless",
    "return_source": "calculated",
    "stateless_input": {
      "benchmark_currency": "USD",
      "component_observations": [
        { "component_id": "IDX_A", "perf_date": "2025-01-01", "weight_bop": 1.0, "component_return": 0.01 },
        { "component_id": "IDX_A", "perf_date": "2025-01-02", "weight_bop": 1.0, "component_return": 0.015 }
      ]
    }
  }
}
```

**Response excerpt**

```json
{
  "results_by_period": {
    "YTD": {
      "portfolio": {
        "summary": {
          "period_return": {
            "base": 2.01
          },
          "cumulative_return": {
            "base": 2.01
          }
        }
      },
      "benchmark": {
        "summary": {
          "period_return": {
            "base": 2.515
          },
          "cumulative_return": {
            "base": 2.515
          }
        },
        "benchmark_id": "BMK_STATELESS_1"
      },
      "relative_performance": {
        "summary": {
          "period_return": {
            "base": -0.505
          },
          "cumulative_return": {
            "base": -0.505
          }
        }
      }
    }
  }
}
```

## 4. Benchmark from Stateless Component Price Points

Calculates benchmark performance directly from raw component price points. This is useful when the
caller has component levels but does not want to precompute component returns outside
`lotus-performance`.

**Endpoint**

```text
POST /performance/benchmark
```

**Payload**

```json
{
  "input_mode": "stateless",
  "benchmark_id": "BMK_STATELESS_PRICE_1",
  "benchmark_start_date": "2026-01-02",
  "report_end_date": "2026-01-02",
  "analyses": [
    {
      "period": "ITD",
      "frequencies": ["daily"]
    }
  ],
  "return_source": "calculated",
  "output": {
    "include_timeseries": true
  },
  "stateless_input": {
    "benchmark_currency": "USD",
    "component_price_points": [
      { "component_id": "IDX_A", "perf_date": "2026-01-01", "weight_bop": 0.6, "index_price": 100.0 },
      { "component_id": "IDX_A", "perf_date": "2026-01-02", "weight_bop": 0.6, "index_price": 102.0 },
      {
        "component_id": "IDX_B",
        "perf_date": "2026-01-01",
        "weight_bop": 0.4,
        "index_price": 100.0,
        "component_currency": "EUR",
        "fx_rate_to_benchmark": 1.2
      },
      {
        "component_id": "IDX_B",
        "perf_date": "2026-01-02",
        "weight_bop": 0.4,
        "index_price": 101.0,
        "component_currency": "EUR",
        "fx_rate_to_benchmark": 1.212
      }
    ]
  }
}
```

## 5. Stateful Money-Weighted Return (MWR) from lotus-core

Calculates MWR from lotus-core portfolio timeseries over an explicitly requested measurement
window.

**Endpoint**

```text
POST /performance/mwr
```

**Payload**

```json
{
  "input_mode": "stateful",
  "portfolio_id": "MWR_STATEFUL_01",
  "as_of": "2025-12-31",
  "mwr_method": "XIRR",
  "annualization": {
    "enabled": true,
    "basis": "ACT/ACT"
  },
  "stateful_input": {
    "window_start_date": "2025-01-01"
  }
}
```

## 5. Dedicated Benchmark Calculation

Calculates benchmark performance directly from benchmark component observations.

**Endpoint**

```text
POST /performance/benchmark
```

**Payload**

```json
{
  "input_mode": "stateless",
  "benchmark_id": "BMK_STATELESS_1",
  "benchmark_start_date": "2026-01-02",
  "report_end_date": "2026-01-03",
  "analyses": [
    {
      "period": "ITD",
      "frequencies": ["daily"]
    }
  ],
  "return_source": "calculated",
  "output": {
    "include_timeseries": true
  },
  "stateless_input": {
    "benchmark_currency": "USD",
    "component_observations": [
      {
        "component_id": "IDX_A",
        "perf_date": "2026-01-02",
        "weight_bop": 0.6,
        "component_return": 0.02
      },
      {
        "component_id": "IDX_B",
        "perf_date": "2026-01-02",
        "weight_bop": 0.4,
        "component_return": 0.01
      }
    ]
  }
}
```

## 6. Multi-Currency Contribution

Calculates contribution for a portfolio with positions in multiple currencies and decomposes the
result into local and FX-aware portfolio return context.

**Endpoint**

```text
POST /performance/contribution
```

**Payload**

```json
{
  "input_mode": "stateless",
  "portfolio_id": "MULTI_ASSET_MCY_01",
  "report_start_date": "2025-01-01",
  "report_end_date": "2025-01-01",
  "analyses": [
    {
      "period": "ITD",
      "frequencies": ["daily"]
    }
  ],
  "currency_mode": "BOTH",
  "report_ccy": "USD",
  "stateless_input": {
    "portfolio_data": {
      "metric_basis": "GROSS",
      "valuation_points": [
        { "perf_date": "2025-01-01", "begin_mv": 10305.0, "end_mv": 10563.66 }
      ]
    },
    "positions_data": [
      {
        "position_id": "EUR_STOCK",
        "meta": { "currency": "EUR", "sector": "Industrials" },
        "valuation_points": [
          { "perf_date": "2025-01-01", "begin_mv": 100.0, "end_mv": 102.0 }
        ]
      },
      {
        "position_id": "JPY_STOCK",
        "meta": { "currency": "JPY", "sector": "Technology" },
        "valuation_points": [
          { "perf_date": "2025-01-01", "begin_mv": 1500000.0, "end_mv": 1515000.0 }
        ]
      }
    ]
  },
  "fx": {
    "rates": [
      { "date": "2024-12-31", "ccy": "EUR", "rate": 1.05 },
      { "date": "2025-01-01", "ccy": "EUR", "rate": 1.08 },
      { "date": "2024-12-31", "ccy": "JPY", "rate": 0.0068 },
      { "date": "2025-01-01", "ccy": "JPY", "rate": 0.0069 }
    ]
  }
}
```

## 7. Multi-Currency Attribution

Runs stateless currency-aware attribution using caller-supplied benchmark groups and FX inputs.

This example is intentionally stateless. The current public stateful attribution path is fenced to:

- `mode="by_instrument"`
- `group_by` limited to `asset_class`, `sector`, `country`, or `currency`
- `currency_mode="BOTH"` requires `report_ccy`
- `currency_mode="BOTH"` requires `fx.rates` when sourced positions include currencies different from `report_ccy`

Stateful attribution can also emit currency attribution when those conditions are met and
`group_by` includes `currency`.

**Endpoint**

```text
POST /performance/attribution
```

**Payload**

```json
{
  "input_mode": "stateless",
  "portfolio_id": "ATTRIB_MCY_01",
  "mode": "by_instrument",
  "group_by": ["currency"],
  "linking": "none",
  "frequency": "daily",
  "currency_mode": "BOTH",
  "report_ccy": "USD",
  "report_start_date": "2025-01-01",
  "report_end_date": "2025-01-01",
  "analyses": [
    {
      "period": "ITD",
      "frequencies": ["daily"]
    }
  ],
  "stateless_input": {
    "portfolio_data": {
      "metric_basis": "GROSS",
      "valuation_points": [
        { "perf_date": "2025-01-01", "begin_mv": 100.0, "end_mv": 103.02 }
      ]
    },
    "instruments_data": [
      {
        "instrument_id": "EUR_ASSET",
        "meta": { "currency": "EUR" },
        "valuation_points": [
          { "perf_date": "2025-01-01", "begin_mv": 100.0, "end_mv": 102.0 }
        ]
      }
    ],
    "benchmark_groups_data": [
      {
        "key": { "currency": "EUR" },
        "observations": [
          {
            "date": "2025-01-01",
            "weight_bop": 1.0,
            "return_local": 0.015,
            "return_fx": 0.01,
            "return_base": 0.02515
          }
        ]
      }
    ]
  },
  "fx": {
    "rates": [
      { "date": "2024-12-31", "ccy": "EUR", "rate": 1.0 },
      { "date": "2025-01-01", "ccy": "EUR", "rate": 1.01 }
    ]
  }
}
```

Use `/docs` for exact field-level schemas, enums, and the latest generated examples.
