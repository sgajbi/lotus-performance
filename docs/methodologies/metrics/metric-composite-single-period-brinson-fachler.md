# Composite Single-Period Brinson–Fachler Attribution

## Metric

`SINGLE_PERIOD_BRINSON_FACHLER` explains the arithmetic difference between one
captured Composite period return and one complete historical benchmark period.
Method `BRINSON_FACHLER_ARITHMETIC_THREE_EFFECT:v1` decomposes that difference into
allocation, selection and interaction using the existing raw BF kernel.
This is calculated analysis. The default historical source and independent BF
purpose authority are unavailable; controlled conformance does not qualify a supplier or institution.

## Endpoint and Mode Coverage

Submit `POST /performance/composites/analytics`. A configured, admitted request
returns `202`, followed by `GET /performance/composites/analytics/results/{calculation_id}`.
The existing durable compute worker owns execution. Public financial arrays and
caller-declared authority are not accepted. One explicit period and captured original
are required; annualization, resampling, linking, factor attribution and geometric
active-return bridges are outside this method. Existing portfolio BF/BHB behavior is unchanged.

## Inputs

The request binds `composite_id`, `candidate_id`, `source_manifest_id`,
`policy_binding_id`, `period_start`, `period_end`, `reporting_currency`, `return_view`
and `precision_mode`. Optional `official_scope_id` plus `official_revision` require
that exact current selection at admission, input binding and publication.
`correction_of_calculation_id` must identify an original in the same verified tenant
and analytical scope; a correction uses a new calculation identity.

The source bundle retains complete member and group observations, expected member,
portfolio-group and benchmark-group universes, historical membership/classification/
benchmark revisions, four source pins, exact pages, original wires and an independently
verified purpose-specific policy. `AttributionApproval.evidence_wire` retains the verified
approval evidence; its digest alone is insufficient original custody.

## Upstream Data Sources

| Input | Owner and required evidence |
| --- | --- |
| Captured original and materializations | Existing Performance immutable candidate/result owners; one READY period and complete retained vector |
| Population and effective membership | Manage-owned historical membership; exact original membership digest and full expected population |
| Member/group and pooled economics | Qualified source-owned actual weights/returns and aggregation reconciliation; no inference from today's holdings |
| Classification | Exact historically effective mapping/version and complete included member/group mapping |
| Benchmark | Exact identity/version, actual group returns/weights, complete expected universe, zero omissions, covering pages and common basis |
| BF policy and approval | Independently configured BF-purpose verifier; source receipts, technical grants and TWR selection approval do not grant this purpose |

Current Core normalization explicitly lacks the historical benchmark and classification
versions needed here. Source binding remains unavailable until those owner contracts
and the aggregation purpose are qualified. Source pin completeness applies to the
full expected universe, not only supplied usable rows. The source reader is an
explicit deployment port, not a new benchmark, classification or financial authority.

## Unit Conventions

All weights and returns are binary64 decimal ratios. `0.068` means 6.8%; an effect
of `0.013` means 1.3 percentage points or 130 basis points. `outcome.units` is
`DECIMAL_RETURN`. Do not reuse portfolio response percentage-point conversion.
`FLOAT64` is the only actual attribution precision; `DECIMAL_STRICT` refuses before
source reads or job registration. Exact original monetary custody remains separate.

## Variable Dictionary

| Symbol | Exact source/response field | Meaning |
| --- | --- | --- |
| m | `members[].portfolio_id` | Included original member |
| g | `groups[].group_id` | Stable historical group identity |
| c_m | `members[].composite_weight` | Original beginning-capital member weight |
| u_mg | `member_groups[].member_weight` | Observed group capital weight within member |
| r_mg | `member_groups[].actual_return` | Actual supplied member/group period return |
| r_m | `members[].actual_return` | Captured original member return |
| wp_g | `groups[].portfolio_weight` | Actual source-owned pooled Composite group weight |
| wb_g | `groups[].benchmark_weight` | Actual benchmark group weight |
| rp_g | `groups[].portfolio_return` | Actual supplied pooled group return |
| rb_g | `groups[].benchmark_return` | Actual benchmark group return |
| P | `outcome.portfolio_return` | Pooled group return, reconciled to captured original |
| B | `outcome.benchmark_return` | Complete benchmark weighted return |
| A_g/S_g/I_g | `outcome.groups[].allocation/selection/interaction` | BF group effects |
| D | `outcome.reconciliation_delta` | Sum of all BF effects minus arithmetic active return |
| epsilon | `source_bundle.policy.tolerance` | Approved absolute ratio tolerance, positive and at most 1e-12 |

## Methodology and Formulas

Source economics must independently reconcile:

```text
sum_m(c_m) = 1
for each included member: sum_g(u_mg) = 1
r_m = sum_g(u_mg * r_mg)
wp_g = sum_m(c_m * u_mg)
wp_g * rp_g = sum_m(c_m * u_mg * r_mg)
sum_g(wp_g) = 1; sum_g(wb_g) = 1
P = sum_g(wp_g * rp_g); B = sum_g(wb_g * rb_g)
P = captured_original.periods[0].return_value
```

Each comparison uses the named policy's epsilon. Actual group returns must be
present; the service never fills a missing return by dividing contribution by weight.
No silent renormalization, omitted-component allocation or member-effect averaging occurs.

The existing `engine/attribution.py::_calculate_single_period_effects` BF branch computes:

```text
A_g = (wp_g - wb_g) * (rb_g - B)
S_g = wb_g * (rp_g - rb_g)
I_g = (wp_g - wb_g) * (rp_g - rb_g)
group_total_g = A_g + S_g + I_g
allocation = sum_g(A_g); selection = sum_g(S_g); interaction = sum_g(I_g)
active_return = P - B
D = allocation + selection + interaction - active_return
```

The separate corrected BHB two-effect convention is not called. No estimator,
quantile interpolation, variance, risk-free rate or annualization applies.

## Step-by-Step Computation

1. Require actual FLOAT64 precision, verified tenant/principal and the complete authorized population before financial reads or submission.
2. Bind one exact READY captured original. Refuse a degraded, blocked, missing or multi-period original and any incompatible basis.
3. Acquire the complete original source bundle and verify its independent BF-purpose approval outside a write transaction.
4. Validate four distinct historical products, exact original wire projections/digests, complete pages, zero omissions, coverage and coherent-cut bindings.
5. Require complete unchanged membership over the period and the same complete positive group universe for every included member and benchmark. Retain approved excluded members without giving them economic weight.
6. Check member/group/source aggregation controls, independently normalized portfolio and benchmark weights, and reconciliation to the captured original. A zero residual alone proves none of these completeness conditions.
7. Revalidate dependencies and bind complete original inputs under the existing acquired job lease. Reuse the existing raw BF kernel on a copy outside that write fence.
8. Bind the complete financial source/policy/approval/original/request into the existing canonical fingerprint service with the governed calculation engine version. Keep this financial identity separate from the earlier request-admission hash.
9. Reverify purpose authority outside the write fence; recheck the exact original/current-selection dependencies within it. Publish once into the existing immutable async-result owner.
10. Replay the retained original input/output without refreshing source or recomputing BF effects. Corrections create another identity and preserve earlier source wires and effects.

## Validation and Failure Behavior

| Condition | Behavior |
| --- | --- |
| Strict unsupported precision | HTTP 422 `ATTRIBUTION_PRECISION_UNSUPPORTED`, before source/job side effects |
| Unconfigured or unqualified historical source | HTTP 503 `SOURCE_AUTHORITY_UNAVAILABLE` |
| BF purpose approval absent | Typed `ATTRIBUTION_PURPOSE_AUTHORITY_UNAVAILABLE`; no published financial result |
| Wrong purpose, digest or independent actor | `ATTRIBUTION_PURPOSE_APPROVAL_CONFLICT` |
| Missing/null/nonfinite/bool actual numbers | Strict model rejection; missing is never an observed zero |
| Missing groups/pages/components or duplicate identities | Typed source-universe/page/identity conflict; no calculation from a supplied subset |
| Equal incomplete portfolio/benchmark weights | Refused independently even if BF residual is zero |
| Zero/negative exposure, off-benchmark group or derivative | Explicit unsupported-convention refusal under the initial policy |
| Observed zero portfolio/benchmark return | Valid when present, finite and all reconciliation controls pass |
| Original or currency/fee/period/policy mismatch | Typed dependency, basis or policy conflict |
| Stale/withdrawn/replaced requested official selection | `OFFICIAL_SELECTION_STALE` at admission, binding or publication |
| Wrong tenant or missing member scope | Authorization denial; no financial source read/result disclosure |
| Different source under an already-bound calculation | Input custody conflict; original is preserved |
| Missing installed table/guard | Read-only schema refusal; runtime cannot repair it |

Zero exposure is an unsupported convention, not a zero-denominator fallback.
Empty alignment is a completeness refusal. Ordinary execution failure lives in
job/execution state; it cannot overwrite an immutable financial original.

## Configuration Options

`install_composite_attribution_deployment` accepts a server-owned source reader
and independent BF-purpose verifier. There is no public installation route.
The policy fixes method, aggregation, period applicability, beginning-capital weights,
arithmetic returns, currency, fee/tax basis and tolerance. Public callers cannot choose
another tolerance, infer FX, elect short/zero/off-benchmark conventions or claim approval.
No global engine-version bump is implied by this additive metric: existing accepted
portfolio methodology and reproducibility semantics remain unchanged.

## Outputs

`CompositeAttributionResponse` retains `qualification=CALCULATED_ANALYSIS`, method,
`calculation_engine_version`, `financial_input_fingerprint`, `calculation_hash`,
`input_manifest_digest`, correction identity and optional exact official-selection pins.
`observation` retains complete source/approval wires, historical versions, expected
universes, observed weight sums and original-P reconciliation. `outcome` retains
every group effect, aggregates, units, actual precision and residual.

Report/Render/Archive consumers must preserve this retained dataset, rather than
calculate effects or substitute current holdings. The response is an immutable
historical analytical original. Later current-use qualification belongs to the
existing result-authority read surface and must match the exact candidate/vector/
revision; reading an old original does not declare it current or official.
Unavailable acquisition/approval outcomes remain typed errors, not zero-valued datasets.

## Worked Example

The [OR17 request and expected dataset](../../examples/composite_attribution_or17.json)
is controlled synthetic evidence. Replace reference IDs with actual authorized retained
objects; the example does not install or qualify a supplier. Registered API tests bind
the same observed source economics to genuine retained synthetic materializations.

| Group | wp_g | wb_g | rp_g | rb_g | A_g | S_g | I_g | Group total |
|---|---|---|---|---|---|---|---|---|
| g1 | 0.6 | 0.5 | 0.10 | 0.08 | 0.0025 | 0.010 | 0.002 | 0.0145 |
| g2 | 0.4 | 0.5 | 0.02 | 0.03 | 0.0025 | -0.005 | 0.001 | -0.0015 |

`P = 0.6*0.10 + 0.4*0.02 = 0.068`; `B = 0.5*0.08 + 0.5*0.03 = 0.055`.
Therefore `outcome.allocation=0.005`, `outcome.selection=0.005`,
`outcome.interaction=0.003`, and `outcome.active_return=0.013`.
The final difference is 6.8% minus 5.5% = 1.3 percentage points, not a relative percent change.
Every group effect and headline uses an absolute 1e-12 oracle tolerance.
Output mapping: each group row maps to `outcome.groups[group_id]`; its A, S, I and total
columns map to `allocation`, `selection`, `interaction` and `total`, respectively.
Deleting g2 must refuse `SOURCE_UNIVERSE_INCOMPLETE`; it must not produce a
reweighted one-group answer or silently allocate a residual.

### Two included members with different group economics

This additional controlled admission/kernel example exercises pooled aggregation with two
economically included members, rather than the one-member OR17 unit fixture. It is rational
reference arithmetic and synthetic software proof, not registered PostgreSQL or supplier approval.

| Member | Composite capital weight | g1 weight / actual return | g2 weight / actual return | g3 weight / actual return | Member return |
| --- | --- | --- | --- | --- | --- |
| member-a | 0.7 | 0.2 / 0.09 | 0.3 / -0.03 | 0.5 / 0.04 | 0.029 |
| member-b | 0.3 | 0.4 / 0.05 | 0.4 / 0.02 | 0.2 / -0.01 | 0.026 |

| Group | Pooled weight | Actual pooled return | Benchmark weight / return | Allocation | Selection | Interaction | Total |
| --- | --- | --- | --- | --- | --- | --- | --- |
| g1 | 0.26 | 93/1300 | 0.3 / 0.04 | -0.00098 | 0.00946153846153846 | -0.00126153846153846 | 0.00722 |
| g2 | 0.33 | -13/1100 | 0.2 / -0.02 | -0.004615 | 0.00163636363636364 | 0.00106363636363636 | -0.001915 |
| g3 | 0.41 | 67/2050 | 0.5 / 0.015 | 0.000045 | 0.00884146341463415 | -0.00159146341463415 | 0.007295 |

For example, the source-supplied g1 weight reconciles to `0.7*0.2 + 0.3*0.4 = 0.26`;
its supplied return reconciles through `0.26*(93/1300) = 0.7*0.2*0.09 + 0.3*0.4*0.05`.
The implementation validates these observations; it does not infer an absent pooled return.
`outcome.portfolio_return=0.0281`, `outcome.benchmark_return=0.0155`,
`outcome.active_return=0.0126`, `outcome.allocation=-0.00555`,
`outcome.selection=233809/11726000` and `outcome.interaction=-209821/117260000`.

The owning unit control independently uses Fraction arithmetic for every group effect and total
at absolute tolerance `1e-12`. It also changes g1 benchmark return to `0.06` (benchmark `0.0215`,
active `0.0066`) and separately supplies actual observed g3 returns of zero for both members and
benchmark (portfolio `0.0147`, benchmark `0.008`, active `0.0067`). Group-order reversal preserves
the effects without mutating source observations; removing any member/group pair refuses
`MEMBER_GROUP_UNIVERSE_INCOMPLETE`. An observed zero is still distinct from a missing return.
