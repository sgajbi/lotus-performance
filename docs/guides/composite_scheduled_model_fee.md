# Calling Scheduled Composite Model Fees

Use `CompositeScheduledModelFeeProfile:v1` when the approved engineering method selects a
nominal annual model wealth rate from original beginning assets. The existing
[periodic fraction product](composite_materialization.md#periodic-model-fee-materialization)
remains available when approval supplies the period fraction directly. The
[scheduled methodology](../methodologies/metrics/metric-composite-scheduled-model-fee.md)
defines the three algorithms, ACT/365 inclusive days, precision and financial boundaries.

This method multiplies post-gross wealth by `1-f`. It does not post an actual cash fee, infer
withdrawals or adjust source assets. Its implied modeled money is `B*(1+g)*f`, not `B*f`.
Preserve `NOT_ASSESSED_ENGINEERING_METHOD_ONLY`; successful publication is
`UNAPPROVED_METHOD_INPUT` and does not establish institutional or customer approval.

## Publish, Materialize and Read

1. Obtain approved native gross return/asset evidence and a matching Manage v2 INTERNAL
   definition, membership, universe and source cut. Default approval/resolution remains unavailable.
2. Construct the complete strict profile with sorted members and adjacent complete periods.
   Select `FLAT_ANNUAL`, `MARGINAL_TIERED` or `WHOLE_AUM_BAND` explicitly; supply the original
   positive beginning reporting assets as each member's `fee_base_amount`.
3. Publish through `POST /performance/composites/model-fee-profiles` using admitted tenant,
   actor, role, service identity and `operations.runtime.manage` capability. Keep the original
   publication receipt and exact product/version/revision/digest binding. Retry preserves the
   original publisher; changed content needs a new immutable revision.
4. Require independent method/calendar approval of that full binding and original profile bytes.
   Configure `LOCAL_CATALOG` only when exact catalog resolution is intended; it grants no trust.
5. Submit `POST /performance/composites/materializations` with `return_view=NET_MODEL_FEE`, the
   exact `model_fee_binding`, source bindings and original member calculation references.
6. Read the returned `result_path`. COMPLETE members retain original gross evidence, original
   assets, approved schedule entries and the derived fraction in `composite-member-source.v5`.
   A BLOCKED result contains reasons; do not synthesize a missing member return or denominator.
7. Call `POST /performance/composites/twr` for the exact fee view, currency and sequence, or
   select explicit chronological COMPLETE materialization IDs for retained-window replay.

## Executed Synthetic Example

[The packaged JSON](../../app/api/examples/composite_scheduled_model_fee.json) contains the actual
registered profile publication request, materialization request/response and a labelled TWR
`periods` response projection. Its UUIDs apply only to the executed fixture database; obtain your
own admitted retained UUIDs before using the request elsewhere. All upstream/approval controls
are synthetic. The source-manifest digest records the execution cut; it is not a customer approval.

The one-day example has three members, original assets `100/200/300` and gross returns
approximately `0.10/0.05/-0.02`. A uses flat annual `0.012`; B uses marginal first `100` at
`0.01` and remaining assets at `0.006`, giving annual `0.008`; C lies at the whole-AUM boundary
`300`, selecting annual `0.006`. The derived fractions are these rates divided by 365.
The worker transforms each gross return before weighting, and the TWR response reconciles
`(100*m(A)+200*m(B)+300*m(C))/600`. Ending source assets remain `110/210/294`.

Internal and external clients consume the same fields and refusals. Parse decimal strings as
Decimal values. Store the complete original request, immutable receipt, source pins and returned
financial values; keep any numeric presentation separately.

## Correction and History

A correction is a new profile revision and separately admitted source/materialization, never an
edit to original bytes. Repeat the original request to reproduce its retained result. Newer catalog
content must not replace its schedule during reopen or replay, and child execution lookup must not
be needed to reconstruct retained original financial evidence.

One complete immutable profile can contain unequal member and period rates. Retained vectors
require that same full binding across windows. A changed revision/digest refuses even when logical
method/schedule IDs agree. There is no cross-profile compatibility rule or automatic latest/official
selection. Effective changes must align to actual approved return-period boundaries. An intraperiod
change needs real subperiod gross returns and assets; do not split or interpolate a monthly return.

## Refusals and Operator Recovery

| Observation | Required response |
| --- | --- |
| Missing approval or resolver | Configure the independently governed adapter; publication alone cannot clear it. |
| Mismatched original asset base or changed schedule/fraction | Repair source/method evidence through a new admitted revision; do not rewrite a retained receipt. |
| Foreign/FX-normalized asset input | Keep this native-only method unavailable; obtain a separately governed composition. |
| Missing/extra members, partial period or calendar gap | Repair complete source coverage; do not drop a member or use a partial denominator. |
| Different full profile binding across windows | Select compatible retained history; no logical-ID shortcut. |
| Unsupported rebate/performance/wrap/tax/average-NAV method | Keep the result unavailable until its own algorithm and authority exist. |
| Runtime schema verification refuses old catalog | Stop workloads and run the matching owner migration; runtime performs no DDL. |

From the matching `lotus-performance` repository root, with its approved isolated database URL
configured, apply the owner before API/worker startup:

```powershell
make migration-apply
```

```bash
make migration-apply
```

Drain workers and capture database plus source/lineage backups first. Require all six verification
checks, then restart. The owner expands only the known catalog product check, preserves retained
rows and guards, refuses unknown schema/dependencies and rolls back late failure. Populated
rollback cannot erase profiles. Keep workloads stopped after failure; use a reviewed forward fix
or an isolated backup restore under the [migration contract](../standards/migration-contract.md).

## Report and Excel Consumption

| API value | Presentation mapping |
| --- | --- |
| `members[].source_evidence.derived_period_fee_fraction` | Original decimal string plus an optional percent display; never replace the approved schedule input. |
| `members[].fact.return_value` | Model-net ratio; multiply by 100 once for percent display. |
| `periods[].return_value`, `cumulative_return` | Authoritative composite return ratios from Performance. |
| Beginning/ending assets and reporting currency | Original source amounts with their declared currency. |
| Gross receipt, full profile binding and source pins | Audit attachment; preserve revision/digest and v5 namespace. |

For Excel, keep the API Decimal string in one cell and its presentation in another. If `B2` contains
an available return string, `=100*NUMBERVALUE(B2,".",",")` projects percent and
`=10000*NUMBERVALUE(B2,".",",")` projects basis points. Excel binary rounding is a display
limitation; keep Performance totals and fingerprints authoritative. Do not recalculate tier selection,
subtract an inferred cash fee, allocate a rounding residual or relabel a model result as actual net.
This consumer mapping does not certify a Report/Render/Archive producer or institutional template.
