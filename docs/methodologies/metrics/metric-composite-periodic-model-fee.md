# Composite Periodic Model-Fee Return

## Metric

Issue #609's first convention transforms each verified gross member wealth factor
by an explicitly approved period management-fee fraction, before the existing composite
beginning-asset weighting and linking. This is a calculated `NET_MODEL_FEE` view.
It is neither an actual fee posting nor official composite approval or firm compliance.

## Endpoint and Mode Coverage

`POST /performance/composites/materializations` registers the command; the existing
durable compute worker admits and retains the source and member evidence. Read its
returned `result_path`, then use `POST /performance/composites/twr` for the published
fee-view/currency/sequence scope. The first producer requires a Manage v2 `INTERNAL`
profile with approved native member-return, beginning-asset and ending-asset selections.
External/hybrid methods and provider profiles without an ending-asset selection are
outside this native-receipt convention. Their existing gross/actual-net routes remain.

Model-profile resolution defaults to `UNAVAILABLE`. An operator can configure
`COMPOSITE_MODEL_FEE_SOURCE_MODE=LOCAL_CATALOG` to resolve exact immutable profiles
retained by Performance. Publication preserves unapproved input and original publisher
custody; independent method verification remains unavailable by default. Registered
SQLite/PostgreSQL controls use the actual catalog and frozen synthetic authority ports;
they do not qualify customer approval or institutional activation.
FX-plus-model composition has not received this increment's registered numerical proof.

## Inputs

| Input | Meaning and required custody |
| --- | --- |
| `model_fee_binding` | Exact product/version/revision/content digest; required only for `NET_MODEL_FEE`. |
| `CompositePeriodicModelFeeProfile:v1` | Immutable profile, method and schedule identities/revisions; tenant/composite, exact calendar and effective dates. |
| `periods[].member_rates[]` | Sorted complete attested member universe, unique entry identities and strict decimal-string fee fractions, including explicit zero waivers. |
| Gross member evidence | Original retained stateful TWR request/result identity, reported return, source asset observations and Core retrieval custody. Actual-net inputs refuse. |
| Manage authority | Definition, evaluated membership, universe, source cut and independently verified return-method/calendar approval. |
| Reporting currency/assets | Profile currency matches the command; source assets retain their verified currency and original amounts. |

The profile declares management fees only, already-included transaction costs, unbundled
context, an explicit period wealth fraction and an end-of-complete-period haircut.
No annual rate, annual/12 conversion, day-count prorating, AUM-derived rate or monetary
fee amount is inferred. Full adjacent calendar coverage and exact complete-period
alignment are mandatory. Rate-entry identities are unique across the whole profile.

## Upstream Data Sources

Manage owns definition, membership and economic selections. Core owns the actual
portfolio source money; Performance owns the admitted gross TWR result and this return
transformation. An approved profile supplier must retrieve immutable content by exact
tenant/composite/product/version/revision/digest through the existing return-method
authority. The consumer's source port grants no approval itself. Supplier adoption and
qualified verification remain separate from the synthetic test configuration.

## Unit Conventions

All member, period and cumulative returns and fee fractions are decimal ratios:
`0.02` means 2%; `0.001` means 0.1% of post-return wealth for this complete period.
Assets are currency amounts. Model-return differences are ratios, not cash fee debits.
The transformation uses bounded Decimal arithmetic with no intermediate rounding.
It preserves the retained gross engine's precision policy; it cannot restore precision
already lost upstream. Existing composite output quantization remains unchanged.

## Variable Dictionary

| Symbol | Unit | Definition |
| --- | --- | --- |
| `i`, `t` | identity/index | Eligible member and approved complete period. |
| `g(i,t)` | ratio | Verified retained gross member return. |
| `f(i,t)` | ratio | Approved explicit post-return period fee fraction. |
| `m(i,t)` | ratio | Transformed model-net member return. |
| `B(i,t)` | currency amount | Verified beginning assets used by the existing composite engine. |
| `w(i,t)` | ratio | `B(i,t) / sum_i B(i,t)` across READY eligible members. |
| `R(t)` | ratio | Asset-weighted model-net composite period return. |
| `L(T)` | ratio | Geometrically linked composite return through periods `1..T`. |

## Methodology and Formulas

```text
m(i,t) = (1 + g(i,t)) * (1 - f(i,t)) - 1
w(i,t) = B(i,t) / sum_i B(i,t)
R(t)   = sum_i w(i,t) * m(i,t)
L(T)   = product_t (1 + R(t)) - 1
```

Transform members before weighting: applying a weighted fee to an already aggregated
gross return gives a different answer for heterogeneous returns/rates. Management fees
never become external capital withdrawals. Source assets, flows and actual fees are
unchanged. Already-included transaction costs are not deducted again. Model-net does
not start from actual-net, so it cannot double charge the actual management fee.

The elected wealth-factor haircut is a project method. It is not a universal formula
asserted by GIPS. Standards applicability is explicitly
`NOT_ASSESSED_ENGINEERING_METHOD_ONLY`; actual-fee comparisons and applicable standards
assessment need their own approved evidence before any presentation claim.

## Step-by-Step Computation

1. Decode the command and enforce model-view/binding equivalence. Omitted fee binding
   preserves historical gross/actual-net immutable payloads.
2. Admit the original Manage definition, membership, universe and economic selections.
3. Resolve and hash the exact fee-profile revision; validate its complete calendar,
   currency, effective interval, conventions and exact attested member coverage.
4. Independently verify the return-method/calendar approval against those immutable
   bytes. A caller approval string or eligibility approval alone cannot satisfy this.
5. Pin the original profile once while progress is WAITING, under the worker lease fence.
6. Read each pinned gross result and recheck its request, assets and retrieval custody.
7. Transform its return and retain `composite-member-source.v4`: original gross receipt,
   gross digest/return, exact method binding and approved member rate entry. Recheck both
   layers on each durable transition and read; keep original assets unchanged.
8. Publish through the existing financial scope/publication ledger. Only COMPLETE
   materializations admit the requested composite calculation. Reload/replay uses the
   retained original method, never a latest revision substituted by the resolver.

## Validation and Failure Behavior

| Case | Behavior |
| --- | --- |
| Missing binding or binding on gross/actual-net | Command validation refuses. |
| Missing/unknown profile, unsupported convention, schema or approval | Source admission refuses; no member facts are released. |
| Changed rate/schedule/calendar bytes under old binding | `COMPOSITE_MODEL_FEE_SOURCE_DIGEST_MISMATCH`. |
| Missing native asset authority | `COMPOSITE_MODEL_FEE_NATIVE_ASSET_AUTHORITY_REQUIRED`, before member writes. |
| Partial period, calendar gap/overlap, missing/extra member rates | Complete-calendar/window/member admission refuses. |
| Zero fee | Explicit approved waiver; model return equals the gross input for that entry only. |
| Negative fee/rebate or fee >= 1 | Unsupported model adjustment/rate; refuses. Actual signed fee behavior remains in its existing engine. |
| Nonfinite gross or gross < -1 | Refuses the wealth-factor domain. Gross -1 stays -1 under any supported fee. |
| Actual-net retained calculation | `MEMBER_RETURN_VIEW_NOT_SUPPORTED`; no fabricated model equality. |
| Tampered gross receipt, model return, assets or rate entry | Retained member evidence refuses, including rehashed wrapper tampering. |
| Cross-tenant read/replay | Existing tenant-scoped authority and repository isolation refuse. |

Existing composite readiness, nonpositive aggregate beginning-asset and horizon continuity
guards still apply. No empty population, zero denominator or incomplete horizon becomes
a financial result. Frozen/official publication, maker/checker and reopen selection are
separate #610 acceptance. Flat/tiered/AUM schedules and specialized adjustments stay in
#609's subsequent explicitly indexed increments.

## Configuration Options

This profile exposes explicit approved per-period/member fractions and immutable
identities only. There is no production trust flag, permissive fallback, fee override,
annualization shortcut, or client-controlled verifier. Supported literals select one
complete convention. Customer approval cannot make an unsupported algorithm available.

## Outputs

READY facts retain `return_view=NET_MODEL_FEE`, original source assets, calculation
identity, a distinct v4 source receipt digest and the approved fee-entry custody.
The TWR response's `periods[].return_value` and `periods[].cumulative_return` are ratios.
The method does not emit a cash fee amount, cash movement, adjusted asset valuation,
official selection or claim of actual-versus-model equivalence.

## Worked Example

Independent Fraction oracles in `test_composite_model_fee_returns.py` bind these values.

The same file runs the existing actual-fee portfolio engine on source beginning assets
1000, ending assets 1090 after a signed management-fee posting −10, with no external
cash flow. Gross return is 0.10; actual net is 0.09. An independently specified model
fee fraction 0.001 applied to that gross return produces 0.0989. All three views retain
the source ending assets 1090. The modeled ratio does not become a new posting or an
alternative valuation. This controlled method example does not register or approve a
live three-view supplier publication.

| Member | Beginning assets | Gross | Period fee | Model wealth factor | Model return | Weight |
|---|---:|---:|---:|---:|---:|---:|
| A | 100 | 0.02 | 0.001 | 1.01898 | 0.01898 | 0.25 |
| B | 300 | -0.01 | 0.002 | 0.98802 | -0.01198 | 0.75 |

Output mapping: `periods[0].return_value = 0.25 * 0.01898 + 0.75 * -0.01198 = -0.00424`
(−0.424%). Weighted-gross/weighted-fee transformation instead produces −0.004245625
and is deliberately refused as an implementation shortcut by the numerical control.

For one member across two approved periods, gross returns `0.02`, `-0.01` link to
`0.0098`; model returns `0.01898`, `-0.01198` link to `0.0067726196`.
The gross-minus-model ratio difference is `0.0030273804` and the fee wealth-factor
product is `0.997002`. These arithmetic fixtures do not certify cross-month supplier
publication or institutional applicability.

The registered API/worker fixture uses assets 100/200/300, gross +10%/+5%/−2% and
fee fractions 0.001/0.002/0. Its ideal decimal model returns are 0.0989/0.0479/−0.02;
the test separately verifies exact transformation of the retained reported engine
inputs and the unchanged aggregate output tolerance. See the caller and recovery
instructions in [Composite materialization](../../guides/composite_materialization.md).
