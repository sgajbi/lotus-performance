# Composite Model-Fee Drag

## Metric

`MODEL_FEE_DRAG`, method `ADDITIVE_GROSS_MINUS_MODEL:v1`, compares gross and model-net returns
for the same retained financial population. It returns a decimal return difference. It does not
calculate monetary fees, actual-net returns, institutional approval or GIPS qualification.

## Endpoint and Mode Coverage

`POST /performance/composites/analytics` accepts an explicit complete chronological vector of
`NET_MODEL_FEE` materializations. The synchronous result is `CALCULATED_ANALYSIS`, qualified
`RETAINED_SOURCE_ATTESTATION_NOT_LIVE_QUALIFIED`. Periodic and scheduled model-fee receipts are
supported. This operation shares the existing analytics route with dispersion, contribution and
asynchronous pooled MWR; their contracts remain separate.

## Inputs

Required inputs are `metric_id`, `composite_id`, `period_start`, `period_end` and
`materialization_ids` (1–120 identifiers). The view must be `NET_MODEL_FEE`; the only method is
`ADDITIVE_GROSS_MINUS_MODEL:v1`. The inherited selection contract refuses duplicate, reversed,
partial or incompatible vectors. Tenant scope comes from the existing tenant dependency.
No fee schedule override or replacement gross population is accepted.

## Upstream Data Sources

The existing strict materialization store supplies the original immutable model-fee binding,
financial member facts, beginning assets and typed original gross receipts. Gross is reconstructed
from those receipts, rather than resolved from current financial sources. The analysis creates no
new approval ledger or materialization and does not resolve a current fee schedule.

## Unit Conventions

`DECIMAL_RETURN_DIFFERENCE`: multiply by 100 for percentage points or 10,000 for basis points.
Beginning assets retain their original reporting currency and are not reduced by model fees.
The shared engine quantizes returns to 12 decimal places; differences use these returned values.
All financial arithmetic uses Decimal with the existing scoped model-fee context.

## Variable Dictionary

| Symbol | Meaning | Source |
| --- | --- | --- |
| `t` | Retained complete period | Exact requested materialization vector |
| `i` | Selected financial member | Original retained facts |
| `B_i,t` | Beginning reporting-currency assets | Original member fact |
| `w_i,t` | `B_i,t / sum_j B_j,t` | Shared composite engine |
| `g_i,t` | Original gross return | Typed gross receipt |
| `m_i,t` | Model-net return | Original model fact |
| `g_t`, `m_t` | Paired composite period returns | Shared engine applied independently |
| `d_t` | Period drag | `g_t - m_t` |
| `G`, `M` | Independently linked horizon returns | Gross and model period series |
| `D` | Horizon drag | `G - M` |

## Methodology and Formulas

The shared asset-weighted engine computes each stream from identical assets and financial facts:
`g_t = sum_i(w_i,t * g_i,t)` and `m_t = sum_i(w_i,t * m_i,t)`.
`d_t = g_t - m_t`. Separately link `G = product_t(1 + g_t) - 1` and
`M = product_t(1 + m_t) - 1`, then return `D = G - M`.
Horizon drag is not the sum of period differences.

For the supported wealth-haircut source convention, the retained model return was calculated as
`m_i,t = (1 + g_i,t)(1 - f_i,t) - 1`. This analysis uses that retained result; it does not rerun
the haircut from a caller-supplied rate. Transaction costs already present in gross are not deducted again.

## Step-by-Step Computation

1. Select the exact tenant-scoped complete model vector using existing selection rules.
2. Require the same complete immutable model-fee binding on every record.
3. Read model facts and reconstruct paired gross facts from original typed receipts, preserving assets and identities.
4. Run both streams through the shared composite engine and scoped Decimal context.
5. Require both calculations READY with cumulative values; pair exact period boundaries and member counts.
6. Subtract period values and independently linked horizon values. Return original gross/model source pins,
   full method binding, selection manifest and value fingerprint.

## Validation and Failure Behavior

| Condition | Behavior |
| --- | --- |
| Missing or foreign-tenant record | Tenant-safe HTTP 404 |
| Invalid view, method, extra fields or malformed vector | HTTP 422; no financial result |
| Changed method binding or incompatible horizon | Existing selection refusal, HTTP 422 |
| Missing typed gross receipt | `COMPOSITE_FEE_DRAG_GROSS_RECEIPT_REQUIRED` |
| Incomplete calculation | `COMPOSITE_FEE_DRAG_POPULATION_UNAVAILABLE` |
| Different period boundaries/counts or missing period return | `COMPOSITE_FEE_DRAG_POPULATION_MISMATCH` |
| Decimal execution failure | `COMPOSITE_FEE_DRAG_PRECISION_REFUSED`; no float fallback |

Counts describe selected financial facts processed by the engine. An excluded materialization
outcome without a financial fact is not converted into an invented zero-return fact. Both streams
use the same retained population; these counts do not certify the full Manage eligibility universe.
Restore original immutable evidence through governed recovery; do not rewrite historical receipts.

## Configuration Options

There are no metric-specific runtime switches or caller fee overrides. Original periodic or
scheduled method evidence determines calculation context. Configured receipt verification remains
independent and defaults to unavailable; a method-only verifier cannot admit missing policy,
evaluation, finalization or financial-source evidence.

## Outputs

The response includes cumulative gross return, model-net return and drag; paired period rows;
six source pins in the worked example; full `model_fee_binding`; and a selection manifest with
engine version, original windows and calculation fingerprint. An explicit zero model fee produces
zero drag. Negative rebates, performance-fee crystallization, actual fees and whole-cost component
source admission are not supplied by this metric.

## Worked Example

The complete [packaged HTTP example](../../../app/api/examples/composite_fee_drag.json) is captured
from the registered route using synthetic retained inputs. Its request and entire success/error
responses are checked against fresh execution without replacing receipt hashes.

Both one-day periods use beginning USD assets A=100, B=200 and C=300, with original gross returns
0.10, 0.05 and -0.02. Weights are respectively 1/6, 1/3 and 1/2; thus gross is
`(100*0.10 + 200*0.05 + 300*(-0.02))/600 = 0.023333333333` after output quantization.
Nominal annual wealth rates on January 5 are A=0.012, B=0.008, C=0.006; on January 6 they are
A=0.02, B=0.01, C=0.004. Each period fraction is the annual rate divided by 365.

| Period | Members | Gross return | Model-net return | Drag |
|---|---:|---:|---:|---:|
| 2026-01-05 | 3 | 0.023333333333 | 0.023311579909 | 0.000021753424 |
| 2026-01-06 | 3 | 0.023333333333 | 0.023308328767 | 0.000025004566 |
| Independently linked horizon | 3 per period | 0.047211111111 | 0.047163262644 | 0.000047848467 |

The horizon difference is 0.47848467 basis points. Summing the period differences would give
0.000046757990, which is not the horizon result. Synthetic authority fixtures prove engineering
behavior only; this example establishes no bank or external supplier qualification.
Output mapping: the horizon row maps to `cumulative_gross_return`, `cumulative_model_net_return` and
`cumulative_fee_drag`; each period row maps to `periods[].gross_return`, `model_net_return` and `fee_drag`.
