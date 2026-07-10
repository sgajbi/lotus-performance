# docs/guides/multi_currency.md
# Multi-Currency & FX-Aware Analytics

The performance engine has endpoint-specific support for portfolios with assets denominated in
multiple currencies. This guide explains how to use these features and interpret the results for
TWR, Contribution, and Attribution. Use the
[RFC-020 multi-currency support matrix](../technical/rfc-020-multi-currency-support-matrix.md) as
the canonical current truth before assuming currency-mode parity across endpoints.

---

## Activating Multi-Currency Mode

Where an endpoint supports the RFC-020 decomposition path, requests use these fields:
-   `"currency_mode": "BOTH"`: Instructs the engine to perform a full decomposition.
-   `"report_ccy": "USD"`: Specifies the final, base currency for all top-level reporting.
-   `"fx": { ... }`: An object containing the daily foreign exchange rates required for the calculation.

When in this mode, all monetary values (`begin_mv`, `end_mv`, `bod_cf`, etc.) for each position in `positions_data` or `instruments_data` are assumed to be in that asset's **local currency**, as specified in its `meta.currency` field.

---

## Return Decomposition (Local | FX | Base)

The core of the framework is the daily decomposition of an asset's total return in the base currency ($r^B$) into two components:
-   **Local Return ($r^L$)**: The performance of the asset in its own currency.
-   **FX Return ($r^X$)**: The performance of the asset's local currency against the portfolio's base currency.

The relationship is geometric: $(1 + r^B) = (1 + r^L) \cdot (1 + r^X)$.

The API surfaces this decomposition in the responses for TWR and Contribution, allowing you to clearly distinguish between performance from asset selection and performance from currency movements.

---

## Modeling Currency Hedges

The engine supports two distinct, **mutually exclusive** methods for modeling the impact of currency hedging. You must choose one method to avoid incorrect results.

### 1. The Modeling Approach (using `hedge_ratio`)

This is a high-level approach that models the *net economic effect* of a hedging strategy.
-   **How it Works**: Provide a `hedging` block in your request with a `hedge_ratio` (between 0.0 and 1.0) for a given currency on a given day. A ratio of `0.75` means 75% of the currency exposure was hedged.
-   **Caller Responsibility**: When using this method, you **must exclude** the specific hedging instruments (e.g., forward contracts) from your `positions_data`. Including them will double-count the hedge.
-   **Example**: See `docs/examples/twr_request_multiccy_hedged.json`.

### 2. The Explicit Approach (Providing Hedging Instruments)

This is a bottom-up approach that uses the actual performance of the hedging instruments.
-   **How it Works**: Provide the hedging instruments (e.g., a currency forward) as regular items in the `positions_data` array, with their own market values and cash flows.
-   **Caller Responsibility**: When using this method, **do not** provide a `hedge_ratio` for the currency being hedged. The engine will naturally calculate the offsetting P&L from the explicit instruments.

---

## Currency Attribution (Karnosky-Singer)

When running the `/performance/attribution` endpoint in multi-currency mode, the engine provides an additional breakdown of active return based on the Karnosky-Singer model. It decomposes the total active return for each currency into four effects:
-   **Local Allocation**: Effect of over/underweighting asset markets within the currency.
-   **Local Selection**: Effect of security selection within those local markets.
-   **Currency Allocation**: Effect of over/underweighting the currency itself.
-   **Currency Selection**: The interaction effect between local returns and currency movements.

This provides a powerful tool for understanding whether a portfolio's active return was driven by asset selection skill or by currency timing decisions.
-   **Example**: See `docs/examples/attribution_request_multiccy.json`.
