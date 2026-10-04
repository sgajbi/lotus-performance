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
