## Metric

Pooled Composite Money-Weighted Return (`POOLED_MONEY_WEIGHTED_RETURN`, `XIRR:v1`).
The calculation pools dated monetary economics across the complete historical
composite population and invokes the existing portfolio MWR solver once.

This implementation supports controlled synthetic supplier qualification. Its
default supplier adapter refuses with `SOURCE_AUTHORITY_UNAVAILABLE`. Actual
source-owner applicability and institutional attestation require separate evidence.

## Endpoint and Mode Coverage

- Submit: `POST /performance/composites/analytics`, returning `202`.
- Poll execution: the accepted response's `poll_path`.
- Read retained result: `GET /performance/composites/analytics/results/{calculation_id}`.
- Select `metric_id=POOLED_MONEY_WEIGHTED_RETURN` and `method=XIRR:v1`.
- Use an explicit positive date interval and ACT/365. ACT/ACT, BUS/252 and custom
  annualization divisors are unsupported by this pooled contract.

The registered compute worker captures inputs under its active job claim, calls
the existing MWR calculation service and publishes the original result under the
same current-claim transaction discipline. Corrections use new calculation IDs.

## Inputs

The request identifies `composite_id`, `calculation_id`, `period_start`,
`period_end`, `reporting_currency`, `return_view`, `source_manifest_id` and
`policy_binding_id`. It also carries the existing `solver`, `calendar` and
`annualization` controls, `fallback_policy`, and optional
`correction_of_calculation_id`.

The trusted supplier reader resolves a `PooledSourceBundle`: complete population
and membership history; source-pinned opening, terminal, entry and exit values;
dated external flows and their lifecycle revisions; explicit flow coverage;
policy applicability; original source bodies and per-source revision/cut/digest
vectors. The HTTP request cannot supply or approve those financial source bodies.

## Upstream Data Sources

The deployment-owned `PooledMonetarySourceReader` first resolves population
identities so member authorization precedes financial source access. It separately
verifies supplier and policy authority before returning pinned monetary data.
The default reader is unavailable. A digest, `COMPLETE` flag, compatibility label
or synthetic qualification label cannot establish source-owner authority.

Performance validates retained identities, coverage, policy elections and source
bindings. It requires every unique declared source page and its original body.
Different suppliers may have different revision and cut identifiers; an admitted
compatibility binding covers the entire selected vector.

## Unit Conventions

- Monetary inputs use exact finite decimal strings, integers or Decimal values;
  binary floating-point source money and booleans are rejected.
- All values and flows must already use the requested reporting currency.
  This contract performs no FX conversion or currency inference.
- Source flows use `PORTFOLIO_IN_POSITIVE`: a contribution into a portfolio is
  positive. Its investor cash flow is negative.
- The existing engine returns percentages. The pooled adapter shifts the decimal
  exponent by two exactly once, publishing `DECIMAL_FRACTION` ratios.
- `0.10` means 10%, or 1,000 basis points. Solver roots and residuals use FLOAT64;
  exact source retention does not imply a high-precision root calculation.

## Variable Dictionary

| Symbol | Meaning |
| --- | --- |
| S, T | Explicit period start and end dates |
| B, E | Pooled opening and terminal monetary values |
| C(d) | Portfolio-sign pooled external or boundary capital flow on date d |
| V(d) | Investor-sign monetary amount on date d after pooling |
| A | Solver anchor date after normalization |
| tau(d) | Actual elapsed calendar days from A to d divided by 365 |
| r | Annual decimal XIRR root within configured bounds |
| NPV(r) | Monetary discounted sum at the solver anchor |
| H | Actual calendar days from S to T |
| w(d) | Modified Dietz remaining-period weight `(T-d).days / H` |

## Methodology and Formulas

Complete membership is evaluated using disjoint inclusive dated segments.
Current membership alone is insufficient. Every expected member has complete
history, including explicit excluded intervals. Pending decisions, overlap and
gaps refuse. Adjacent included segments form one continuous inclusion run.

For each included run, the source supplies its exact boundary valuations.
Opening members contribute to B; terminal members contribute to E. Mid-period
entries and exits become dated boundary capital flows using the admitted boundary
policy. External flows are selected only for included dates. Source-owned active
revisions are deduplicated by namespace, declared identity scope, event identity
and revision. Conflicting active versions or unresolved predecessor chains refuse.

Only explicit reconciled internal pool-transfer pairs may cancel. The transfer
group, counterparties, dates and monetary amounts must reconcile; an unclassified
flow or an unpaired transfer cannot be silently excluded.

Investor signs are constructed as follows, summing all components on the same date:

```text
V(S) += -B
V(d) += -C(d)
V(T) += E
NPV(r) = sum_d V(d) / (1+r)^tau(d)
NPV(r) = 0
```

The existing solver normalizes same-date amounts and removes zero net dates.
Its actual algorithm is reported in convergence diagnostics. A result is
`AVAILABLE` only when the engine calculates XIRR, converges, detects exactly one
root, supports uniqueness within its configured bounds and detects no non-simple
root. This is a qualified bounded result, not a mathematical claim outside those
bounds. Member IRRs are never averaged or used as aggregation weights.

When the independently admitted policy explicitly allows Modified Dietz and the
existing engine uses that fallback, the published disposition is
`FALLBACK_ANALYSIS`, with `actual_method=MODIFIED_DIETZ`. Its measured-period form is:

```text
R_D = (E - B - sum_d C(d)) / (B + sum_d w(d)*C(d))
```

The adapter preserves the existing solver's annualization, approximation,
fallback reason and diagnostics. Under `REQUIRE_XIRR`, fallback values remain
unpublished and the disposition is `NOT_CALCULABLE`.

## Step-by-Step Computation

1. Verify the signed caller and server-resolved capabilities, tenant membership
   and complete portfolio scope. Caller role or capability headers do not grant access.
2. Resolve population identity metadata; authorize every member before financial
   source access. Bind the request in the existing asynchronous submission lifecycle.
3. Under the acquired worker attempt, read an existing immutable input snapshot.
   An identical retry reuses it without upstream financial reads.
4. Otherwise obtain the qualified pinned bundle; require that its population
   equals the scope admitted at submission. Validate coverage, source bodies,
   membership, flow revisions, currency and policy before pooling.
5. Construct exact monetary opening/terminal totals and dated portfolio/investor
   flow vectors. Retain source identities and original bodies in the observation.
6. Bind that observation once inside the active job's locked transaction. A stale
   worker, wrong owner, wrong attempt or expired lease cannot publish inputs.
7. Call the existing MWR service with B, E and C(d), explicit S/T and FLOAT64.
8. Apply the qualified-root or explicit-fallback disposition. Preserve actual
   residual NPV, bounds, convergence and the complete original solver result.
9. Publish the original result under the current claim, matched to its retained
   input manifest. Identical publication replays; conflicting publication refuses.
10. Complete the existing execution and lineage lifecycle. Operational failures
    stay in job/execution records and do not become immutable financial originals.

## Validation and Failure Behavior

| Condition | Behavior |
| --- | --- |
| Unconfigured supplier authority | Submission `409 SOURCE_AUTHORITY_UNAVAILABLE` |
| Missing/invalid signed credential | `401` before financial source access |
| Tenant, capability or member-scope denial | `403` before financial source access |
| Foreign tenant retained identity | `404`, without financial observation disclosure |
| Missing population or flow coverage | Typed refusal; no zero-flow substitution |
| Missing terminal or boundary value | Worker failure; no financial input/result original published |
| Unknown flow classification/date election | Typed refusal; no inferred economic date |
| Mixed currency or incompatible source cut | Typed refusal |
| ACT/ACT or BUS/252 | `METHOD_DATE_BASIS_UNSUPPORTED` |
| Custom year divisor | Request validation refusal |
| No, multiple, non-simple or unqualified root | `NOT_CALCULABLE`, null published return |
| Solver work limit or unsupported numeric projection | `NOT_CALCULABLE`, null published return |
| Explicit admitted Dietz fallback | `FALLBACK_ANALYSIS`, actual method and reason retained |
| Conflicting request/result under retained identity | Custody conflict; original preserved |

Valid mathematical unavailability is a completed analytical dataset with a typed
outcome, rather than an invented zero. Transient operational failure can retry
using already retained inputs. A new financial correction preserves its original
and must bind the same composite, window, reporting currency, return view and method.

Input and financial-result custody currently uses indefinite fail-safe retention.
Governed purge and legal-hold lifecycle acceptance remains open; ordinary operational
retention must not delete these originals. Database guards protect updates,
deletes and PostgreSQL truncation, including cascading removal.

## Configuration Options

`solver` reuses the existing MWR solver model, including rate bounds, scan steps,
tolerance and iteration controls. Its named control method is retained alongside
the algorithm actually executed. `fallback_policy` is `REQUIRE_XIRR` by default;
`ALLOW_MODIFIED_DIETZ` requires matching supplier-resolved policy applicability.
`annualization.basis` is restricted to ACT/365 by this metric. Currency, fee/tax
view, source date basis and boundary-flow treatment come from the matching policy.

## Outputs

The accepted response carries `calculation_id`, metric/method identity,
`poll_path`, `result_path` and retry guidance. The retained dataset contains:

- schema and engine version, composite/calculation identity and correction link;
- `input_manifest_digest` and the full immutable `observation`;
- `outcome.availability`, `actual_method`, `return_value`, `annualized_return`,
  `holding_period_return`, units, reason codes and root precision;
- actual solver diagnostics and `original_solver_result`;
- source qualification and institutional-attestation posture in the retained bundle.

The residual is reporting-currency NPV at the solver anchor using FLOAT64. The
adapter does not invent an independently computed high-precision residual.

## Worked Example

This controlled two-year ACT/365 example runs through the registered API and
worker. Both members are included throughout 2025-01-01 to 2027-01-01.

| Member | Opening value | 2026-01-01 contribution | Terminal value |
| --- | ---: | ---: | ---: |
| A | 100 | 0 | 121 |
| B | 100 | 100 | 220 |
| Pooled | 200 | 100 | 341 |

| Date | Elapsed days | Year fraction | Investor flow |
| --- | ---: | ---: | ---: |
| 2025-01-01 | 0 | 0 | -200 |
| 2026-01-01 | 365 | 1 | -100 |
| 2027-01-01 | 730 | 2 | 341 |

```text
-200 - 100/(1+r) + 341/(1+r)^2 = 0
200*x^2 + 100*x - 341 = 0, where x = 1+r
r = 0.0794735800308331061377877548969028459657461134194723829...
```

The existing FLOAT64 solver publishes `outcome.return_value` approximately
`0.07947358003`, with `outcome.availability=AVAILABLE` and
`outcome.actual_method=XIRR`. The registered test compares it with the independent
Decimal quadratic oracle within `1e-9` in ratio units. Member A's IRR is 0.10;
member B's is approximately 0.06524758425. Their mean, approximately 0.08262379212,
differs from the pooled result by more than 0.003 and is rejected as an aggregation
method. These numbers are synthetic evidence and carry no institutional attestation.
