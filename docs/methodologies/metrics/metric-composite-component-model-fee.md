# Composite component periodic model fee

## Metric

`CompositeComponentPeriodicModelFeeProfile:v1` elects one Lotus engineering convention:
explicit nonnegative periodic component fractions on a common post-gross wealth base. A bundle
contains allocated components and never adds another charge. Exact evidence can identify a selected
component already reflected in the original gross return. This convention was selected under
[issue #609](https://github.com/sgajbi/lotus-performance/issues/609); it does not grant institutional
method approval or standards applicability.

## Endpoint and Mode Coverage

The existing model-fee profile POST/GET registers this strict product as unapproved method input.
The existing materialization worker requires a separately admitted complete `CompositeGrossCostSource:v1`,
retains its original wire and independent verification, and emits additive member receipts v6.
Existing TWR and `MODEL_FEE_DRAG` consume those retained facts and original gross pins. Default
financial supplier composition is unavailable. Positive integration controls are synthetic; software
delivery does not establish a production financial supplier. Periodic and scheduled v1 wires,
hashes, original decoders and transforms remain unchanged. See the
[component source guide](../../guides/composite_component_model_fee.md).

`UNBUNDLED`, `BUNDLED` and `WRAP` are presentation context. They do not select a specialized GIPS
correction or prospective-client methodology. The official
[wrap-fee guidance, printed pages 11–12](https://www.gipsstandards.org/wp-content/uploads/2021/09/gs_wrap_fee_portfolios.pdf)
distinguishes prospective wrap presentation and a permitted identified or estimated transaction-cost
correction. This generic component convention does not implement or certify that correction.

## Inputs

| Input | Required meaning |
| --- | --- |
| `gross_return` | Original verified gross member return as a finite Decimal, at least `-1` |
| Profile scope | Exact tenant, composite, reporting currency, immutable method/calendar bindings and effective dates |
| `periods[].member_rates[]` | Explicit member and complete period, original gross-receipt digest and gross-component evidence binding |
| `reference_base` | One exact post-gross wealth reference binding shared by every allocated component |
| `components[]` | Unique component and economic-charge identities, category, fraction, allocation evidence and explicit treatment |
| `bundles[]` | Unique container identity, explicit component identifiers, declared fraction and allocation evidence |
| `gross_evidence` | Exact selected scope/receipt/base and evidence for originally included economic charges |

Supported calculated categories are transaction costs, management/advisory fees, custody fees and
administration fees. Performance-fee crystallization, rebates, indirect fund costs and withholding
taxes remain separate requirements; recognizing their taxonomy does not enable a calculation.
Missing or unknown allocation is refused rather than inferred.

## Upstream Data Sources

The intended upstream inputs are independently admitted immutable method/allocation evidence and
the selected retained gross receipt with authoritative component-inclusion evidence. The pure
helper consumes typed evidence; it does not retrieve, authenticate or approve that evidence.
Caller-supplied binding strings or digests alone cannot establish authority. Source/worker/custody
integration retains and verifies the exact original evidence before any financial fact becomes
READY. The complete selected population is checked before the first READY write. Independent
financial verification binds the whole source payload and producer, separately from method/calendar
approval. Retained replay never fetches a current replacement financial source.

An offset pins both the aggregate gross-component evidence binding and the component's original
source-evidence binding. Matching a transaction-cost category, a historical non-wrap cost or an
unrelated economic charge is insufficient.

## Unit Conventions

All fee inputs are dimensionless complete-period wealth fractions on the same post-gross base.
`0.010` means 1% of that reference wealth. It is not an annual rate, a currency charge, a percentage
of beginning assets or an external cash flow. Reporting currency is part of evidence scope; the
method performs no currency conversion.

Returns use decimal units: `0.01184` is a 1.184% return. The method makes no fee cash posting,
withdrawal, source-asset reduction, annualization or monetary quantization.

## Variable Dictionary

| Symbol | Meaning | Code field or derivation |
| --- | --- | --- |
| `g` | Original gross member return | `gross_return` |
| `c_j` | Approved fraction for economic component `j` | `components[].period_fee_fraction` |
| `C` | Total selected component fraction | `sum_j c_j`; each economic charge appears once |
| `b_k` | Declared fraction for bundle `k` | `bundles[].declared_period_fee_fraction` |
| `A_k` | Explicit component set for bundle `k` | `bundles[].component_ids` |
| `I` | Components explicitly treated as already included with matching evidence | `treatment = ALREADY_INCLUDED_IN_GROSS` |
| `O` | Sum of fractions already included | `sum_(j in I) c_j` |
| `f` | Fraction still to deduct | `C - O` |
| `m` | Calculated model-net return | `(1 + g)(1 - f) - 1` |

## Methodology and Formulas

Every container must reconcile exactly: `b_k = sum_(j in A_k) c_j`. Bundle sets cannot overlap;
containers cannot also be components. Bundled/wrap presentation requires complete allocation of
all selected components. Unbundled presentation carries no containers.

Each component fraction is nonnegative and below one; the total must also satisfy `0 <= C < 1`.
For an included offset, evidence must match the exact economic-charge identity, component identity,
category, fraction, complete period, common base and pinned source. A selected deduction with
evidence that the same economic charge is already included is refused to prevent double charging.

`f = C - O`, followed by the existing periodic transform `m = (1 + g)(1 - f) - 1`.
The container total is a reconciliation control and is not added to `C` again. Component fractions
are summed on their explicitly common reference base; sequential compounding of component haircuts
would be a different convention and is not selected here.

## Step-by-Step Computation

1. Decode the strict profile and evidence. Require complete adjacent profile periods, unique members
   per period, unique entry identities, distinct economic charges and explicit container membership.
2. Select the exact member and complete period from the gross-evidence scope. Compare the full tenant,
   composite, currency, method/calendar, original gross receipt and base against the profile entry.
3. Require the exact pinned aggregate evidence binding and one common component reference base.
4. Enter the existing derived Decimal monetary-arithmetic context. Reconcile every bundle total
   exactly and require the total selected component fraction in the supported domain.
5. Admit each already-included offset against its exact original economic component and source.
   Refuse a category-only or mismatched offset and any attempted repeat deduction.
6. Sum `O`, derive `f`, and call the existing `periodic_model_net_return` once. Return the four
   internal result fields without mutating input profiles, evidence or source assets.

## Validation and Failure Behavior

| Condition | Behavior |
| --- | --- |
| Unknown allocation, missing input, extra field or unsupported component category | Strict model refusal |
| Duplicate component/economic charge, container charge, overlapping containers or unknown member reference | Refusal |
| Inverted/gapped profile calendar, duplicate members or entry identities | Refusal |
| Foreign tenant/composite/member/period/currency, changed method/calendar/receipt/base | Refusal |
| Bundle total differs from exact allocated fractions | ValueError; no tolerance or balancing residual |
| Offset source, economic identity, amount or base differs | ValueError; no category-only matching |
| Same included economic charge selected for another deduction | ValueError; no double charge |
| Negative/nonfinite fraction, individual or total fraction at least one, invalid gross wealth factor | Refusal |
| Explicit zero fractions | Valid zero adjustment with unchanged gross return |

No empty-population, monetary-base denominator, interpolation or estimated allocation calculation
exists in this helper. Missing members or complete periods refuse rather than becoming zero. Decimal
context isolation preserves caller flags/traps and retains coefficients; there is no float fallback.

## Configuration Options

The method is fixed by the new immutable profile product/version and explicit fields. There are no
automatic rate conversions, inferred source identities, model/actual equality assumptions, G5
correction switches or production approval defaults. Existing v1 profiles do not acquire component
semantics by relabeling them. Any new method needs its own approved immutable identity and evidence.

## Outputs

`ComponentModelFeeResult` is an internal pure-helper result, not a registered API response:

| Field | Meaning |
| --- | --- |
| `total_component_fee_fraction` | `C`, each selected economic component counted once |
| `already_included_fee_fraction` | `O`, exact proven components already reflected in gross |
| `deducted_fee_fraction` | `f`, remaining common-base fraction |
| `model_net_return` | `m`, existing periodic wealth-haircut result |

Real source custody, actual fee accounting, negative rebates, performance-fee crystallization,
monetary conversions, annual component schedule composition, specialized wrap guidance and
institutional applicability remain open acceptance requirements under #609.

## Worked Example

The owning rational-oracle tests use synthetic complete-period inputs, not a customer fee policy.
Gross return `g = 0.020`; declared bundle `b = 0.010`:

| Economic component | Fraction | Exact same charge already in selected gross? | Remaining deduction |
|---|---:|---|---:|
| Transaction | 0.002 | Yes, with matching component/source/base/amount evidence | 0 |
| Management/advisory | 0.006 | No | 0.006 |
| Custody | 0.001 | No | 0.001 |
| Administration | 0.001 | No | 0.001 |
| Total | 0.010 | `O = 0.002` | `f = 0.008` |

Output mapping: `m = (1.020 × 0.992) - 1 = 0.01184`, so `model_net_return = 0.01184`.
The independently derived rational expectation is `148 / 12500`.

If the transaction costs already in gross represent a different economic charge, they cannot offset
the model transaction component. Deduct `f = 0.010` once: `m = (1.020 × 0.990) - 1 = 0.00980`, with
independent rational expectation `49 / 5000`. Selecting an offset despite that mismatch refuses.
