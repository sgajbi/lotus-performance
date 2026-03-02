# Metric: Money-Weighted Return (Simple Dietz Fallback)

## Quantitative Conventions
- Unless explicitly noted otherwise, endpoint-level performance and attribution outputs are expressed in **percentage points**.
- `returns/series` payload values are expressed in **decimal return form** (`0.0012 = 12 bps`).
- Geometric linking uses `Π(1+r_t)-1`.
- Annualization uses the configured day-count basis and annualization factor.

## Lotus-Performance Endpoint(s)
- `POST /performance/mwr` (fallback from XIRR failure, or explicit `DIETZ`/`MODIFIED_DIETZ` request).

## Supported Calculation Modes
- Stateless.

## Upstream Data Sources and Exact Data Points
- Request payload only.

## Inputs
- `begin_mv`, `end_mv`, net cash flow `ΣCF`.

## Methodology and Formulas
- Periodic rate: `r = (end_mv - begin_mv - ΣCF) / (begin_mv + ΣCF/2)`.
- If denominator is zero, return `0` with explanatory note.
- If annualization enabled: `r_ann = (1+r)^{ppy/days}-1` where `ppy` from basis (`ACT/ACT`=>365.25 else 365).
- Current implementation note: `MODIFIED_DIETZ` requests are handled by this same Dietz formula path in the engine.

## Outputs
- `money_weighted_return` (%), optional `mwr_annualized`, `method="DIETZ"` in fallback path.

## Configuration Options
- `annualization.enabled`, `annualization.basis`.

## Assumptions and Edge Cases
- Input series are expected to be date-valid, sortable, and semantically aligned with the request window.
- For insufficient observations or invalid denominator conditions, the engine returns deterministic error semantics (HTTP validation error and/or metric-level error details depending on endpoint contract).
- Where configured, policy controls (missing-data policy, fill method, reset rules, robustness policies) can materially change results and must be interpreted with diagnostics.

## Worked Example
- begin=100, end=112, CF=+10 => `r=(112-100-10)/(100+5)=1.9048%`.



