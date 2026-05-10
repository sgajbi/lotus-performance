# RFC 048 Slice 4 - Stateful Source Alignment and Upstream Contract Review

Date: 2026-05-11

Branch: `feat/rfc-048-attribution-industry-alignment`

## Scope

Slice 4 reviewed whether `lotus-performance` can represent attribution source truth from the
current `lotus-core` contracts without moving attribution methodology upstream. The review covered
portfolio valuation observations, position valuation rows, benchmark assignment, benchmark
component observations, index classification labels, currency evidence, FX support, and degraded
source states.

## Implementation

`lotus-performance` remains the attribution methodology authority. `lotus-core` remains the source
data authority. No `lotus-core` contract change was required in this slice because current source
contracts can support the approved RFC 048 attribution claims when `lotus-performance` preserves
source limits explicitly.

The implementation added bounded stateful source-alignment evidence during normalization:

1. portfolio observation count;
2. position row count;
3. resolved benchmark id;
4. benchmark component observation count;
5. index catalog record count;
6. requested classification dimensions;
7. classified and unclassified position-row counts;
8. classified and unclassified benchmark-component counts;
9. currency-mode source posture, reporting currency, position currency count, benchmark component
   currency count, FX-required flag, and FX-supplied flag;
10. explicit source-contract limitations for benchmark version, classification version, calendar
    policy, derivative or short flags, and fee/tax/income breakout.

The evidence is internal execution-stage evidence in this slice. Public API exposure, Swagger
certification, and downstream Gateway/Workbench contract realization remain governed by later RFC
048 slices.

## Source Contract Assessment

| Source requirement | Current state | Decision |
| --- | --- | --- |
| Portfolio beginning and ending market values | Available through `lotus-core` stateful portfolio timeseries and validated against summed positions. | Satisfied for approved attribution claims. |
| Position beginning and ending market values | Available through `lotus-core` position timeseries in portfolio, reporting, and position-currency forms where supplied. | Satisfied for approved attribution claims. |
| Position cash flows | Available as bounded row evidence and converted through existing value-basis logic. | Satisfied for current position-return calculation. |
| Position classification | Available through canonical `asset_class`, `sector`, and `country` dimensions. Missing labels are now counted in source-alignment evidence and handled as supportability/degraded attribution evidence downstream. | Satisfied with explicit degraded-state evidence. |
| Benchmark assignment | Available from `lotus-core` benchmark assignment unless explicitly overridden by the request. | Satisfied. |
| Benchmark component weights and returns | Available through stateful benchmark input normalization. | Satisfied. |
| Benchmark classification labels | Available through the index catalog. Missing label records are explicit normalization errors when classification grouping cannot be represented; missing dimension labels are counted as unclassified evidence. | Satisfied with explicit error/degraded behavior. |
| Currency and FX source evidence | Available for current `currency_mode="BOTH"` support when `report_ccy`, position currency, benchmark component currency, and required FX rates are present. | Satisfied for approved currency-attribution claims. |
| Benchmark version | Not currently available from the `lotus-core` contract consumed here. | Source-limited; not promoted as a supported claim. |
| Classification version | Not currently available from the `lotus-core` contract consumed here. | Source-limited; not promoted as a supported claim. |
| Calendar policy | Not currently available from the `lotus-core` contract consumed here. | Source-limited; not promoted as a supported claim. |
| Derivative or short flags | Not currently available from the `lotus-core` contract consumed here. | Source-limited; derivative attribution remains unsupported. |
| Fee, tax, and income breakout | Not currently available from the `lotus-core` contract consumed here. | Source-limited; attribution explains active return from supplied position returns, not source-economic decomposition. |

## Tests Added Or Strengthened

1. `tests/unit/services/test_stateful_attribution_input_service.py`
   - proves source-alignment evidence for complete and partial classification;
   - proves currency source posture and FX-required evidence;
   - proves source-contract limitations are explicit rather than hidden assumptions.
2. `tests/integration/test_attribution_api.py`
   - strengthens stateful attribution endpoint proof so source-normalized attribution still emits
     controlled period status, reason codes, and supportability evidence.

## Validation Evidence

```powershell
python -m ruff check app\services\stateful_attribution_input_service.py app\services\attribution_mode_service.py tests\unit\services\test_stateful_attribution_input_service.py tests\integration\test_attribution_api.py
# All checks passed.

python -m pytest tests\unit\services\test_stateful_attribution_input_service.py tests\integration\test_attribution_api.py -q
# 45 passed.
```

`lotus-core` tests were not required because this slice did not change an upstream source contract.

## Review Decision

Slice 4 is complete for the approved RFC 048 scope. The implementation is intentionally conservative:
it does not create a local fake benchmark-version, classification-version, calendar, derivative, or
fee/tax/income contract. Instead, it preserves those as explicit source limitations while proving
the current source-backed attribution path remains usable, bounded, and degraded-state aware.
