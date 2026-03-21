 
# Data Model (Inputs & Outputs)

This document defines the canonical request and response schemas used across the performance analytics modules. The API enforces a strict `snake_case` naming convention for all fields.

---
## Shared Components

### DailyInputData

This is the standard structure for providing a single day of performance data. It is used in TWR, Contribution, and Attribution requests.

```json
{
  "perf_date": "2025-01-01",
  "begin_mv": 100000.0,
  "bod_cf": 0.0,
  "eod_cf": 0.0,
  "mgmt_fees": 0.0,
  "end_mv": 101000.0
}
````

  - **`perf_date`**: The specific date of the observation in `YYYY-MM-DD` format.
  - **`begin_mv`**: The market value at the beginning of the day.
  - **`end_mv`**: The market value at the end of the day.
  - **`bod_cf`**: Any cash flow occurring at the beginning of the day (before trading).
  - **`eod_cf`**: Any cash flow occurring at the end of the day (after trading).
  - **`mgmt_fees`**: Management fees charged for the day, which reduce the portfolio's value.
  - Observation order is derived server-side from sorted `perf_date`; callers do not send a separate `day` field.

### DataPolicy (Optional)

An optional object that allows for on-the-fly data correction and flagging. See the `robustness_policies.md` guide for details.

```json
"data_policy": {
  "overrides": {
    "market_values": [],
    "cash_flows": []
  },
  "ignore_days": [],
  "outliers": { "enabled": true, "action": "FLAG" }
}
```

-----

### Enums

  - **`Frequency`**: Defines the aggregation periods for TWR breakdowns: `daily`, `weekly`, `monthly`, `quarterly`, `yearly`.
  - **`PeriodType`**: Defines how the reporting window is resolved: `MTD`, `QTD`, `YTD`, `ITD`, `1Y`, `3Y`, `5Y`, `EXPLICIT`.
  - **`MetricBasis`**: Defines whether returns are calculated before or after fees: `NET`, `GROSS`.
  - **`PrecisionMode`**: Defines the numerical precision used by the engine: `FLOAT64` (fast, default) or `DECIMAL_STRICT` (auditable).

-----

### Response Envelope

All API responses include a shared footer for context, diagnostics, and auditability.

  - **`meta`**: Contains metadata about the calculation itself.
      - `calculation_id`: The unique UUID for the request.
      - `engine_version`: The version of the application that ran the calculation.
      - `input_fingerprint`: A SHA256 hash of the canonical request payload.
      - `calculation_hash`: A SHA256 hash of the request payload combined with the engine version, providing a unique fingerprint for the entire calculation event.
      - `precision_mode`: The precision mode used (`FLOAT64` or `DECIMAL_STRICT`).
      - `annualization`: The annualization settings that were applied.
      - `calendar`: The calendar settings used.
      - `periods`: The resolved period type, start, and end dates for the calculation.
  - **`diagnostics`**: Provides insights into the engine's behavior and any rules that were triggered.
      - `nip_days`: The total number of "No Investment Period" days identified.
      - `reset_days`: The total number of performance reset days applied.
      - `effective_period_start`: The actual start date used for the calculation after resolving the `period_type`.
      - `notes`: A list of informational messages from the engine (e.g., fallbacks used, assumptions made).
      - **`policy`**: An object detailing actions taken by the Robustness Policies Framework (e.g., number of overrides applied, outliers flagged).
  - **`audit`**: Contains data for reconciliation and validation.
      - `sum_of_parts_vs_total_bp`: For contribution/attribution, the residual between the sum of components and the total, in basis points.
      - `counts`: A dictionary of key counts, such as `input_rows`, `output_rows`, or `cashflows`.

-----

## Example Response (TWR)

The following shows a complete TWR response, including the data payload (`breakdowns`) and the shared envelope (`meta`, `diagnostics`, `audit`).

```json
{
  "calculation_id": "a4b7e289-7e28-4b7e-8e28-7e284b7e8e28",
  "portfolio_id": "TWR_EXAMPLE_01",
  "breakdowns": {
    "daily": [
      {
        "period": "2025-01-01",
        "summary": {
          "begin_mv": 100000.0,
          "end_mv": 101000.0,
          "net_cash_flow": 0.0,
          "period_return_pct": 1.0,
          "cumulative_return_pct_to_date": 1.0
        }
      }
    ]
  },
  "reset_events": [],
  "meta": {
    "calculation_id": "a4b7e289-7e28-4b7e-8e28-7e284b7e8e28",
    "engine_version": "0.5.0",
    "precision_mode": "FLOAT64",
    "input_fingerprint": "sha256:b3e1...",
    "calculation_hash": "sha256:5a2c...",
    "annualization": {
      "enabled": false,
      "basis": "BUS/252",
      "periods_per_year": null
    },
    "calendar": {
      "type": "BUSINESS",
      "trading_calendar": "NYSE"
    },
    "periods": {
      "type": "YTD",
      "start": "2025-01-01",
      "end": "2025-01-05"
    }
  },
  "diagnostics": {
    "nip_days": 0,
    "reset_days": 0,
    "effective_period_start": "2025-01-01",
    "notes": [],
    "policy": null
  },
  "audit": {
    "sum_of_parts_vs_total_bp": null,
    "residual_applied_bp": null,
    "counts": {
      "input_rows": 5,
      "output_rows": 5
    }
  }
}
```


