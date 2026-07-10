# Engine Configuration

The performance engine's behavior is controlled by a comprehensive and immutable `EngineConfig` object. This object is constructed by the `api_adapter` from the API request and passed into all core calculation functions, ensuring that each run is explicit and reproducible.

---

## Core Parameters

### Performance Dates

-   **`performance_start_date`**: The earliest date from which performance can be calculated, often the portfolio's inception date. This acts as a floor for all period calculations.
-   **`report_start_date`**: The specific start date of the requested reporting window. Used by `EXPLICIT` period types.
-   **`report_end_date`**: The final date of the reporting window. All results are filtered to end on or before this date.

### Precision

-   **`precision_mode`**: Controls the numerical precision of calculations.
    -   `FLOAT64`: The default mode, using standard NumPy `float64` for maximum performance.
    -   `DECIMAL_STRICT`: Uses Python's `Decimal` type for arbitrary-precision arithmetic. This is slower but eliminates floating-point drift, making it suitable for compliance and auditing.
-   **`rounding_precision`**: The number of decimal places to round final `float64` results to. This has no effect in `DECIMAL_STRICT` mode.

### Metric Basis

-   **`metric_basis`**: Determines whether returns are calculated before or after fees.
    -   `NET`: Returns are calculated after subtracting `mgmt_fees`. The formula's numerator effectively becomes `EndMV - BMV - CFs + Fees`.
    -   `GROSS`: Returns are calculated before fees; the `mgmt_fees` column is ignored.

### Period Type

The `period_type` defines how the engine resolves the effective start date for calculations. This is handled by `core/periods.py`.
-   **`MTD`/`QTD`/`YTD`**: Standard calendar month-to-date, quarter-to-date, and year-to-date.
-   **`SI`**: Since inception, starting from `performance_start_date`; legacy `ITD` aliases normalize to `SI`.
-   **`Y1`/`Y3`/`Y5`**: Rolling 1, 3, or 5-year periods ending on `report_end_date`.
-   **`EXPLICIT`**: Uses the `report_start_date` provided in the request.

---

## Multi-Currency Parameters

These parameters activate and control the FX-aware analytics.

-   **`currency_mode`**: A string that can be `"BASE_ONLY"` (default), `"LOCAL_ONLY"`, or `"BOTH"`. Setting to `"BOTH"` enables the full local/fx/base return decomposition.
-   **`report_ccy`**: The three-letter ISO code for the portfolio's base reporting currency (e.g., `"USD"`). Required when `currency_mode` is not `"BASE_ONLY"`.
-   **`fx`**: An object containing the client-supplied FX rates. The engine uses this data to calculate daily FX returns.
-   **`hedging`**: An optional object containing the client-supplied hedging strategy, such as a daily `hedge_ratio` to model the net effect of currency hedges.

---

## Shared Envelope Parameters

These parameters are part of the unified API envelope and influence engine behavior.

### Calendar

-   **`type`**:
    -   `BUSINESS`: Calculation assumes business days (e.g., 252 days per year for annualization).
    -   `NATURAL`: Calculation assumes all calendar days.
-   **`trading_calendar`**: Optional exchange-calendar identifier preserved in the request,
    diagnostics, and reproducibility metadata (e.g., `NYSE`). The current calculation engine uses
    `type` and annualization settings for day-count behavior; venue-specific holiday calendars are
    not applied unless a caller has provided an implementation-backed calendar integration.

### Annualization

-   **`enabled`**: A boolean flag to enable or disable the calculation of annualized returns.
-   **`basis`**: The day-count convention to use for annualization.
    -   `BUS/252`: Uses a 252-day year.
    -   `ACT/365`: Uses the actual number of days in the period over a fixed 365-day year.
    -   `ACT/ACT`: Uses the actual number of days in the period over the actual number of days in the year (e.g., 365.25 to account for leap years).
-   **`periods_per_year`**: An optional override for the annualization factor (e.g., 252 or 365).

### Flags

-   **`fail_fast`**: When `true`, completed TWR, MWR, Contribution, and Attribution responses
    that contain governed warning, fallback, diagnostic-note, degraded supportability, or
    supportability-reason evidence return HTTP `422` with `error_code=FAIL_FAST_SOFT_WARNING`
    instead of returning a `200` degraded result. The same request returns the degraded response
    when `fail_fast=false`. Initial async `202 Accepted` envelopes are not rejected before the
    calculation has completed.

---

## Diagnostics & Audit

All engine calculations are designed to emit diagnostic and audit information, which is surfaced in the final API response.
-   **Diagnostics**:
    -   `nip_days`: Count of days flagged as No-Investment-Periods.
    -   `reset_days`: Count of days where performance compounding was reset.
    -   `notes`: A list of strings containing informational messages, such as calculation fallbacks or assumptions made.
-   **Audit**:
    -   `sum_of_parts_vs_total_bp`: For contribution and attribution, this shows the residual between the sum of component effects and the total portfolio effect, measured in basis points.
    -   `counts`: Key metrics about the input data, such as the number of rows processed or positions analyzed.
