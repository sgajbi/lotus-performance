# Composite Linked Member Contribution

## Metric

`LINKED_MEMBER_CONTRIBUTION` explains a calculated Composite's cumulative time-weighted return by stable portfolio identity across an explicitly pinned period vector. The registered method is `CARINO:v1`. It applies the existing Carino factor to original retained Decimal member returns and beginning assets, rather than linking rounded public contribution literals.

The result is `CALCULATED_ANALYSIS` with `RETAINED_SOURCE_ATTESTATION_NOT_LIVE_QUALIFIED`. It does not establish official generation selection, institutional methodology approval, GIPS compliance, or enterprise readiness. Official selection and freeze remain separately governed by #610. This bounded method implements multi-period member contribution; rankings, classified rollups, annualized transforms, attribution and Composite MWR are outside this method.

## Endpoint and Mode Coverage

Call `POST /performance/composites/analytics` with admitted `X-Tenant-Id`, `metric_id=LINKED_MEMBER_CONTRIBUTION` and `method=CARINO:v1`. The existing annual dispersion request and response remain a separately selected metric on this operation. Existing `POST /performance/composites/twr` and its per-period member contribution contract remain unchanged.

| Mode | Behavior |
| --- | --- |
| Exact retained calculated member facts | Supported after existing COMPLETE vector admission |
| Authoritative entry, exit or exclusion | Supported through the retained historical membership; only participating READY facts receive rows |
| Missing period or required member evidence | Refused; no zero-filled economics or reduced universe |
| Imported Composite-only return or caller override | No constituent decomposition is derived; this request cannot inject an override |
| Latest, official, approved or frozen generation selection | Not supplied by this method |
| Legacy portfolio Carino fallback | Preserved for portfolio callers; not inherited by Composite analysis |

## Inputs

The caller supplies `composite_id`, inclusive `period_start` and `period_end`, `return_view`, optional `reporting_currency`, `calculation_id`, and 1–120 distinct chronological `materialization_ids`. `restatement_sequence` cannot be combined with the vector. Omitting currency uses the first selected retained command's currency; explicit currency is preferable for audit and consumer integration.

Each selected receipt must be tenant-owned and COMPLETE. The existing retained read-side admits exact contiguous windows, composite, fee view, currency, calculation method, policy and source method authority. Original retained outcomes provide `portfolio_id`, Decimal `return_value`, `beginning_market_value`, source snapshot/fingerprint and correction identity. Authoritative ending assets remain an existing admission requirement, although they are not a Carino weight input.

## Upstream Data Sources

The operation reuses `select_composite_materialization_facts` from the existing Composite calculation service and the existing materialization repository. It adds no source fetch, scheduler, financial ledger or independently retained calculation engine.

Manage owns the effective universe and membership and evaluated approval dependencies; existing source adapters own admitted member facts, source cuts and fee identity. Retained `definition_content_hash`, `membership_content_hash`, `attestation_content_hash`, `source_cut_id`, `method_binding` and `retained_receipt_fingerprint` identify the selected evidence. See the [client guide](../../guides/composite_linked_contribution.md) for the replay dependency diagram.

Synthetic authority packets in acceptance tests prove the calculated mechanics and retained custody only. They do not certify live Manage/Core authority or official publication. Report, Render and Archive consume the Performance dataset; this method does not implement their producers.

## Unit Conventions

All returns, weights and contributions are dimensionless Decimal ratios. The response declares `units=DECIMAL_RETURN`. A contribution of `0.025` is 2.5 percentage points or 250 basis points of return contribution, not money. Presentation converts a Decimal contribution `x` to `100*x` percentage points or `10000*x` basis points. Beginning market value is money in the single admitted `reporting_currency`.

`weight` and `linking_factor` are dimensionless. `reconciliation_difference` and `display_rounding_difference` retain decimal-return units. Do not label the latter as financial P&L, an authority adjustment, or a member contribution.

## Variable Dictionary

| Symbol | Definition | Response/source mapping |
| --- | --- | --- |
| `t` | Selected chronological period | `selection_manifest.windows` |
| `i` | Stable participating portfolio identity | `portfolio_id` |
| `I_t` | READY member set admitted for period `t` | Retained outcome facts |
| `a_i,t` | Member beginning market value | `periods[].beginning_market_value` |
| `A_t` | Sum of beginning market values over `I_t` | Computed denominator |
| `r_i,t` | Original retained member Decimal return | `periods[].return_value` |
| `w_i,t` | `a_i,t/A_t` | `periods[].weight` |
| `c_i,t` | `r_i,t*a_i,t/A_t` | `periods[].contribution` |
| `r_t` | Sum of member period contributions | Computed Composite period return |
| `R` | Geometrically linked Composite return | `cumulative_return` |
| `k(r)` | Continuous Carino factor | Existing strict Decimal factor helper |
| `K` | `k(R)` | Computed cumulative factor |
| `f_t` | `k(r_t)/K` | `periods[].linking_factor` |
| `l_i,t` | `c_i,t*f_t` | `periods[].linked_contribution` |
| `L_i` | Sum of `l_i,t` for identity `i` | `members[].linked_contribution` |
| `L` | Sum of all `L_i` | `total_linked_contribution` |
| `d` | `L-R` | `reconciliation_difference` |
| `q(x)` | Decimal quantization to `0.000000000001` | Existing Composite return quantum |
| `d_display` | `sum_i q(L_i)-q(R)` | `display_rounding_difference` |

## Methodology and Formulas

For every admitted period:

```text
A_t = sum_i a_i,t
w_i,t = a_i,t / A_t
c_i,t = r_i,t * a_i,t / A_t
r_t = sum_i c_i,t
R = product_t (1 + r_t) - 1
k(r) = ln(1 + r) / r, for nonzero r > -1
k(0) = 1
f_t = k(r_t) / k(R)
l_i,t = c_i,t * f_t
L_i = sum_t l_i,t
L = sum_i L_i
```

Only admitted participating periods enter a member's sum; absence is not represented by a fabricated row. Historical membership can therefore change between periods without requiring every member to exist throughout the entire vector.

The Carino identity gives `sum_t r_t*k(r_t)=sum_t ln(1+r_t)=ln(1+R)` and hence `L=R` within the calculation precision. No residual is allocated to any member to force this equality.

Calculation uses a local Decimal context with 80 significant digits. For `abs(r)<=1e-12`, the strict Decimal helper evaluates the continuous expansion:

```text
k(r) = 1 - r/2 + r^2/3 - r^3/4 + r^4/5 - r^5/6
```

This includes exact zero and preserves the near-zero correction rather than substituting the legacy portfolio factor `1`. The omitted term is below `1e-72` in this interval. Period growth must remain strictly positive. Cumulative cancellation and precision are assessed using the cumulative factor and the unrounded reconciliation difference; `abs(d)>1e-60` refuses the result. Display projection uses the existing return quantum only to calculate `d_display`; it is never fed back into weights or linking.

There is no annualization, interpolation, benchmark subtraction or currency conversion in this linking method. Currency-normalized facts, when admitted, already carry their existing retained normalization authority.

## Step-by-Step Computation

1. Admit the tenant header and typed metric/method request.
2. Read exactly the selected retained receipts. Reject duplicate IDs, noncanonical order, gaps, overlaps, incomplete receipts and incompatible scope or method authority.
3. Run existing asset-weighted Composite admission over original facts. If its aggregate is not READY, refuse constituent decomposition.
4. For each retained window, sort READY facts by portfolio identity, compute `A_t`, `c_i,t` and `r_t` from retained Decimal returns and beginning assets, and validate the strict Carino domain.
5. Geometrically link `r_t` to obtain `R`; calculate `K`, final `f_t` and every `l_i,t`.
6. Sum by stable identity and count each identity's participating periods. Sort member totals by identity; retain chronological period rows.
7. Assess `d`, calculate the independent display projection difference, and refuse failed precision reconciliation.
8. Return the calculated dataset and selection manifest. Bind tenant, full request, financial result, retained windows and engine version in `selection_manifest.calculation_fingerprint`.

## Validation and Failure Behavior

| Condition | Behavior |
| --- | --- |
| Absent or malformed tenant authority | Existing Composite 401/400 error; no default tenant |
| Receipt absent from admitted tenant | 404; no cross-tenant evidence disclosure |
| Missing middle/final window, incomplete receipt or missing required member facts | 409, including `REQUIRED_PERIOD_UNAVAILABLE`; no partial linked result |
| Duplicate IDs, reversed order, overlap, invalid bounds or unsupported metric/method | 422 typed request or retained-vector refusal |
| Mixed composite, fee view or reporting currency | 422 `COMPOSITE_VECTOR_SCOPE_MISMATCH` or existing currency authority refusal |
| Incompatible retained calculation method/policy | 422 `COMPOSITE_VECTOR_METHOD_MISMATCH` |
| Retained method authority absent | 422 `COMPOSITE_VECTOR_METHOD_UNAVAILABLE` |
| Non-READY Composite admission | 422 `COMPOSITE_CONSTITUENT_DECOMPOSITION_UNAVAILABLE` |
| Nonfinite period return or period return at/below -100% reaching strict linking | 422 `COMPOSITE_CARINO_LOG_DOMAIN_REFUSED` |
| Invalid cumulative factor or reconciliation outside precision bound | 422 `COMPOSITE_CARINO_PRECISION_REFUSED` |
| Below-domain source rejected earlier by materialization | Existing unavailable receipt refusal, commonly 409; the analysis does not bypass it |

Zero return is a valid number. Missing facts are not zero. Authoritative exclusion or absence is a historical membership fact; missing an expected member observation is a source failure. Imported Composite-only or override returns cannot justify member decomposition; this operation accepts no caller economics or residual recipient. Existing retained evidence integrity failures remain governed by the retained read-side, with no partial success payload.

## Configuration Options

The caller selects only the named metric, `CARINO:v1`, exact retained vector and scope. The window limit, precision, near-zero threshold, reconciliation threshold and display quantum are registered implementation behavior, not caller-adjustable policies. `GROSS`, `NET_ACTUAL` and `NET_MODEL_FEE` follow existing retained fee admission. Model-net vectors require one identical complete immutable method/profile binding across all windows. That profile can contain unequal member and period rates. A changed revision or digest is incompatible even when logical method and schedule IDs match; cross-profile history requires a separately governed compatibility relation. Linked analysis adds no fee authority or fee calculation.

## Outputs

The typed `CompositeLinkedContributionResponse` includes the scope, `calculation_id`, method, units, status, qualification and `constituent_decomposition=AVAILABLE`. `members` gives sorted linked totals and `participating_period_count`. `periods` gives original member economics, raw and linked contributions, final linking factors, source snapshot/fingerprint, member calculation ID and restatement version/sequence.

`selection_manifest` declares `EXPLICIT_RETAINED_CALCULATED_REPLAY`, retained window pins, `engine_version` and `calculation_fingerprint`. Keep both row evidence and the manifest. Decimal values serialize as strings; consumer binary floats are not an authoritative recalculation.

## Worked Example

OR13 uses two synthetic periods with Composite returns `0.01` and `0.02`. In each period A and B have beginning assets of `100`, so both weights are `0.5`. The returns and contributions below are original unrounded inputs, not values recovered from rounded TWR responses.

| Period | Member | Beginning assets | Member return | Weight | `c_i,t` | `r_t` |
|---|---|---|---|---|---|---|
| 1 | A | 100 | 0.05 | 0.5 | 0.025 | 0.01 |
| 1 | B | 100 | -0.03 | 0.5 | -0.015 | 0.01 |
| 2 | A | 100 | 0.01 | 0.5 | 0.005 | 0.02 |
| 2 | B | 100 | 0.03 | 0.5 | 0.015 | 0.02 |

`R=(1.01*1.02)-1=0.0302`. Intermediate raw factors are `k(0.01)=ln(1.01)/0.01`, `k(0.02)=ln(1.02)/0.02` and `K=ln(1.0302)/0.0302`; response row factors are these period factors divided by `K`.

| Intermediate | Independent Decimal/log value, shortened for display |
| --- | --- |
| `k(0.01)` | `0.995033085316808284821535754426` |
| `k(0.02)` | `0.990131364808985651301453344255` |
| `K` | `0.985197289713503174643855113555` |
| `f_1` | `1.009983579640343279923485410030` |
| `f_2` | `1.005008210179828360038257294985` |

| Response identity/field | Independent original OR13 decimal-return control |
| --- | --- |
| A `members[].linked_contribution` | `0.030274630541907723798278421725685604316257567000362` |
| B `members[].linked_contribution` | `-0.000074630541907723798278421725685604316257567000360925` |
| `cumulative_return` | `0.0302` |
| `total_linked_contribution` | `0.0302` within absolute `1e-12` |
| Each `participating_period_count` | `2` |

The aggregation is `L_A=0.025*f_1+0.005*f_2` and `L_B=-0.015*f_1+0.015*f_2`. The original controls are finite Decimal reference literals; the implementation returns longer precision values that must agree within the original absolute tolerance. At the display quantum, `q(L_A)=0.030274630542` and `q(L_B)=-0.000074630542`, so this fixture's `display_rounding_difference` is zero. Other member populations can have a nonzero display difference without an economic residual.

The independent Decimal/log reference and original controls live in `tests/composite_linked_contribution_helpers.py`; registered source-retention, correction and refusal cases live in `tests/integration/test_composite_linked_contribution_api.py`. The strict-factor edge controls live in `tests/unit/engine/test_composite_carino_factors.py`. See the client guide for correction/replay and consumer acceptance instructions.
