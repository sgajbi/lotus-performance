# Calling Annual Composite Dispersion

Use `POST /performance/composites/analytics` with `X-Tenant-Id` and a JSON body. This operation reads existing monthly materializations; obtain their exact UUIDs from the governed monthly materialization workflow described in [Composite Materialization](composite_materialization.md).

| Request field | Selection |
| --- | --- |
| `metric_id` | `ANNUAL_MEMBER_DISPERSION` |
| `composite_id` | Same composite on all twelve receipts |
| `year` | Complete calendar year |
| `return_view` | `GROSS` or `NET_ACTUAL` |
| `reporting_currency` | Same evidenced reporting currency throughout |
| `method` | `EQUAL_WEIGHT_SAMPLE_STDDEV` or `YEAR_BEGIN_ASSET_WEIGHTED_POPULATION_STDDEV` |
| `materialization_ids` | Twelve distinct UUIDs for complete January–December receipts |

The caller selects receipt identities, not member economics. The operation normalizes their order by retained dates, uses historical membership, and refuses incomplete or incompatible evidence. It never chooses today's survivors or silently substitutes a later correction. Retry a read with the same request to replay its evidence; select a separately reviewed corrected receipt vector to analyze corrected evidence.

For the synthetic six-member example in the [methodology](../methodologies/metrics/metric-composite-annual-member-dispersion.md), the sample method returns `value="0.018708286934"`, `unit="DECIMAL_RETURN"`, `status="AVAILABLE"`, and both member counts equal six. Decimal values are serialized as strings. The worked example is covered by the registered API integration test; it is not a live portfolio fixture.

Always interpret `full_year_member_count` separately from `year_end_member_count`. Five full-year members can yield an available calculation while `reporting_applicability` is `NOT_REQUIRED_SMALL_POPULATION`. Fewer than two yield `UNAVAILABLE` with a null value. Unknown or missing source evidence yields an error instead of a reduced population.

Retain `result_fingerprint`, `method_version`, all `months`, and `members` for audit. `publication_state=CALCULATED_ANALYSIS` and `qualification=RETAINED_SOURCE_ATTESTATION_NOT_LIVE_QUALIFIED` require consumers to keep this analysis separate from an official report or compliance statement. Official selection, model-net policy, external return admission, and live producer qualification remain separately governed work.

See the methodology for formulas, exact refusal behavior, source ownership, weighted assets, and executable numerical examples. Existing composite TWR and inspection operations retain their existing contracts.

## Comparing pinned results

Call `POST /performance/composites/analytics/comparison` with the tenant header and `baseline` and `candidate`, each a complete annual request from the table above. Both must share composite, year, return view, currency and method; admitted definition digest and policy must also agree. Membership revisions and source cuts may differ. Both vectors pass existing retained admission and public annual v1 calculation. There is no automatic latest, original, approval or freeze selector.

The response retains both full results: monthly vectors, member economics, separate December/full-year counts, fingerprints, applicability and qualification. Sorted `full_year_members_added` and `full_year_members_removed` describe identity differences. `metric_id=DISPERSION_OUTPUT_DELTA`, `comparison_version=v1` and `convention=DIFFERENCE_OF_QUANTIZED_V1_OUTPUTS` define `value = candidate.value - baseline.value` in `DECIMAL_RETURN` units. This is a difference of quantized outputs, not relative growth, causal attribution, investment P&L, materiality or approval.

Baseline annual returns 1%–6% produce `0.018708286934`; candidate {1%,2%,3%,4%,5%,7%} produces `0.021602468995`; difference is `0.002894182061`. The synthetic fixture adds member 7 and removes member 6. A 1%–5% candidate produces `0.015811388301`, difference `-0.002896898633` and removed member 6. Changing original member 1's return to 7% instead yields the same dispersion with changed evidence. Zero difference does not prove no impact elsewhere.

If either side is unavailable, comparison value stays null with `UNAVAILABLE` and side-prefixed reasons, such as `CANDIDATE_ANNUAL_DISPERSION_INSUFFICIENT_MEMBERS`. Never substitute zero. Either-side absent tenant receipts yield 404, incomplete receipt/publication 409, invalid request or incompatible basis/domain 422, corrupt retained evidence 503. Errors contain no partial result. Reversing sides reverses available difference and swaps sets. Reordering receipts replays identically; later candidate retention does not alter a pinned baseline.

Internal callers and clients should retain both complete results, request vectors and comparison fingerprint; parse decimal strings with decimal arithmetic and consume API eligibility rather than reconstructing it. Complete synthetic examples are packaged in `app/api/examples/composite_annual_comparison.json` and exposed in OpenAPI; execution requires retained tenant evidence.

For Report-owned Excel consumption, retain baseline/candidate outputs, availability, method/version, December/full-year counts, source vectors and fingerprints in separate columns. With B2/C2 containing available API decimal strings and D2/E2 their statuses, a presentation formula is `=IF(AND(D2="AVAILABLE",E2="AVAILABLE"),NUMBERVALUE(C2,".",",")-NUMBERVALUE(B2,".",","),NA())`. Treat the returned comparison value as authoritative because Excel can introduce binary rounding. This is consumption guidance only; no Excel producer or official report authority is implemented. DEC-10/12/13, live qualification and full #610 selection/freeze/publication remain separately governed dependencies.
