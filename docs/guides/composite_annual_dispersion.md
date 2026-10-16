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

Always interpret `full_year_member_count` separately from `year_end_member_count`. Five full-year members can yield an available calculation of `0.015811388301`. Generic analysis has no approved reporting-profile or provision binding, so every population returns `reporting_applicability=REQUIRES_PROFILE_REVIEW` and `reporting_applicability_reason=APPROVED_REPORTING_PROFILE_NOT_BOUND`. Count alone grants no reporting exemption. This reporting reason is separate from financial `reason_codes`: an available number keeps an empty financial reason list. Fewer than two full-year members yield `UNAVAILABLE`, a null value and `ANNUAL_DISPERSION_INSUFFICIENT_MEMBERS`. A valid year can have no full-year intersection despite nonempty monthly populations; an empty monthly release remains refused. Unknown or missing source evidence yields an error instead of a reduced population.

Retain `result_fingerprint`, `method_version`, all `months`, and `members` for audit. `publication_state=CALCULATED_ANALYSIS` and `qualification=RETAINED_SOURCE_ATTESTATION_NOT_LIVE_QUALIFIED` require consumers to keep this analysis separate from an official report or compliance statement. Official selection, model-net policy, external return admission, and live producer qualification remain separately governed work.

### Reporting metadata compatibility

Legacy responses remain readable with either reporting-applicability value and without the new reporting reason. A legacy `NOT_REQUIRED_SMALL_POPULATION` value is historical metadata, not newly verified reporting authority. Preserve any previously captured original response body and fingerprint exactly; do not backfill or reserialize it as a corrected original. When decoding a legacy response for a projection, `model_dump(exclude_unset=True)` preserves the omitted reason field.

The annual route calculates a response from the selected retained receipt vector; it does not introduce a stored-original result workflow. A fresh calculation now includes corrected reporting metadata in its result fingerprint, even when its financial value, source receipts and method are unchanged. The new response therefore has a new identity. Comparisons retain both corrected annual responses and bind them into the pair fingerprint. There is no new approval source, caller-controlled reporting profile, automatic official selection or change to the financial method. Approved provision-level exemption support and live upstream/downstream acceptance remain open under #608/#923.

See the methodology for formulas, exact refusal behavior, source ownership, weighted assets, and executable numerical examples. Existing composite TWR and inspection operations retain their existing contracts.

## Comparing pinned results

Call `POST /performance/composites/analytics/comparison` with the tenant header and `baseline` and `candidate`, each a complete annual request from the table above. Both must share composite, year, return view, currency and method; admitted definition digest and policy must also agree. Membership revisions and source cuts may differ. Both vectors pass existing retained admission and public annual v1 calculation. There is no automatic latest, original, approval or freeze selector.

The response retains both full results: monthly vectors, member economics, separate December/full-year counts, fingerprints, applicability and qualification. Sorted `full_year_members_added` and `full_year_members_removed` describe identity differences. `metric_id=DISPERSION_OUTPUT_DELTA`, `comparison_version=v1` and `convention=DIFFERENCE_OF_QUANTIZED_V1_OUTPUTS` define `value = candidate.value - baseline.value` in `DECIMAL_RETURN` units. This is a difference of quantized outputs, not relative growth, causal attribution, investment P&L, materiality or approval.

Baseline annual returns 1%–6% produce `0.018708286934`; candidate {1%,2%,3%,4%,5%,7%} produces `0.021602468995`; difference is `0.002894182061`. The synthetic fixture adds member 7 and removes member 6. A 1%–5% candidate produces `0.015811388301`, difference `-0.002896898633` and removed member 6. Changing original member 1's return to 7% instead yields the same dispersion with changed evidence. Zero difference does not prove no impact elsewhere.

If either side is unavailable, comparison value stays null with `UNAVAILABLE` and side-prefixed reasons, such as `CANDIDATE_ANNUAL_DISPERSION_INSUFFICIENT_MEMBERS`. Never substitute zero. Either-side absent tenant receipts yield 404, incomplete receipt/publication 409, invalid request or incompatible basis/domain 422, corrupt retained evidence 503. Errors contain no partial result. Reversing sides reverses available difference and swaps sets. Reordering receipts replays identically; later candidate retention does not alter a pinned baseline.

Internal callers and clients should retain both complete results, request vectors and comparison fingerprint; parse decimal strings with decimal arithmetic and consume API eligibility rather than reconstructing it. Complete synthetic examples are packaged in `app/api/examples/composite_annual_comparison.json` and exposed in OpenAPI; execution requires retained tenant evidence.

For Report-owned Excel consumption, retain baseline/candidate outputs, availability, method/version, December/full-year counts, source vectors and fingerprints in separate columns. With B2/C2 containing available API decimal strings and D2/E2 their statuses, a presentation formula is `=IF(AND(D2="AVAILABLE",E2="AVAILABLE"),NUMBERVALUE(C2,".",",")-NUMBERVALUE(B2,".",","),NA())`. Treat the returned comparison value as authoritative because Excel can introduce binary rounding. This is consumption guidance only; no Excel producer or official report authority is implemented. DEC-10/12/13, live qualification and full #610 selection/freeze/publication remain separately governed dependencies.

## PostgreSQL retained-consumer acceptance

The existing required PostgreSQL materialization target also exercises these registered HTTP operations through their default retained reader. Its isolated database schema is provisioned by the complete thirteen-table durable schema owner; controlled tenant publications use the existing materialization and fact stores. The tests do not override the financial reader or calculation ports.

Independent rational/Decimal oracles check sample and equal-asset weighted population dispersion, paired differences and reversal. The same target covers historical full-year/December counts, unavailable null versus available zero, two-tenant receipt authority, reordered replay, changed-evidence fingerprints and refusal without a partial pair. SQL observation and before/after retained-row snapshots establish read-only consumption. Closing and reopening the retained store preserves a pinned original and replays the corrected pair; this is store reopen evidence, not process or worker restart evidence.

From the `lotus-performance` repository root, with `LOTUS_POSTGRES_PLAN_DATABASE_URL` set to a separately provisioned PostgreSQL database, run:

```powershell
python scripts/postgres_concurrency_contracts_gate.py --target tests/benchmarks/test_postgres_composite_materialization.py
```

```bash
python scripts/postgres_concurrency_contracts_gate.py --target tests/benchmarks/test_postgres_composite_materialization.py
```

The unchanged native gate requires every collected contract to pass with no skips, using pytest's JUnit report. This controlled retained-consumer proof does not certify live ingestion, institutional methodology, official generation selection or the complete upstream/downstream consumer chain.
