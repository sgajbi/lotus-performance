# Composite Scheduled Model-Fee Return

## Metric

`CompositeScheduledModelFeeProfile:v1` derives an approved period model wealth fraction from
an explicit annual rate and verified beginning assets, then reuses the existing gross-to-model-net
wealth transformation and composite engine. It produces `NET_MODEL_FEE`. The method is an elected
engineering convention, with `NOT_ASSESSED_ENGINEERING_METHOD_ONLY` standards applicability.
It does not calculate actual cash fee postings or establish institutional approval.
The original [periodic fraction method](metric-composite-periodic-model-fee.md) remains a separate
unchanged product; an annual rate cannot be submitted as its explicit period fraction.

## Endpoint and Mode Coverage

Publish through `POST /performance/composites/model-fee-profiles`; retain the returned full binding.
Submit that binding to `POST /performance/composites/materializations` with `NET_MODEL_FEE`,
then read its `result_path`. COMPLETE receipts support the existing composite calculation routes.
Profile publication is `UNAPPROVED_METHOD_INPUT`, independently of successful storage.

This convention requires an admitted Manage v2 INTERNAL profile, original gross stateful member
receipts, verified native reporting-currency assets and independent return-method/calendar approval.
FX-normalized source assets refuse for this product. External/hybrid, actual-net and inferred
asset conversions are outside this increment. Default source resolution and method verification
remain unavailable; controlled SQLite/PostgreSQL proofs use explicitly synthetic authority ports.

## Inputs

| Input | Required meaning |
|---|---|
| `model_fee_binding` | Exact scheduled product/version/revision/full content digest, also bound by the Manage definition. |
| Profile identity | Immutable tenant/composite, profile, method and schedule identities/revisions. |
| `calendar_binding`, effective dates | Approved complete adjacent periods covering the exact effective interval. |
| `periods[].member_rates[]` | Sorted complete expected-member entries; globally unique entry identities. |
| `fee_base_amount` | Strict positive Decimal string equal to original verified beginning reporting assets. |
| `schedule_rule` | Explicit `FLAT_ANNUAL`, `MARGINAL_TIERED` or `WHOLE_AUM_BAND` and annual model wealth rate(s). |
| Original gross evidence | Pinned return, request/result identity, source observations and retrieval custody. |

The caller does not supply `derived_period_fee_fraction`. Every banded schedule must cover zero
through an unbounded final band (`upper_bound: null`), without gaps or overlap. Bounds are lower inclusive and upper
exclusive. At most 64 bands, 128 periods and 1,000 members per period are admitted. Input decimal
strings are finite and bounded to 80 characters. Each annual rate is in `[0,1)`.

## Upstream Data Sources

Manage owns definitions, membership, universe and economic selections. Core owns original source
money; Performance owns admitted gross returns and the model transformation. Profile custody in
Performance does not grant method approval. The independent approval port receives the complete
immutable profile and its binding, original source scope and exact period/calendar authority.
Eligibility approval, a valid hash or a caller approval flag cannot replace this verification.

## Unit Conventions

Rates, fee fractions and returns are Decimal ratios: `0.012` is a nominal annual 1.2% model
wealth rate. Assets and implied modeled charges have the profile's reporting-currency unit.
The divisor is always 365, including leap years. Actual accrual days include both period endpoints.
This is nominal ACT/365 fixed prorating, not annual/12 or effective annual compounding.

Rate derivation uses a fresh half-even Decimal context, precision at least 80 with bounded
input-dependent expansion, explicit exponent bounds and explicit arithmetic traps. Caller precision,
rounding, flags and traps cannot select the rate calculation. Quotients may round under this
declared ratio policy; there is no monetary quantization or inferred currency-minor-unit cash fee.
Original gross precision remains authoritative. Composite return output retains its existing
`0.000000000001` quantum and assets its `0.000001` quantum.

## Variable Dictionary

| Symbol | Unit | Definition |
|---|---|---|
| `i`, `t`, `j` | index | Member, complete period and ascending band. |
| `B(i,t)` | currency amount | Original verified positive beginning assets; rate-selection base and existing composite weight base. |
| `g(i,t)` | ratio | Original verified gross member return. |
| `d(t)` | days | Inclusive actual calendar-day count of the complete period. |
| `l(j)`, `u(j)` | currency amount | Lower and upper band bounds; final upper bound is unbounded. |
| `r(j)` | annual ratio | Approved nominal annual model wealth rate for a band, or the flat rate. |
| `q(j,B)` | currency amount | Assets occupying marginal tranche `j`. |
| `a(B)` | annual ratio | Selected or marginally blended annual model wealth rate. |
| `f(i,t)` | period ratio | Derived fraction of post-gross wealth, required in `[0,1)`. |
| `m(i,t)` | ratio | Model-net member return. |
| `C(i,t)` | currency amount | Implied modeled charge, an explanation rather than a cash posting. |
| `w(i,t)` | ratio | Original beginning-assets weight among READY members. |
| `R(t)`, `L(T)` | ratio | Composite period and cumulative model-net returns. |

## Methodology and Formulas

```text
FLAT_ANNUAL:     a(B) = r
MARGINAL_TIERED: q(j,B) = max(0, min(B,u(j)) - l(j))
                a(B) = sum_j q(j,B)*r(j) / B
WHOLE_AUM_BAND:  a(B) = r(j), for the unique l(j) <= B < u(j)
d(t) = period_end - period_start + 1 calendar day
f(i,t) = a(B(i,t)) * d(t) / 365
m(i,t) = (1 + g(i,t)) * (1 - f(i,t)) - 1
C(i,t) = B(i,t) * (1 + g(i,t)) * f(i,t)
w(i,t) = B(i,t) / sum_i B(i,t)
R(t) = sum_i w(i,t)*m(i,t)
L(T) = product_t (1 + R(t)) - 1
```

For the unbounded marginal band, `min(B,u(j))` means `B`. In a whole-AUM schedule, the
selected rate applies to all post-gross wealth; in a marginal schedule, tranche rates determine
the blended annual rate. These conventions differ at band boundaries and are never inferred.

`C` is distinct from a fixed beginning-assets cash fee `B*f`. Subtracting that fixed cash amount
would yield `g-f`; this elected wealth method yields `g-(1+g)*f`. No withdrawal, actual fee credit,
cash flow or new asset value is manufactured. Management fees never become external capital
withdrawals. Transaction costs already included in gross are not deducted again.

## Step-by-Step Computation

1. Admit the command's view/binding, original Manage scope and native asset selections.
2. Resolve the exact immutable profile; strictly decode its product, literals, calendar and members.
3. Recompute its full digest and require the exact Manage method binding and reporting currency.
4. Derive all selected-period fractions and refuse non-executable rates before member release.
5. Independently verify the method/calendar approval against the complete original profile.
6. Read and verify each original gross receipt, return, beginning/ending assets and source custody.
7. Require the schedule entry's beginning asset base to equal that member's original beginning assets.
8. Derive the fraction, transform gross wealth and retain `composite-member-source.v5`: original
   gross evidence/digest/return, full method binding, original schedule entry and derived fraction.
9. Rederive and compare that fraction, transformed return and receipt fingerprint on every durable
   transition/read. Preserve original assets and flows. Publish through the existing worker ledger.
10. Calculate with the existing composite engine. Replay uses retained original bytes, without
    resolving latest profiles or requiring child execution lookup to recreate financial evidence.

## Validation and Failure Behavior

| Case | Behavior |
|---|---|
| Missing/unknown profile, convention or schema | Refusal before financial facts; no inferred defaults. |
| Default/unavailable or nonboolean approval | `COMPOSITE_MODEL_FEE_METHOD_APPROVAL_UNAVAILABLE`. |
| Changed bytes under old full binding | `COMPOSITE_MODEL_FEE_SOURCE_DIGEST_MISMATCH`. |
| Fully rehashed but unapproved rate/base/schedule/calendar | Independent method approval refuses. |
| Missing required beginning/ending asset authority | `COMPOSITE_MODEL_FEE_NATIVE_ASSET_AUTHORITY_REQUIRED`. |
| FX normalization wire for scheduled method | `COMPOSITE_SCHEDULED_MODEL_FEE_NATIVE_ASSETS_REQUIRED`. |
| Derived fraction outside `[0,1)` | `COMPOSITE_SCHEDULED_MODEL_FEE_RATE_NOT_EXECUTABLE`. |
| Nonpositive/mismatched base, altered fraction/entry/gross receipt/namespace | Schema or `COMPOSITE_MODEL_FEE_MEMBER_EVIDENCE_REFUSED`. |
| Missing/extra member or partial period | Exact member/complete-period admission refuses; no member is dropped to repair the denominator. |
| Gaps/overlap or intraperiod schedule change | Schema/period admission refuses; actual separately retained subperiod economics are required. |
| Changed full profile binding across retained windows | `COMPOSITE_VECTOR_METHOD_MISMATCH`; logical method ID is insufficient. |

Explicit zero rates are approved waivers. Gross total loss can yield model-net total loss without
inventing a cash fee. Negative rebates, performance fees, bundled/wrap/tax adjustments, average or
daily-changing NAV, cross-profile compatibility and FX-plus-schedule composition remain separate
methods. Empty alignment and nonpositive composite denominators retain existing engine refusals.

## Configuration Options

The strict product declares `AUM_SELECTED_NOMINAL_ANNUAL_MODEL_WEALTH_RATE`,
`ACT_365_FIXED_INCLUSIVE`, `COMPLETE_RETURN_PERIOD`,
`VERIFIED_BEGINNING_REPORTING_ASSETS_RATE_SELECTION_ONLY`,
`POST_GROSS_WEALTH_FRACTION_NOT_FIXED_CASH_FEE` and
`DECIMAL_MIN_80_DERIVED_RATIO_NO_MONETARY_QUANTIZATION`.
Management-only, unbundled, already-in-gross transaction costs and unchanged source assets remain
mandatory shared literals. Source mode `LOCAL_CATALOG` enables exact resolution, not approval.

Owner `make migration-apply` expands only the known catalog product check. PostgreSQL changes
the check transactionally; SQLite replaces the exact table and restores verified immutable guards.
Retained JSON, digest, publisher, tenant and identity remain unchanged. Unknown shape/dependencies
refuse before mutation, late failures roll back, and runtime verification performs no DDL.
Populated catalog rollback refuses destruction; use a reviewed forward correction or isolated
backup restore. Apply from the matching repository revision with workloads drained and all six
durable schema verification checks required before restart.

## Outputs

The materialization inspection returns original schedule inputs and
`members[].source_evidence.derived_period_fee_fraction`, the original gross receipt and the
transformed `members[].fact.return_value`. The fact snapshot fingerprint binds the v5 namespace.
The TWR response exposes `periods[].return_value`, `periods[].cumulative_return`, original assets,
weights/contributions and source pins. Fraction/return fields are ratios, not currency charges.
The API does not post `C` or output a modeled cash ledger.

## Worked Example

For a synthetic complete January (31 days), `B=100000`, `g=0.02`:

| Rule | Annual rate `a(B)` | Period fraction `f` | Model return `m` | Implied modeled money `C` |
|---|---|---|---|---|
| Flat annual `0.012` | `0.012` | `93/91250` | `86507/4562500` (about `0.01896043835616438`) | About `103.95616438356` |
| Marginal first `50000` at `0.01`, remainder at `0.006` | `0.008` | `31/45625` | `22022/1140625` (about `0.01930695890410959`) | About `69.30410958904` |
| Whole-AUM boundary `100000`, lower rate `0.01`, upper rate `0.006` | `0.006` | `93/182500` | About `0.01948021917808219` | About `51.97808219178` |

The flat case's fixed beginning-assets amount would instead be about `101.91780821918` and
produce `g-f`, about `0.01898082191780822`. It is not the elected modeled charge or return.
The one-member output mapping is `R=m`, exposed as `periods[].return_value` after the existing
output quantum. For multiple members, weight each transformed return by its original beginning
assets before geometric linking. Do not weight annual rates and apply them to an aggregate gross return.

The registered synthetic one-day worker control uses A/B/C original assets `100/200/300`,
gross returns approximately `0.10/0.05/-0.02`, and annual rates `0.012/0.008/0.006` from the three
algorithms. It verifies `R=(100*m(A)+200*m(B)+300*m(C))/600` against the actual TWR response,
preserves ending assets `110/210/294`, and proves original v5 custody/reopen/pinned replay and
foreign-tenant refusal. Independent Fraction controls cover the January cases, thresholds,
leap-year inclusive days, zero and invalid fractions; PostgreSQL controls exercise the real catalog
upgrade and registered worker. These fixtures establish bounded engineering behavior, not live
provider qualification, official selection, applicable standards or whole-bank readiness.
